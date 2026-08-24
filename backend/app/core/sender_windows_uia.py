"""Windows 微信 UI Automation 消息发送器。

优先通过 wechatauto-replica 提供的 UIA 驱动操作微信控件，避免移动真实鼠标。
该驱动针对微信 4.1.12+ 的自绘界面，会在必要时热激活 Qt accessibility gate，
但不会自动降级到坐标/OCR；鼠标兜底由上层配置显式决定。
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
from pathlib import Path
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from typing import Any

from app.config import get_config
from app.core.send_result import SendResult

logger = logging.getLogger(__name__)

_UIA_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wx-uia")
_PYWIN32_DLL_HANDLES: list[object] = []


def _window_pid_from_control(driver: Any, control: Any) -> int | None:
    """Resolve a UIA control's owning process without activating it."""
    for attribute in ("ProcessId", "process_id"):
        try:
            value = getattr(control, attribute, None)
            if callable(value):
                value = value()
            pid = int(value or 0)
            if pid > 0:
                return pid
        except (TypeError, ValueError, AttributeError):
            pass

    try:
        hwnd = int(getattr(control, "NativeWindowHandle", 0) or 0)
    except (TypeError, ValueError):
        hwnd = 0
    if not hwnd:
        return None

    resolver = getattr(driver, "_pid_from_hwnd", None)
    if callable(resolver):
        try:
            pid = int(resolver(hwnd) or 0)
            if pid > 0:
                return pid
        except (TypeError, ValueError, OSError):
            pass

    if os.name != "nt":
        return None
    try:
        pid_value = wintypes.DWORD()
        if not ctypes.windll.user32.GetWindowThreadProcessId(
            wintypes.HWND(hwnd), ctypes.byref(pid_value)
        ):
            return None
        return int(pid_value.value) or None
    except (AttributeError, OSError):
        return None


def _prepare_windows_imports() -> None:
    """Make pywin32 importable from the bundled/embedded Python runtime."""
    if os.name != "nt":
        return

    site_dirs: list[Path] = []
    for raw_path in tuple(sys.path):
        if raw_path:
            candidate = Path(raw_path)
            if candidate.name.casefold() == "site-packages":
                site_dirs.append(candidate)

    for site_dir in site_dirs:
        dll_dir = site_dir / "pywin32_system32"
        if dll_dir.is_dir():
            try:
                handle = os.add_dll_directory(str(dll_dir))
                _PYWIN32_DLL_HANDLES.append(handle)
            except (AttributeError, OSError):
                pass

        for relative in ("win32", "win32/lib", "pythonwin"):
            module_dir = site_dir / relative
            if module_dir.is_dir() and str(module_dir) not in sys.path:
                sys.path.insert(0, str(module_dir))


class _SelectedWeChatUIA:
    """Bind the third-party UIA driver to the account-selected Weixin process."""

    def __init__(self, target_pid: int | None):
        _prepare_windows_imports()
        try:
            from wechatauto.uia_driver import WeChatUIA
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise RuntimeError(
                "UIA 发送依赖未安装，请执行: pip install wechatauto-replica"
            ) from exc

        class BoundDriver(WeChatUIA):
            def _wechat_hwnds(self):
                handles = super()._wechat_hwnds()
                if target_pid is None:
                    return []
                return [
                    handle
                    for handle in handles
                    if self._pid_from_hwnd(handle) == target_pid
                ]

        self.driver = BoundDriver()


class WindowsUIASender:
    """Send Windows WeChat text without pyautogui or physical mouse movement."""

    def __init__(self):
        _prepare_windows_imports()
        self._driver: Any = None
        self._driver_pid: int | None = None
        self._driver_lock = threading.Lock()
        win_cfg = get_config().windows_sender if hasattr(get_config(), "windows_sender") else {}
        configured_mode = str(win_cfg.get("send_mode", "") or "").strip().lower()
        if configured_mode not in {"foreground_uia", "background_uia", "auto"}:
            configured_mode = (
                "background_uia"
                if bool(win_cfg.get("background_mode", False))
                else "foreground_uia"
            )
        self._send_mode = configured_mode
        self._background_mode = configured_mode == "background_uia"
        self._send_key_fallback = str(
            win_cfg.get("send_key_fallback", "none") or "none"
        ).strip().lower()
        if self._send_key_fallback not in {"none", "enter", "ctrl_enter"}:
            self._send_key_fallback = "none"
        self._input_verify_timeout = float(win_cfg.get("input_verify_timeout", 3.0))
        self._ui_verify_timeout = float(win_cfg.get("ui_verify_timeout", 4.0))
        self._require_ui_verify = bool(win_cfg.get("require_ui_verify", True))
        self._last_result: SendResult | None = None
        self._last_binding_error: dict[str, Any] | None = None
        self._last_background_capability: dict[str, Any] = {}

    async def send_text(
        self,
        msg: str,
        receiver: str,
        is_group: bool = False,
        target_id: str = "",
        attempt_id: str = "",
    ) -> bool:
        result = await self.send_text_result(msg, receiver, is_group, target_id, attempt_id)
        return result.success

    async def send_text_result(
        self,
        msg: str,
        receiver: str,
        is_group: bool = False,
        target_id: str = "",
        attempt_id: str = "",
    ) -> SendResult:
        """Send text and retain stage-level UIA diagnostics."""
        method = self._send_mode
        result = SendResult.for_message(msg, target_id or receiver, method, attempt_id)
        if not msg or not receiver:
            result.fail("draft", "invalid_request", "消息内容或接收者为空")
            self._last_result = result
            return result
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            _UIA_EXECUTOR,
            self._send_text_sync_result,
            msg,
            receiver,
            is_group,
            target_id,
            attempt_id,
        )
        self._last_result = result
        return result

    @property
    def last_result(self) -> SendResult | None:
        return self._last_result

    async def diagnose(self) -> dict[str, Any]:
        """Probe the selected account and UIA controls without sending."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_UIA_EXECUTOR, self._diagnose_sync)

    async def is_wechat_running(self) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_UIA_EXECUTOR, self._is_running_sync)

    async def open_chat(self, receiver: str, is_group: bool = False) -> bool:
        if not receiver:
            return False
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _UIA_EXECUTOR,
            self._open_chat_sync,
            receiver,
            is_group,
        )

    def _get_bound_pid(self) -> int | None:
        try:
            from app.core.platform import Platform

            pid = Platform.get().key_extractor.bound_pid
            return int(pid) if pid else None
        except Exception:
            return None

    def _binding_info(self) -> dict[str, Any]:
        """Return the selected-account/PID binding state used by UIA."""
        info: dict[str, Any] = {
            "selected_account": "",
            "bound_account": "",
            "bound_pid": None,
            "status": "ambiguous_process",
            "error_code": "ambiguous_process",
            "error_message": "没有确认所选微信账号对应的主进程 PID，拒绝选择任意窗口",
        }
        try:
            from app.core.platform import Platform

            extractor = Platform.get().key_extractor
            selected = (
                extractor.selected_account()
                if hasattr(extractor, "selected_account")
                else ""
            )
            bound_account = str(getattr(extractor, "bound_account", "") or "")
            bound_pid = getattr(extractor, "bound_pid", None)
            info["selected_account"] = str(selected or "")
            info["bound_account"] = bound_account
            info["bound_pid"] = int(bound_pid) if bound_pid else None
        except Exception as exc:
            info.update(
                status="binding_unavailable",
                error_code="binding_unavailable",
                error_message=f"无法读取微信账号绑定状态: {exc}",
            )
            return info

        selected = str(info["selected_account"] or "").casefold()
        bound_account = str(info["bound_account"] or "").casefold()
        if not info["bound_pid"]:
            return info
        if selected and bound_account and selected != bound_account:
            return {
                **info,
                "status": "account_binding_mismatch",
                "error_code": "account_binding_mismatch",
                "error_message": (
                    f"所选账号 {info['selected_account']} 与已绑定账号 "
                    f"{info['bound_account']} 不一致"
                ),
            }
        if selected and not bound_account:
            return {
                **info,
                "status": "account_binding_unverified",
                "error_code": "account_binding_unverified",
                "error_message": "已找到微信进程 PID，但无法确认它属于所选账号",
            }
        return {
            **info,
            "status": "bound",
            "error_code": "",
            "error_message": "",
        }

    def _get_driver(self):
        target_pid = self._get_bound_pid()
        with self._driver_lock:
            if self._driver is None or self._driver_pid != target_pid:
                self._driver = _SelectedWeChatUIA(target_pid).driver
                self._driver_pid = target_pid
            return self._driver

    def _is_running_sync(self) -> bool:
        _prepare_windows_imports()
        try:
            if self._binding_info()["status"] != "bound":
                return False
            driver = self._get_driver()
            return driver._find_main() is not None
        except Exception as exc:
            logger.debug("UIA 检查微信进程失败: %s", exc)
            return False

    def _ensure_driver_window(self, method: str | None = None):
        binding = self._binding_info()
        if binding["status"] != "bound":
            self._last_binding_error = binding
            logger.error("UIA 账号绑定不可用 | code=%s | message=%s", binding["error_code"], binding["error_message"])
            return None

        self._last_binding_error = None
        driver = self._get_driver()
        background = method == "background_uia" if method else self._background_mode
        if background:
            # wechatauto.ensure_window() deliberately activates the window. In
            # background mode, only bind to an already materialized UIA tree.
            window = driver._find_main()
            if window is None:
                logger.error("后台 UIA 未找到可访问的微信主窗口，不切换前台")
                return None
            driver._win = window
            if not self._window_matches_bound_pid(driver, window, binding["bound_pid"]):
                return None
            return driver
        if not driver.ensure_window():
            logger.error("UIA 未找到可访问的微信主窗口")
            return None
        if not self._window_matches_bound_pid(driver, driver._win, binding["bound_pid"]):
            return None
        return driver

    def _window_matches_bound_pid(self, driver: Any, window: Any, target_pid: int) -> bool:
        actual_pid = _window_pid_from_control(driver, window)
        if actual_pid != int(target_pid):
            self._last_binding_error = {
                "status": "window_pid_mismatch",
                "error_code": "window_pid_mismatch",
                "error_message": (
                    f"UIA 窗口 PID {actual_pid or '-'} 与绑定 PID {target_pid} 不一致"
                ),
                "bound_pid": target_pid,
                "window_pid": actual_pid,
            }
            logger.error(self._last_binding_error["error_message"])
            return False
        return True

    @staticmethod
    def _supports_legacy_value(control: Any) -> bool:
        try:
            pattern = control.GetLegacyIAccessiblePattern()
            return pattern is not None and callable(getattr(pattern, "SetValue", None))
        except Exception:
            return False

    @staticmethod
    def _supports_invoke(control: Any) -> bool:
        try:
            legacy = control.GetLegacyIAccessiblePattern()
            if legacy is not None and callable(getattr(legacy, "DoDefaultAction", None)):
                return True
        except Exception:
            pass
        try:
            import uiautomation as auto

            for pattern_id in (
                auto.PatternId.InvokePattern,
                auto.PatternId.SelectionItemPattern,
            ):
                if control.GetPattern(pattern_id) is not None:
                    return True
        except Exception:
            pass
        return False

    def _probe_background_capability(self) -> dict[str, Any]:
        """Check background-only patterns before attempting any send action."""
        capability: dict[str, Any] = {
            "available": False,
            "method": "background_uia",
            "reason_code": "",
            "reason": "",
            "window": None,
            "session_list": False,
            "search_box": None,
            "chat_input": None,
            "send_button": None,
        }
        binding = self._binding_info()
        if binding["status"] != "bound":
            capability.update(
                reason_code=binding["error_code"],
                reason=binding["error_message"],
            )
            self._last_background_capability = capability
            return capability

        driver = self._ensure_driver_window("background_uia")
        if driver is None:
            binding_error = self._last_binding_error or {}
            capability.update(
                reason_code=binding_error.get("error_code", "background_window_unavailable"),
                reason=binding_error.get("error_message", "后台 UIA 未找到绑定窗口"),
            )
            self._last_background_capability = capability
            return capability

        window = driver._win
        hwnd = int(getattr(window, "NativeWindowHandle", 0) or 0)
        capability["window"] = {
            "hwnd": hwnd,
            "pid": _window_pid_from_control(driver, window),
            "class_name": str(getattr(window, "ClassName", "") or ""),
        }
        missing: list[str] = []
        try:
            session_list = window.ListControl(AutomationId="session_list")
            capability["session_list"] = bool(session_list.Exists(0.2, 0.1))
        except Exception:
            capability["session_list"] = False
        if not capability["session_list"]:
            missing.append("session_list")

        try:
            search_box = driver._search_box(window)
        except Exception:
            search_box = None
        capability["search_box"] = (
            {
                "patterns": self._pattern_summary(search_box),
                "legacy_value": self._supports_legacy_value(search_box),
            }
            if search_box
            else None
        )
        if search_box is None or not self._supports_legacy_value(search_box):
            missing.append("search_box_legacy_value")

        try:
            input_control = driver._chat_input(window)
        except Exception:
            input_control = None
        capability["chat_input"] = (
            {
                "patterns": self._pattern_summary(input_control),
                "legacy_value": self._supports_legacy_value(input_control),
            }
            if input_control
            else None
        )
        if input_control is None or not self._supports_legacy_value(input_control):
            missing.append("chat_input_legacy_value")

        button = self._find_send_button(driver, input_control) if input_control else None
        capability["send_button"] = (
            {
                "name": str(getattr(button, "Name", "") or ""),
                "patterns": self._pattern_summary(button),
                "invokable": self._supports_invoke(button),
            }
            if button
            else None
        )
        if button is None or not self._supports_invoke(button):
            missing.append("send_button_invoke")

        if self._require_ui_verify:
            try:
                if driver._message_list() is None:
                    missing.append("message_list")
            except Exception:
                missing.append("message_list")

        if missing:
            capability.update(
                reason_code="background_patterns_incomplete",
                reason="后台 UIA 缺少必要控件或 Pattern: " + ", ".join(missing),
            )
        else:
            capability["available"] = True
        self._last_background_capability = capability
        return capability

    @staticmethod
    def _invoke_without_mouse(control: Any) -> bool:
        """Invoke/select a UIA control without uiautomation.Control.Click()."""
        try:
            import uiautomation as auto

            legacy_pattern = control.GetLegacyIAccessiblePattern()
            if legacy_pattern is not None and legacy_pattern.DoDefaultAction(waitTime=0.1):
                return True
            invoke_pattern = control.GetPattern(auto.PatternId.InvokePattern)
            if invoke_pattern is not None and invoke_pattern.Invoke(waitTime=0.1):
                return True
            selection_pattern = control.GetPattern(auto.PatternId.SelectionItemPattern)
            if selection_pattern is not None and selection_pattern.Select(waitTime=0.1):
                return True
        except Exception as exc:
            logger.debug("UIA 无鼠标调用控件失败: %s", exc)
        return False

    @staticmethod
    def _set_text_without_mouse(
        driver: Any,
        control: Any,
        text: str,
        allow_focus_fallback: bool = True,
    ) -> bool:
        """Set an edit control through ValuePattern, optionally using focus."""
        if not allow_focus_fallback:
            try:
                legacy_pattern = control.GetLegacyIAccessiblePattern()
                if legacy_pattern is not None and legacy_pattern.SetValue(text, waitTime=0.1):
                    return True
            except Exception:
                pass
            logger.debug("UIA LegacyIAccessiblePattern 写入失败，后台模式拒绝其他回退")
            return False

        try:
            value_pattern = control.GetValuePattern()
            if value_pattern is not None and not value_pattern.IsReadOnly:
                if value_pattern.SetValue(text, waitTime=0.1):
                    return True
        except Exception:
            pass

        try:
            import uiautomation as auto

            if not control.SetFocus():
                return False
            auto.SendKeys("{Ctrl}a{Delete}", waitTime=0.05)
            driver._clip_set(text)
            auto.SendKeys("{Ctrl}v", waitTime=0.05)
            return True
        except Exception as exc:
            logger.debug("UIA 无鼠标写入文本失败: %s", exc)
            return False

    def _open_chat_without_mouse(
        self,
        driver: Any,
        keyword: str,
        is_group: bool,
        background_mode: bool | None = None,
    ) -> bool:
        background = self._background_mode if background_mode is None else background_mode
        if background:
            return self._open_visible_session_without_mouse(driver, keyword)

        search_box = driver._search_box(driver._win)
        if search_box is None:
            return False

        try:
            keywords = driver._resolve_search_keyword(keyword)
        except Exception:
            keywords = [keyword]
        results = []
        used_keyword = keyword
        for candidate in keywords:
            if not self._set_text_without_mouse(
                driver,
                search_box,
                candidate,
                allow_focus_fallback=not background,
            ):
                continue
            time.sleep(0.8)
            results = driver._collect_results(candidate)
            if is_group:
                group_results = [
                    item for item in results
                    if (item.get("section") or "") == "群聊"
                ]
                if group_results:
                    results = group_results
                else:
                    results = [
                        item for item in results
                        if item.get("name") == candidate
                        and (item.get("section") or "") in {"最常使用", "最近使用"}
                    ]
            if results:
                used_keyword = candidate
                break

        if not results:
            return False

        exact = [item for item in results if item.get("name") == used_keyword]
        if len(exact) > 1 or (len(results) > 1 and not exact):
            logger.error(
                "UIA 搜索结果不唯一 | keyword=%s | count=%s",
                used_keyword,
                len(results),
            )
            return False
        chosen = (exact or results)[0]
        if not self._invoke_without_mouse(chosen["cell"]):
            return False
        expected_names = {chosen.get("name"), used_keyword}
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            current_name = driver.current_chat()
            if current_name and current_name in expected_names:
                return True
            time.sleep(0.2)
        return False

    def _open_visible_session_without_mouse(self, driver: Any, keyword: str) -> bool:
        """Open a visible recent session through UIA without search or focus."""
        try:
            session_list = driver._win.ListControl(AutomationId="session_list")
            if not session_list.Exists(0.5, 0.1):
                return False
        except Exception:
            return False

        candidates = {keyword.strip()}
        try:
            candidates.update(
                candidate.strip()
                for candidate in driver._resolve_search_keyword(keyword)
                if candidate and candidate.strip()
            )
        except Exception:
            pass

        try:
            sessions = session_list.GetChildren()
        except Exception:
            return False

        for session in sessions:
            try:
                name = (session.Name or "").split("\n", 1)[0].strip()
                aid = session.AutomationId or ""
            except Exception:
                continue
            if name not in candidates and aid not in {
                f"session_item_{candidate}" for candidate in candidates
            }:
                continue
            if not self._invoke_without_mouse(session):
                return False
            deadline = time.monotonic() + 2.5
            while time.monotonic() < deadline:
                current_name = driver.current_chat()
                if current_name and current_name in candidates:
                    return True
                time.sleep(0.2)
            return False
        return False

    @staticmethod
    def _find_send_button(driver: Any, input_control: Any) -> Any:
        """Find the current chat's UIA send button without using coordinates."""
        container = input_control
        for _ in range(4):
            try:
                container = container.GetParentControl()
            except Exception:
                break
            if container is None:
                break
            try:
                for name in ("发送", "发送(S)", "Send"):
                    button = container.ButtonControl(Name=name)
                    if button.Exists(0.2, 0.1):
                        return button
            except Exception:
                continue

        try:
            for name in ("发送", "发送(S)", "Send"):
                button = driver._win.ButtonControl(Name=name)
                if button.Exists(0.2, 0.1):
                    return button
        except Exception:
            pass
        return None

    @staticmethod
    def _invoke_control(control: Any) -> tuple[bool, str]:
        """Invoke a control through UIA patterns without moving the mouse."""
        try:
            import uiautomation as auto

            invoke_pattern = control.GetPattern(auto.PatternId.InvokePattern)
            if invoke_pattern is not None and invoke_pattern.Invoke(waitTime=0.2):
                return True, "InvokePattern"
        except Exception:
            pass
        try:
            legacy_pattern = control.GetLegacyIAccessiblePattern()
            if legacy_pattern is not None and legacy_pattern.DoDefaultAction(waitTime=0.2):
                return True, "LegacyIAccessible.DoDefaultAction"
        except Exception:
            pass
        try:
            import uiautomation as auto

            selection_pattern = control.GetPattern(auto.PatternId.SelectionItemPattern)
            if selection_pattern is not None and selection_pattern.Select(waitTime=0.2):
                return True, "SelectionItemPattern"
        except Exception:
            pass
        return False, ""

    @staticmethod
    def _post_enter_without_focus(driver: Any) -> bool:
        """Post an Enter key sequence to the WeChat window without activating it."""
        try:
            import ctypes

            hwnd = int(getattr(driver._win, "NativeWindowHandle", 0) or 0)
            if not hwnd:
                return False

            user32 = ctypes.windll.user32
            user32.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.PostMessageW.restype = wintypes.BOOL

            key_messages = (
                (0x0100, 0x000D, 0x001C0001),
                (0x0102, 0x000D, 0x001C0001),
                (0x0101, 0x000D, 0xC01C0001),
            )
            for message, wparam, lparam in key_messages:
                if not user32.PostMessageW(hwnd, message, wparam, lparam):
                    return False
                time.sleep(0.05)
            return True
        except Exception as exc:
            logger.debug("后台 UIA 投递回车失败: %s", exc)
            return False

    @staticmethod
    def _read_control_value(control: Any) -> str:
        try:
            pattern = control.GetValuePattern()
            if pattern is not None:
                return str(pattern.Value or "")
        except Exception:
            pass
        try:
            pattern = control.GetLegacyIAccessiblePattern()
            if pattern is not None:
                return str(getattr(pattern, "Value", "") or "")
        except Exception:
            pass
        return ""

    def _wait_input_empty(self, input_control: Any) -> bool:
        deadline = time.monotonic() + self._input_verify_timeout
        while time.monotonic() < deadline:
            if not self._read_control_value(input_control).strip():
                return True
            time.sleep(0.1)
        return not self._read_control_value(input_control).strip()

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").replace("\r\n", "\n").split())

    def _ui_contains_sent_text(self, driver: Any, text: str) -> bool:
        """Look for the exact text in the visible UIA message list."""
        try:
            message_list = driver._message_list()
        except Exception:
            message_list = None
        if message_list is None:
            return False
        expected = self._normalize_text(text)

        def walk(control: Any, depth: int = 0) -> bool:
            if depth > 12:
                return False
            try:
                name = self._normalize_text(getattr(control, "Name", ""))
                if name == expected:
                    return True
                children = control.GetChildren()
            except Exception:
                return False
            for child in children:
                if walk(child, depth + 1):
                    return True
            return False

        return walk(message_list)

    def _wait_ui_message(self, driver: Any, text: str) -> bool:
        deadline = time.monotonic() + self._ui_verify_timeout
        while time.monotonic() < deadline:
            if self._ui_contains_sent_text(driver, text):
                return True
            time.sleep(0.2)
        return self._ui_contains_sent_text(driver, text)

    @staticmethod
    def _pattern_summary(control: Any) -> dict[str, bool]:
        summary: dict[str, bool] = {}
        try:
            import uiautomation as auto

            for name, pattern_id in (
                ("ValuePattern", auto.PatternId.ValuePattern),
                ("InvokePattern", auto.PatternId.InvokePattern),
                ("SelectionItemPattern", auto.PatternId.SelectionItemPattern),
            ):
                try:
                    summary[name] = control.GetPattern(pattern_id) is not None
                except Exception:
                    summary[name] = False
        except Exception:
            pass
        try:
            summary["LegacyIAccessible"] = control.GetLegacyIAccessiblePattern() is not None
        except Exception:
            summary["LegacyIAccessible"] = False
        return summary

    def _open_chat_sync(self, receiver: str, is_group: bool) -> bool:
        try:
            for method in self._candidate_methods():
                driver = self._ensure_driver_window(method)
                if driver is None:
                    continue
                if self._open_chat_without_mouse(
                    driver,
                    receiver,
                    is_group,
                    background_mode=method == "background_uia",
                ):
                    return True
            logger.error("UIA 无法打开目标会话 | receiver=%s", receiver)
            return False
        except Exception as exc:
            logger.exception("UIA 打开会话失败 | receiver=%s | error=%s", receiver, exc)
            return False

    def _candidate_methods(self) -> list[str]:
        if self._send_mode == "auto":
            capability = self._probe_background_capability()
            if capability.get("available"):
                return ["background_uia", "foreground_uia"]
            logger.info(
                "后台 UIA 能力不足，自动选择前台 UIA | code=%s | reason=%s",
                capability.get("reason_code", ""),
                capability.get("reason", ""),
            )
            return ["foreground_uia"]
        return [self._send_mode]

    def _post_key_without_focus(self, driver: Any, ctrl: bool = False) -> bool:
        """Post an explicitly configured Enter/Ctrl+Enter sequence."""
        try:
            import ctypes

            hwnd = int(getattr(driver._win, "NativeWindowHandle", 0) or 0)
            if not hwnd:
                return False
            user32 = ctypes.windll.user32
            user32.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.PostMessageW.restype = wintypes.BOOL
            if ctrl and not user32.PostMessageW(hwnd, 0x0100, 0x11, 0x001D0001):
                return False
            for message, wparam, lparam in (
                (0x0100, 0x000D, 0x001C0001),
                (0x0102, 0x000D, 0x001C0001),
                (0x0101, 0x000D, 0xC01C0001),
            ):
                if not user32.PostMessageW(hwnd, message, wparam, lparam):
                    return False
                time.sleep(0.05)
            if ctrl and not user32.PostMessageW(hwnd, 0x0101, 0x11, 0xC01D0001):
                return False
            return True
        except Exception as exc:
            logger.debug("后台 UIA 按键投递失败: %s", exc)
            return False

    def _send_text_once(
        self,
        msg: str,
        receiver: str,
        is_group: bool,
        target_id: str,
        method: str,
        attempt_id: str = "",
    ) -> SendResult:
        result = SendResult.for_message(msg, target_id or receiver, method, attempt_id)
        background = method == "background_uia"
        try:
            driver = self._ensure_driver_window(method)
            if driver is None:
                binding_error = self._last_binding_error or {}
                return result.fail(
                    "window",
                    binding_error.get("error_code", "window_not_found"),
                    binding_error.get("error_message", "未找到绑定账号的 UIA 主窗口"),
                    binding=binding_error,
                )

            current_name = driver.current_chat()
            input_control = driver._chat_input()
            if current_name != receiver or input_control is None:
                opened = self._open_chat_without_mouse(
                    driver,
                    receiver,
                    is_group,
                    background_mode=background,
                )
                if not opened and target_id and target_id != receiver:
                    opened = self._open_chat_without_mouse(
                        driver,
                        target_id,
                        is_group,
                        background_mode=background,
                    )
                if not opened:
                    return result.fail("search", "chat_open_failed", "无法唯一打开目标会话")
                input_control = driver._chat_input()

            if input_control is None:
                return result.fail("draft", "input_not_found", "未找到聊天输入框")
            if not self._set_text_without_mouse(
                driver,
                input_control,
                msg,
                allow_focus_fallback=not background,
            ):
                return result.fail("draft", "draft_write_failed", "UIA 无法写入消息正文")

            written = self._read_control_value(input_control)
            if self._normalize_text(written) != self._normalize_text(msg):
                return result.fail(
                    "draft",
                    "draft_readback_mismatch",
                    "输入框回读内容与待发送正文不一致",
                    written=written,
                )

            button = self._find_send_button(driver, input_control)
            invoke_method = ""
            if button is not None:
                invoked, invoke_method = self._invoke_control(button)
                if not invoked:
                    return result.fail(
                        "invoke",
                        "send_button_invoke_failed",
                        "发送按钮存在但 Invoke/Legacy Pattern 调用失败",
                        patterns=self._pattern_summary(button),
                    )
                result.action_performed = True
            else:
                if self._send_key_fallback == "none":
                    return result.fail(
                        "invoke",
                        "send_button_not_found",
                        "未找到真实发送按钮，且未启用按键兜底",
                    )
                if background:
                    if not self._post_key_without_focus(
                        driver,
                        ctrl=self._send_key_fallback == "ctrl_enter",
                    ):
                        return result.fail(
                            "invoke",
                            "send_key_fallback_failed",
                            "后台 UIA 按键兜底投递失败",
                        )
                else:
                    if not input_control.SetFocus():
                        return result.fail("invoke", "input_focus_failed", "无法聚焦聊天输入框")
                    import uiautomation as auto

                    keys = "{Ctrl}{Enter}" if self._send_key_fallback == "ctrl_enter" else "{Enter}"
                    auto.SendKeys(keys, waitTime=0.1)
                result.action_performed = True
                invoke_method = f"key:{self._send_key_fallback}"

            result.details["invoke_method"] = invoke_method
            if not self._wait_input_empty(input_control):
                return result.fail(
                    "ui_verify",
                    "send_not_accepted",
                    "发送动作完成但输入框未清空，微信可能未接受发送",
                )
            result.draft_cleared = True

            ui_verified = self._wait_ui_message(driver, msg)
            result.ui_verified = ui_verified
            if not ui_verified and self._require_ui_verify:
                return result.fail(
                    "ui_verify",
                    "ui_message_not_found",
                    "输入框已清空，但消息列表未找到本人发送正文",
                )
            return result.sent(
                "ui_verify",
                action_performed=True,
                draft_cleared=True,
                ui_verified=ui_verified,
            )
        except Exception as exc:
            logger.exception("UIA 消息发送失败 | receiver=%s | error=%s", receiver, exc)
            return result.fail("invoke", "uia_exception", str(exc))

    def _diagnose_sync(self) -> dict[str, Any]:
        binding = self._binding_info()
        target_pid = binding.get("bound_pid")
        payload: dict[str, Any] = {
            "method": self._send_mode,
            "selected_account": binding.get("selected_account", ""),
            "bound_account": binding.get("bound_account", ""),
            "binding_status": binding.get("status", ""),
            "bound_pid": target_pid,
            "driver_pid": self._driver_pid,
            "window": None,
            "uia_available": False,
            "current_chat": "",
            "session_list": None,
            "search_box": None,
            "chat_input": None,
            "send_button": None,
            "error_code": binding.get("error_code", ""),
            "error": "",
        }
        if binding["status"] != "bound":
            payload["error"] = binding.get("error_message", "账号绑定不可用")
            return payload
        try:
            driver = self._get_driver()
            window = driver._find_main()
            if window is None:
                window = driver._win
            if window is None:
                payload["error"] = "未找到可访问的 mmui::MainWindow"
                return payload
            driver._win = window
            if not self._window_matches_bound_pid(driver, window, target_pid):
                binding_error = self._last_binding_error or {}
                payload["error_code"] = binding_error.get("error_code", "window_pid_mismatch")
                payload["error"] = binding_error.get("error_message", "UIA 窗口 PID 不匹配")
                payload["window"] = {
                    "hwnd": int(getattr(window, "NativeWindowHandle", 0) or 0),
                    "pid": _window_pid_from_control(driver, window),
                    "class_name": str(getattr(window, "ClassName", "") or ""),
                    "name": str(getattr(window, "Name", "") or ""),
                }
                return payload
            payload["uia_available"] = True
            payload["driver_pid"] = self._driver_pid
            hwnd = int(getattr(window, "NativeWindowHandle", 0) or 0)
            payload["window"] = {
                "hwnd": hwnd,
                "pid": _window_pid_from_control(driver, window),
                "class_name": str(getattr(window, "ClassName", "") or ""),
                "name": str(getattr(window, "Name", "") or ""),
            }
            session_list = None
            try:
                session_list = window.ListControl(AutomationId="session_list")
                if not session_list.Exists(0.2, 0.1):
                    session_list = None
            except Exception:
                session_list = None
            search_box = driver._search_box(window)
            input_control = driver._chat_input(window)
            button = self._find_send_button(driver, input_control) if input_control else None
            payload["current_chat"] = driver.current_chat() or ""
            payload["session_list"] = (
                {
                    "automation_id": getattr(session_list, "AutomationId", ""),
                    "name": getattr(session_list, "Name", ""),
                }
                if session_list
                else None
            )
            payload["search_box"] = (
                {
                    "name": getattr(search_box, "Name", ""),
                    "patterns": self._pattern_summary(search_box),
                }
                if search_box
                else None
            )
            payload["chat_input"] = (
                {
                    "automation_id": getattr(input_control, "AutomationId", ""),
                    "patterns": self._pattern_summary(input_control),
                }
                if input_control
                else None
            )
            payload["send_button"] = (
                {
                    "name": getattr(button, "Name", ""),
                    "patterns": self._pattern_summary(button),
                }
                if button
                else None
            )
        except Exception as exc:
            payload["error"] = str(exc)
        return payload

    def _send_text_sync(
        self,
        msg: str,
        receiver: str,
        is_group: bool,
        target_id: str,
        attempt_id: str = "",
    ) -> bool:
        return self._send_text_sync_result(msg, receiver, is_group, target_id, attempt_id).success

    def _send_text_sync_result(
        self,
        msg: str,
        receiver: str,
        is_group: bool,
        target_id: str,
        attempt_id: str = "",
    ) -> SendResult:
        """Run the configured UIA mode(s) serially inside the UIA executor."""
        last_result: SendResult | None = None
        for method in self._candidate_methods():
            result = self._send_text_once(
                msg,
                receiver,
                is_group,
                target_id,
                method,
                attempt_id,
            )
            if result.success:
                return result
            last_result = result
            if self._send_mode != "auto":
                break
            if result.action_performed or result.draft_cleared:
                logger.error(
                    "UIA 已经执行过发送动作，禁止切换模式重复发送 | method=%s | stage=%s | code=%s",
                    method,
                    result.stage,
                    result.error_code,
                )
                break
            logger.warning(
                "UIA 模式发送失败，尝试下一模式 | method=%s | stage=%s | code=%s",
                method,
                result.stage,
                result.error_code,
            )

        return last_result or SendResult.for_message(
            msg,
            target_id or receiver,
            self._send_mode,
            attempt_id,
        ).fail("window", "uia_not_attempted", "没有可用的 UIA 发送模式")

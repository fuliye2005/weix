"""Windows 微信 UI Automation 消息发送器。

优先通过 wechatauto-replica 提供的 UIA 驱动操作微信控件，避免移动真实鼠标。
该驱动针对微信 4.1.12+ 的自绘界面，会在必要时热激活 Qt accessibility gate，
但不会自动降级到坐标/OCR；鼠标兜底由上层配置显式决定。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from typing import Any

from app.config import get_config

logger = logging.getLogger(__name__)

_UIA_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wx-uia")


class _SelectedWeChatUIA:
    """Bind the third-party UIA driver to the account-selected Weixin process."""

    def __init__(self, target_pid: int | None):
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
                    return handles
                return [
                    handle
                    for handle in handles
                    if self._pid_from_hwnd(handle) == target_pid
                ]

        self.driver = BoundDriver()


class WindowsUIASender:
    """Send Windows WeChat text without pyautogui or physical mouse movement."""

    def __init__(self):
        self._driver: Any = None
        self._driver_pid: int | None = None
        self._driver_lock = threading.Lock()
        win_cfg = get_config().windows_sender if hasattr(get_config(), "windows_sender") else {}
        self._background_mode = bool(win_cfg.get("background_mode", True))

    async def send_text(
        self,
        msg: str,
        receiver: str,
        is_group: bool = False,
        target_id: str = "",
    ) -> bool:
        if not msg or not receiver:
            return False
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _UIA_EXECUTOR,
            self._send_text_sync,
            msg,
            receiver,
            is_group,
            target_id,
        )

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

    def _get_driver(self):
        target_pid = self._get_bound_pid()
        with self._driver_lock:
            if self._driver is None or self._driver_pid != target_pid:
                self._driver = _SelectedWeChatUIA(target_pid).driver
                self._driver_pid = target_pid
            return self._driver

    def _is_running_sync(self) -> bool:
        try:
            from wechatauto.uia_driver import WeChatUIA

            return bool(WeChatUIA.is_running())
        except Exception as exc:
            logger.debug("UIA 检查微信进程失败: %s", exc)
            return False

    def _ensure_driver_window(self):
        driver = self._get_driver()
        if self._background_mode:
            # wechatauto.ensure_window() deliberately activates the window. In
            # background mode, only bind to an already materialized UIA tree.
            window = driver._find_main()
            if window is None:
                logger.error("后台 UIA 未找到可访问的微信主窗口，不切换前台")
                return None
            driver._win = window
            return driver
        if not driver.ensure_window():
            logger.error("UIA 未找到可访问的微信主窗口")
            return None
        return driver

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
    ) -> bool:
        if self._background_mode:
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
                allow_focus_fallback=not self._background_mode,
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
                button = container.ButtonControl(Name="发送")
                if button.Exists(0.2, 0.1):
                    return button
            except Exception:
                continue

        try:
            button = driver._win.ButtonControl(Name="发送")
            if button.Exists(0.2, 0.1):
                return button
        except Exception:
            pass
        return None

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

    def _open_chat_sync(self, receiver: str, is_group: bool) -> bool:
        try:
            driver = self._ensure_driver_window()
            if driver is None:
                return False
            if self._open_chat_without_mouse(driver, receiver, is_group):
                return True
            logger.error("UIA 无法打开目标会话 | receiver=%s", receiver)
            return False
        except Exception as exc:
            logger.exception("UIA 打开会话失败 | receiver=%s | error=%s", receiver, exc)
            return False

    def _send_text_sync(
        self,
        msg: str,
        receiver: str,
        is_group: bool,
        target_id: str,
    ) -> bool:
        try:
            driver = self._ensure_driver_window()
            if driver is None:
                return False

            current_name = driver.current_chat()
            input_control = driver._chat_input()
            if current_name != receiver or input_control is None:
                opened = self._open_chat_without_mouse(driver, receiver, is_group)
                if not opened and target_id and target_id != receiver:
                    opened = self._open_chat_without_mouse(driver, target_id, is_group)
                if not opened:
                    logger.error("UIA 无法打开目标会话 | receiver=%s", receiver)
                    return False
                input_control = driver._chat_input()

            if input_control is None:
                logger.error("UIA 未找到聊天输入框 | receiver=%s", receiver)
                return False
            if not self._set_text_without_mouse(
                driver,
                input_control,
                msg,
                allow_focus_fallback=not self._background_mode,
            ):
                return False

            if self._background_mode:
                time.sleep(0.1)
                if not self._post_enter_without_focus(driver):
                    logger.error("后台 UIA 无法投递发送事件 | receiver=%s", receiver)
                    return False
                time.sleep(0.25)
                try:
                    remaining = input_control.GetValuePattern().Value
                except Exception:
                    remaining = ""
                if remaining:
                    logger.error(
                        "后台 UIA 发送事件已投递但输入框未清空 | receiver=%s",
                        receiver,
                    )
                    return False
                return True

            if not input_control.SetFocus():
                return False
            import uiautomation as auto

            auto.SendKeys("{Enter}", waitTime=0.1)
            return True
        except Exception as exc:
            logger.exception("UIA 消息发送失败 | receiver=%s | error=%s", receiver, exc)
            return False

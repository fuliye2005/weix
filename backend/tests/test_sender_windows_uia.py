from types import SimpleNamespace

import pytest

from app.core.send_result import SendResult
from app.core.sender_windows_uia import WindowsUIASender


class FakeValuePattern:
    IsReadOnly = False

    def __init__(self):
        self.value = ""

    @property
    def Value(self):
        return self.value

    def SetValue(self, value, waitTime=0.1):
        self.value = value
        return True


class FakeLegacyValuePattern:
    def __init__(self, value_pattern):
        self.value_pattern = value_pattern

    def SetValue(self, value, waitTime=0.1):
        self.value_pattern.value = value
        return True


class FakeInput:
    def __init__(self):
        self.value_pattern = FakeValuePattern()
        self.legacy_value_pattern = FakeLegacyValuePattern(self.value_pattern)
        self.focused = False

    def GetLegacyIAccessiblePattern(self):
        return self.legacy_value_pattern

    def GetValuePattern(self):
        return self.value_pattern

    def SetFocus(self):
        self.focused = True
        return True


class FakeLegacyPattern:
    def __init__(self):
        self.invoked = False

    def DoDefaultAction(self, waitTime=0.1):
        self.invoked = True
        return True


class FakeSendButton:
    def __init__(self):
        self.legacy_pattern = FakeLegacyPattern()

    def GetLegacyIAccessiblePattern(self):
        return self.legacy_pattern


class FakeDriver:
    def __init__(self):
        self.input = FakeInput()
        self.sent = []
        self._win = self

    def _find_main(self):
        return self

    def current_chat(self):
        return "测试联系人"

    def _chat_input(self):
        return self.input


class FakeDiagnosticSessionList:
    AutomationId = "session_list"
    Name = "会话列表"

    def Exists(self, *_args):
        return False


class FakeDiagnosticWindow:
    NativeWindowHandle = 1234
    ClassName = "mmui::MainWindow"
    Name = "微信"

    def ListControl(self, **_kwargs):
        return FakeDiagnosticSessionList()


class FakeDiagnosticDriver:
    def __init__(self):
        self._win = FakeDiagnosticWindow()

    def _find_main(self):
        return self._win

    def _pid_from_hwnd(self, hwnd):
        assert hwnd == 1234
        return 5678

    def _search_box(self, _window):
        return None

    def _chat_input(self, _window):
        return None

    def current_chat(self):
        return "测试联系人"


class FakeSession:
    def __init__(self, name, aid=""):
        self.Name = name
        self.AutomationId = aid


class FakeSessionList:
    def __init__(self, sessions):
        self._sessions = sessions

    def Exists(self, *_args):
        return True

    def GetChildren(self):
        return list(self._sessions)


class FakeVisibleDriver(FakeDriver):
    def __init__(self, sessions):
        super().__init__()
        self._session_list = FakeSessionList(sessions)

    def ListControl(self, **_kwargs):
        return self._session_list


@pytest.mark.asyncio
async def test_uia_sender_writes_text_without_click(monkeypatch):
    sender = WindowsUIASender()
    sender._send_mode = "background_uia"
    sender._background_mode = True
    sender._send_key_fallback = "enter"
    sender._require_ui_verify = False
    driver = FakeDriver()
    monkeypatch.setattr(sender, "_get_driver", lambda: driver)
    monkeypatch.setattr(sender, "_ensure_driver_window", lambda _method=None: driver)
    def post_key(_driver, ctrl=False):
        driver.input.value_pattern.value = ""
        return True

    monkeypatch.setattr(sender, "_post_key_without_focus", post_key)
    monkeypatch.setattr(
        "uiautomation.SendKeys",
        lambda *args, **kwargs: driver.sent.append(args[0]),
    )

    assert await sender.send_text("你好", "测试联系人") is True
    assert driver.input.value_pattern.value == ""
    assert driver.input.focused is False
    assert driver.sent == []


@pytest.mark.asyncio
async def test_background_uia_does_not_call_ensure_window(monkeypatch):
    sender = WindowsUIASender()

    class Driver(FakeDriver):
        def ensure_window(self):
            raise AssertionError("background mode must not call ensure_window")

    driver = Driver()
    monkeypatch.setattr(sender, "_get_driver", lambda: driver)
    sender._send_mode = "background_uia"
    sender._background_mode = True
    sender._send_key_fallback = "enter"
    sender._require_ui_verify = False
    monkeypatch.setattr(
        sender,
        "_binding_info",
        lambda: {
            "selected_account": "wxid_selected_1",
            "bound_account": "wxid_selected_1",
            "bound_pid": 5678,
            "status": "bound",
            "error_code": "",
            "error_message": "",
        },
    )
    monkeypatch.setattr(sender, "_window_matches_bound_pid", lambda *_args: True)
    monkeypatch.setattr(
        sender,
        "_post_key_without_focus",
        lambda _driver, ctrl=False: driver.input.value_pattern.__setattr__("value", "") or True,
    )

    assert await sender.send_text("后台发送", "测试联系人") is True


def test_background_text_write_prefers_legacy_value_pattern():
    sender = WindowsUIASender()
    driver = FakeDriver()

    class LegacyOnlyInput(FakeInput):
        def GetValuePattern(self):
            raise AssertionError("background mode must not use ValuePattern")

    driver.input = LegacyOnlyInput()
    assert sender._set_text_without_mouse(
        driver,
        driver.input,
        "只走 Legacy",
        allow_focus_fallback=False,
    ) is True
    assert driver.input.value_pattern.value == "只走 Legacy"


def test_uia_diagnose_resolves_window_pid_without_sending(monkeypatch):
    sender = WindowsUIASender()
    driver = FakeDiagnosticDriver()
    probe_methods = []
    monkeypatch.setattr(
        sender,
        "_ensure_driver_window",
        lambda method=None: probe_methods.append(method) or driver,
    )
    monkeypatch.setattr(sender, "_ensure_foreground_navigation", lambda value: value)
    monkeypatch.setattr(
        sender,
        "_binding_info",
        lambda: {
            "selected_account": "wxid_selected_1",
            "bound_account": "wxid_selected_1",
            "bound_pid": 5678,
            "status": "bound",
            "error_code": "",
            "error_message": "",
        },
    )

    result = sender._diagnose_sync()

    assert result["uia_available"] is True
    assert result["bound_pid"] == 5678
    assert result["window"]["hwnd"] == 1234
    assert result["window"]["pid"] == 5678
    assert result["current_chat"] == "测试联系人"
    assert result["probe_method"] == "foreground_uia"
    assert probe_methods == ["foreground_uia"]
    assert result["error"] == ""


def test_uia_diagnose_reports_window_initialization_error(monkeypatch):
    sender = WindowsUIASender()
    monkeypatch.setattr(sender, "_ensure_driver_window", lambda _method=None: None)
    monkeypatch.setattr(
        sender,
        "_binding_info",
        lambda: {
            "selected_account": "wxid_selected_1",
            "bound_account": "wxid_selected_1",
            "bound_pid": 5678,
            "status": "bound",
            "error_code": "",
            "error_message": "",
        },
    )

    result = sender._diagnose_sync()

    assert result["uia_available"] is False
    assert result["error_code"] == "uia_window_unavailable"


def test_foreground_navigation_can_be_disabled_without_window_resize(monkeypatch):
    sender = WindowsUIASender()
    sender._ensure_full_layout = False
    driver = FakeDiagnosticDriver()
    monkeypatch.setattr(sender, "_navigation_controls_ready", lambda _driver: False)

    assert sender._ensure_foreground_navigation(driver) is None
    assert sender._last_binding_error["error_code"] == "navigation_controls_missing"


def test_visible_session_refuses_duplicate_names(monkeypatch):
    sender = WindowsUIASender()
    driver = FakeVisibleDriver([
        FakeSession("文件传输助手", "session_item_1"),
        FakeSession("文件传输助手", "session_item_2"),
    ])
    opened = sender._open_visible_session_without_mouse(driver, "文件传输助手")

    assert opened is False
    assert sender._last_navigation_error["error_code"] == "ambiguous_search_result"


def test_search_open_requires_chat_input_after_title_match(monkeypatch):
    sender = WindowsUIASender()
    driver = FakeDriver()
    cell = FakeSession("文件传输助手", "search_item_1")
    monkeypatch.setattr(sender, "_set_text_without_mouse", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(driver, "_chat_input", lambda: None)
    monkeypatch.setattr(driver, "current_chat", lambda: "文件传输助手")
    monkeypatch.setattr(
        driver,
        "_search_box",
        lambda *_args, **_kwargs: driver.input,
        raising=False,
    )
    monkeypatch.setattr(
        driver,
        "_collect_results",
        lambda _keyword: [{"cell": cell, "name": "文件传输助手", "section": "联系人"}],
        raising=False,
    )
    monkeypatch.setattr(sender, "_ensure_foreground_navigation", lambda value: value)
    monkeypatch.setattr(sender, "_invoke_without_mouse", lambda _control: True)

    opened = sender._open_chat_without_mouse(driver, "文件传输助手", False, background_mode=False)

    assert opened is False
    assert sender._last_navigation_error["error_code"] == "chat_open_verification_failed"


def test_uia_binding_refuses_to_guess_when_pid_is_unknown(monkeypatch):
    sender = WindowsUIASender()
    platform = SimpleNamespace(
        key_extractor=SimpleNamespace(
            selected_account=lambda: "wxid_selected_1",
            bound_account="",
            bound_pid=None,
        )
    )
    monkeypatch.setattr("app.core.platform.Platform.get", lambda: platform)

    result = sender._binding_info()

    assert result["status"] == "ambiguous_process"
    assert result["error_code"] == "ambiguous_process"


def test_uia_binding_rejects_account_mismatch(monkeypatch):
    sender = WindowsUIASender()
    platform = SimpleNamespace(
        key_extractor=SimpleNamespace(
            selected_account=lambda: "wxid_selected_1",
            bound_account="wxid_other_2",
            bound_pid=5678,
        )
    )
    monkeypatch.setattr("app.core.platform.Platform.get", lambda: platform)

    result = sender._binding_info()

    assert result["status"] == "account_binding_mismatch"
    assert result["error_code"] == "account_binding_mismatch"


def test_auto_selects_foreground_when_background_probe_is_incomplete(monkeypatch):
    sender = WindowsUIASender()
    sender._send_mode = "auto"
    monkeypatch.setattr(
        sender,
        "_probe_background_capability",
        lambda: {
            "available": False,
            "reason_code": "background_patterns_incomplete",
            "reason": "send_button_invoke",
        },
    )

    assert sender._candidate_methods() == ["foreground_uia"]


def test_auto_does_not_retry_after_send_action(monkeypatch):
    sender = WindowsUIASender()
    sender._send_mode = "auto"
    calls = []

    attempted = SendResult.for_message("你好", "wxid_target", "background_uia")
    attempted.action_performed = True
    attempted.fail("ui_verify", "ui_message_not_found", "未找到消息")

    def send_once(*_args):
        calls.append(True)
        return attempted

    monkeypatch.setattr(sender, "_candidate_methods", lambda: ["background_uia", "foreground_uia"])
    monkeypatch.setattr(sender, "_send_text_once", send_once)

    result = sender._send_text_sync_result("你好", "目标", False, "wxid_target")

    assert result is attempted
    assert calls == [True]


def test_uia_retries_text_after_readback_mismatch(monkeypatch):
    sender = WindowsUIASender()
    sender._send_mode = "foreground_uia"
    sender._send_key_fallback = "none"
    sender._require_ui_verify = False
    driver = FakeDriver()
    calls = []

    monkeypatch.setattr(sender, "_ensure_driver_window", lambda _method=None: driver)
    monkeypatch.setattr(sender, "_find_send_button", lambda *_args: FakeSendButton())

    def write_text(_driver, control, text, allow_focus_fallback=True, prefer_focus_fallback=False):
        calls.append(prefer_focus_fallback)
        control.value_pattern.value = text if prefer_focus_fallback else "错误正文"
        return True

    monkeypatch.setattr(sender, "_set_text_without_mouse", write_text)

    def invoke(_control):
        driver.input.value_pattern.value = ""
        return True, "InvokePattern"

    monkeypatch.setattr(sender, "_invoke_control", invoke)

    result = sender._send_text_once(
        "正确正文",
        "测试联系人",
        False,
        "wxid_target",
        "foreground_uia",
    )

    assert result.success is True
    assert calls == [False, True]
    assert result.draft_cleared is True


def test_foreground_uia_focuses_input_before_invoke(monkeypatch):
    sender = WindowsUIASender()
    sender._send_mode = "foreground_uia"
    sender._send_key_fallback = "none"
    sender._require_ui_verify = False
    driver = FakeDriver()

    monkeypatch.setattr(sender, "_ensure_driver_window", lambda _method=None: driver)
    monkeypatch.setattr(
        sender,
        "_set_text_without_mouse",
        lambda _driver, control, text, **_kwargs: control.value_pattern.__setattr__("value", text) or True,
    )
    monkeypatch.setattr(sender, "_find_send_button", lambda *_args: FakeSendButton())

    def invoke(_control):
        assert driver.input.focused is True
        driver.input.value_pattern.value = ""
        return True, "LegacyIAccessible.DoDefaultAction"

    monkeypatch.setattr(sender, "_invoke_control", invoke)

    result = sender._send_text_once(
        "需要焦点",
        "测试联系人",
        False,
        "wxid_target",
        "foreground_uia",
    )

    assert result.success is True
    assert result.details["input_focused"] is True


def test_uia_rebuilds_driver_when_bound_account_changes(monkeypatch):
    sender = WindowsUIASender()
    binding = {
        "selected_account": "wxid_account_a",
        "bound_account": "wxid_account_a",
        "bound_pid": 5678,
        "status": "bound",
        "error_code": "",
        "error_message": "",
    }
    created = []

    class FakeBoundDriver:
        def __init__(self, pid):
            self.pid = pid

    class FakeDriverFactory:
        def __init__(self, pid):
            created.append(pid)
            self.driver = FakeBoundDriver(pid)

    monkeypatch.setattr(
        "app.core.sender_windows_uia._SelectedWeChatUIA",
        FakeDriverFactory,
    )
    monkeypatch.setattr(sender, "_binding_info", lambda: binding)

    first = sender._get_driver()
    assert sender._get_driver() is first

    binding["selected_account"] = "wxid_account_b"
    binding["bound_account"] = "wxid_account_b"
    second = sender._get_driver()

    assert second is not first
    assert created == [5678, 5678]

import pytest

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
    monkeypatch.setattr(sender, "_get_driver", lambda: driver)
    monkeypatch.setattr(sender, "_get_bound_pid", lambda: 5678)

    result = sender._diagnose_sync()

    assert result["uia_available"] is True
    assert result["bound_pid"] == 5678
    assert result["window"]["hwnd"] == 1234
    assert result["window"]["pid"] == 5678
    assert result["current_chat"] == "测试联系人"
    assert result["error"] == ""

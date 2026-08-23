import pytest

from app.core.sender_windows_uia import WindowsUIASender


class FakeValuePattern:
    IsReadOnly = False

    def __init__(self):
        self.value = ""

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


@pytest.mark.asyncio
async def test_uia_sender_writes_text_without_click(monkeypatch):
    sender = WindowsUIASender()
    driver = FakeDriver()
    monkeypatch.setattr(sender, "_get_driver", lambda: driver)
    def post_enter(_driver):
        driver.input.value_pattern.value = ""
        return True

    monkeypatch.setattr(sender, "_post_enter_without_focus", post_enter)
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
    monkeypatch.setattr(
        sender,
        "_post_enter_without_focus",
        lambda _driver: driver.input.value_pattern.__setattr__("value", "") or True,
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

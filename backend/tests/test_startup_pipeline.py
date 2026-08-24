import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import main


@pytest.fixture(autouse=True)
def reset_startup_globals():
    main._shutdown_event.clear()
    main._app_loop = None
    main._pipeline_start_lock = None
    main._pipeline = None
    yield
    main._shutdown_event.clear()
    main._app_loop = None
    main._pipeline_start_lock = None
    main._pipeline = None


@pytest.mark.asyncio
async def test_late_key_extraction_schedules_pipeline_start(monkeypatch, tmp_path):
    started = []
    pipeline = object()

    class FakeExtractor:
        def find_wechat_processes(self):
            return [1234]

        def scan_memory_for_keys(self, pid, stop_event=None):
            assert pid == 1234
            assert stop_event is main._shutdown_event
            return {"message/message_0.db": "00" * 32}

    async def fake_create(reason):
        started.append(reason)
        return pipeline

    monkeypatch.setattr(main, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(main, "_create_auto_reply_pipeline", fake_create)
    monkeypatch.setattr(
        "app.core.platform.Platform.get",
        lambda: SimpleNamespace(key_extractor=FakeExtractor()),
    )

    main._app_loop = asyncio.get_running_loop()
    main._pipeline_start_lock = asyncio.Lock()

    await asyncio.to_thread(main._try_auto_extract_keys)
    for _ in range(20):
        if main._pipeline is pipeline:
            break
        await asyncio.sleep(0.05)

    assert main._pipeline is pipeline
    assert started == ["数据库密钥提取完成"]


@pytest.mark.asyncio
async def test_pipeline_start_is_single_flight(monkeypatch):
    calls = 0
    pipeline = object()

    async def fake_create(reason):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return pipeline

    monkeypatch.setattr(main, "_create_auto_reply_pipeline", fake_create)

    result1, result2 = await asyncio.gather(
        main._ensure_auto_reply_pipeline_started("first"),
        main._ensure_auto_reply_pipeline_started("second"),
    )

    assert result1 is pipeline
    assert result2 is pipeline
    assert calls == 1


def test_windows_runtime_check_reports_pinned_environment(monkeypatch):
    from app.core import windows_runtime

    monkeypatch.setattr(windows_runtime.sys, "platform", "win32")
    monkeypatch.setattr(windows_runtime.sys, "version_info", (3, 12, 13))
    monkeypatch.setattr(windows_runtime, "_site_package_paths", lambda: [])
    monkeypatch.setattr(
        windows_runtime.importlib.metadata,
        "version",
        lambda package: windows_runtime.EXPECTED_PACKAGES[package],
    )
    monkeypatch.setattr(
        windows_runtime,
        "_module_path",
        lambda module: str(
            windows_runtime.Path(windows_runtime.sys.prefix)
            / "Lib"
            / "site-packages"
            / f"{module}.py"
        ),
    )

    result = windows_runtime.inspect_windows_runtime()

    assert result["ok"] is True
    assert result["packages"]["wechatauto-replica"] == "1.1.7"


def test_windows_runtime_rejects_wrong_python_version(monkeypatch):
    from app.core import windows_runtime

    monkeypatch.setattr(windows_runtime.sys, "platform", "win32")
    monkeypatch.setattr(windows_runtime.sys, "version_info", (3, 13, 0))
    monkeypatch.setattr(windows_runtime, "_site_package_paths", lambda: [])
    monkeypatch.setattr(
        windows_runtime.importlib.metadata,
        "version",
        lambda package: windows_runtime.EXPECTED_PACKAGES[package],
    )
    monkeypatch.setattr(
        windows_runtime,
        "_module_path",
        lambda module: str(
            windows_runtime.Path(windows_runtime.sys.prefix)
            / "Lib"
            / "site-packages"
            / f"{module}.py"
        ),
    )

    result = windows_runtime.inspect_windows_runtime()

    assert result["ok"] is False
    assert any("Python 3.12" in error for error in result["errors"])


def test_startup_refuses_to_guess_when_multiple_wechat_processes_are_unselected(
    monkeypatch,
    tmp_path,
):
    scanned = []

    class FakeExtractor:
        def find_wechat_processes(self):
            return [1111, 2222]

        def selected_account(self):
            return ""

        def scan_memory_for_keys(self, pid, stop_event=None):
            scanned.append(pid)
            return {"message/message_0.db": "00" * 32}

    monkeypatch.setattr(main, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.core.platform.Platform.get",
        lambda: SimpleNamespace(key_extractor=FakeExtractor()),
    )

    main._try_auto_extract_keys()

    assert scanned == []


def test_startup_clears_cached_keys_when_they_cannot_bind_to_a_process(
    monkeypatch,
    tmp_path,
):
    cache = tmp_path / "all_keys.json"
    cache.write_text('{"message/message_0.db": "' + "00" * 32 + '"}', encoding="utf-8")
    events = []

    class FakeExtractor:
        def load_keys(self):
            return {"message/message_0.db": "00" * 32}

        def validate_cached_keys(self, keys):
            return keys

        def _has_message_key(self, keys):
            return bool(keys)

        def bind_process_for_cached_keys(self, pid):
            events.append(("bind", pid))
            return False

        def clear_keys(self):
            events.append(("clear",))

        def find_wechat_processes(self):
            return [3333]

        def selected_account(self):
            return "wxid_selected"

        def scan_memory_for_keys(self, pid, stop_event=None):
            events.append(("scan", pid))
            return {}

    monkeypatch.setattr(main, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.core.platform.Platform.get",
        lambda: SimpleNamespace(key_extractor=FakeExtractor()),
    )

    main._try_auto_extract_keys()

    assert events == [("bind", 3333), ("clear",), ("scan", 3333), ("clear",)]

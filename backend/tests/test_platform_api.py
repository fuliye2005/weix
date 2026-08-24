import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api import platform_api
from app.core import db_reader_macos


class SharedReader:
    def find_database_files(self):
        return ["/wx/db_storage/contact/contact.db"]

    def open_db(self, *_args, **_kwargs):
        raise AssertionError("contacts API must not reuse platform.db_reader")


class ContactReader:
    opened = []

    def find_database_files(self):
        return ["/wx/db_storage/contact/contact.db"]

    def open_db(self, path, key):
        self.opened.append((path, key))
        return True

    def get_contacts(self):
        return [{"wxid": "wxid_a", "nickname": "A"}]

    def get_chatrooms(self):
        return [{"room_id": "room@chatroom", "name": "测试群"}]


class FakeExtractor:
    def load_keys(self):
        return {"contact/contact.db": "00" * 32}


def test_accounts_api_marks_selected_bound_and_online_account(monkeypatch):
    class Extractor:
        bound_account = "wxid_second_2"
        bound_pid = 222

        def selected_account(self):
            return "wxid_second_2"

        def get_available_accounts(self):
            return [
                {"wxid": "wxid_first_1", "data_dir": ""},
                {"wxid": "wxid_second_2", "data_dir": ""},
            ]

    class Sender:
        async def is_wechat_running(self):
            return True

    platform = SimpleNamespace(
        is_windows=True,
        key_extractor=Extractor(),
        sender=Sender(),
    )
    monkeypatch.setattr(platform_api.Platform, "get", lambda: platform)

    result = asyncio.run(platform_api.list_accounts())

    first, second = result["accounts"]
    assert result["selected"] == "wxid_second_2"
    assert result["active"] == "wxid_second_2"
    assert first["online"] is False
    assert second["online"] is True
    assert second["base_wxid"] == "wxid_second"


def test_select_account_rejects_unknown_directory_without_saving(monkeypatch):
    class Extractor:
        def get_available_accounts(self):
            return [{"wxid": "wxid_known_1"}]

    platform = SimpleNamespace(is_windows=True, key_extractor=Extractor())
    saved = []
    monkeypatch.setattr(platform_api.Platform, "get", lambda: platform)
    monkeypatch.setattr(platform_api, "_save_selected_account", saved.append)

    result = asyncio.run(
        platform_api.select_account(platform_api.AccountSelectionRequest(wxid="wxid_missing_9"))
    )

    assert result["success"] is False
    assert saved == []


def test_contacts_api_uses_isolated_reader(monkeypatch):
    shared_reader = SharedReader()
    platform = SimpleNamespace(
        key_extractor=FakeExtractor(),
        db_reader=shared_reader,
        is_macos=True,
    )

    monkeypatch.setattr(platform_api.Platform, "get", lambda: platform)
    monkeypatch.setattr(db_reader_macos, "MacOSDBReader", ContactReader)

    result = asyncio.run(platform_api.list_contacts(type="all", search=""))

    assert result["ready"] is True
    assert result["total_contacts"] == 1
    assert result["total_chatrooms"] == 1
    assert ContactReader.opened == [
        ("/wx/db_storage/contact/contact.db", bytes.fromhex("00" * 32))
    ]


def test_uia_diagnose_api_delegates_without_sending(monkeypatch):
    class FakeSender:
        async def diagnose_uia(self):
            return {
                "uia_available": True,
                "bound_pid": 5678,
                "window": {"pid": 5678},
            }

    platform = SimpleNamespace(is_windows=True, sender=FakeSender())
    monkeypatch.setattr(platform_api.Platform, "get", lambda: platform)

    result = asyncio.run(platform_api.diagnose_uia())

    assert result["uia_available"] is True
    assert result["window"]["pid"] == 5678

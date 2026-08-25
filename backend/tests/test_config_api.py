import asyncio
from types import SimpleNamespace

import yaml

from app.api import config as config_api


def test_chat_config_exposes_uia_policy(monkeypatch):
    cfg = SimpleNamespace(
        auto_reply={"enabled": True},
        windows_sender={
            "send_mode": "auto",
            "background_post_message": True,
            "allow_foreground_activation": True,
            "background_attempts": 2,
            "foreground_attempts": 3,
        },
    )
    monkeypatch.setattr(config_api, "get_config", lambda: cfg)

    result = asyncio.run(config_api.get_chat_config())

    assert result["windows_sender"] == {
        "send_mode": "auto",
        "background_post_message": True,
        "allow_foreground_activation": True,
        "background_attempts": 2,
        "foreground_attempts": 3,
    }


def test_update_chat_config_saves_and_applies_uia_policy(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "auto_reply": {"enabled": True},
                "windows_sender": {"send_mode": "foreground_uia"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cfg = SimpleNamespace(
        auto_reply={"enabled": True},
        windows_sender={"send_mode": "foreground_uia"},
    )
    monkeypatch.setattr(config_api, "get_config", lambda: cfg)
    monkeypatch.setattr(config_api, "_get_config_path", lambda: str(config_path))
    refreshed = []
    monkeypatch.setattr(config_api, "_refresh_runtime_uia_policy", lambda: refreshed.append(True))

    result = asyncio.run(
        config_api.update_chat_config(
            {
                "enabled": False,
                "windows_sender": {
                    "send_mode": "auto",
                    "background_post_message": True,
                    "allow_foreground_activation": True,
                    "background_attempts": 3,
                    "foreground_attempts": 2,
                },
            }
        )
    )

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert result["success"] is True
    assert result["windows_sender"]["background_attempts"] == 3
    assert cfg.auto_reply["enabled"] is False
    assert cfg.windows_sender["send_mode"] == "auto"
    assert saved["windows_sender"]["foreground_attempts"] == 2
    assert refreshed == [True]

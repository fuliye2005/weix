import asyncio
from pathlib import Path
from types import SimpleNamespace

import yaml

from app.ai import embeddings
from app.ai import vector_store
from app.api import config as config_api


def test_embedding_settings_keep_local_default_for_old_config(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(ai={"provider": "deepseek"}),
    )
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    settings = embeddings.get_embedding_settings()

    assert settings["provider"] == "local"
    assert settings["model"] == embeddings.LOCAL_EMBEDDING_MODEL
    assert settings["base_url"] == ""
    assert settings["api_key"] == ""


def test_embedding_settings_resolve_cloud_provider_key(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(
            ai={
                "provider": "deepseek",
                "embedding": {
                    "provider": "dashscope",
                    "model": "text-embedding-v3",
                    "base_url": "",
                },
            }
        ),
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dash-key")

    settings = embeddings.get_embedding_settings()

    assert settings == {
        "provider": "dashscope",
        "model": "text-embedding-v3",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "dash-key",
    }


def test_embedding_settings_ignore_template_key(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(
            ai={
                "embedding": {
                    "provider": "dashscope",
                    "api_key": "sk-your-dashscope-key-here",
                }
            }
        ),
    )
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    settings = embeddings.get_embedding_settings()

    assert settings["provider"] == "dashscope"
    assert settings["api_key"] == ""


def test_vector_store_directory_isolated_by_embedding_model(monkeypatch, tmp_path):
    monkeypatch.setattr(
        vector_store,
        "get_config",
        lambda: SimpleNamespace(chroma_persist_dir=""),
    )
    monkeypatch.setattr(vector_store, "get_data_dir", lambda: tmp_path)

    monkeypatch.setattr(
        embeddings,
        "get_embedding_settings",
        lambda: {
            "provider": "local",
            "model": embeddings.LOCAL_EMBEDDING_MODEL,
        },
    )
    local_path = Path(vector_store._build_project_dir())

    monkeypatch.setattr(
        embeddings,
        "get_embedding_settings",
        lambda: {
            "provider": "dashscope",
            "model": "text-embedding-v3",
        },
    )
    cloud_path = Path(vector_store._build_project_dir())

    assert local_path == tmp_path / "chroma"
    assert cloud_path == tmp_path / "chroma_dashscope_text-embedding-v3_1024"
    assert cloud_path != local_path


def test_ai_config_preserves_masked_nested_embedding_key(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "ai": {
                    "provider": "deepseek",
                    "api_key": "chat-secret",
                    "embedding": {
                        "provider": "dashscope",
                        "model": "text-embedding-v3",
                        "api_key": "embedding-secret",
                    },
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cfg = SimpleNamespace(
        ai={
            "provider": "deepseek",
            "api_key": "chat-secret",
            "embedding": {
                "provider": "dashscope",
                "model": "text-embedding-v3",
                "api_key": "embedding-secret",
            },
        }
    )
    monkeypatch.setattr(config_api, "get_config", lambda: cfg)
    monkeypatch.setattr(config_api, "_get_config_path", lambda: str(config_path))
    monkeypatch.setattr(config_api, "_refresh_embedding_runtime", lambda: None)

    result = asyncio.run(
        config_api.update_ai_config(
            {
                "embedding": {
                    "provider": "dashscope",
                    "model": "text-embedding-v3",
                    "api_key": "***cret",
                },
                "embedding_api_key_configured": True,
            }
        )
    )

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert result["embedding_reload_required"] is True
    assert cfg.ai["embedding"]["api_key"] == "embedding-secret"
    assert saved["ai"]["embedding"]["api_key"] == "embedding-secret"
    assert "embedding_api_key_configured" not in saved["ai"]


def test_get_ai_config_masks_nested_embedding_key(monkeypatch):
    cfg = SimpleNamespace(
        ai={
            "provider": "deepseek",
            "api_key": "chat-secret",
            "embedding": {
                "provider": "dashscope",
                "model": "text-embedding-v3",
                "api_key": "embedding-secret",
            },
        }
    )
    monkeypatch.setattr(config_api, "get_config", lambda: cfg)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    result = asyncio.run(config_api.get_ai_config())

    assert result["embedding"]["api_key"] != "embedding-secret"
    assert result["embedding"]["api_key"].endswith("cret")
    assert result["embedding_api_key_configured"] is True

import os
import sys
import asyncio
import time
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import verify_token
from app.deps import get_session
from app.models.database import AutoReplyRule, MessageTemplate, Workflow, ForwardRule, SystemConfig
from app.models.schemas import (
    RuleCreate, RuleOut, RuleUpdate,
    TemplateCreate, TemplateOut, TemplateUpdate,
    WorkflowCreate, WorkflowOut, WorkflowUpdate,
    ForwardRuleCreate, ForwardRuleOut,
    SystemConfigUpdate, SystemConfigItem,
)
from app.config import get_config
from app.utils.paths import get_config_dir

router = APIRouter(prefix="/api", tags=["config"], dependencies=[Depends(verify_token)])


AI_PROVIDER_CATALOG = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "description": "适合中文对话、长文本分析和风格蒸馏",
        "base_url": "https://api.deepseek.com",
        "protocol": "chat_completions",
        "models": [
            {"id": "deepseek-v4-pro", "context_window": "128K", "image_support": False},
            {"id": "deepseek-chat", "context_window": "64K", "image_support": False},
            {"id": "deepseek-reasoner", "context_window": "64K", "image_support": False},
        ],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "description": "OpenAI 官方兼容接口",
        "base_url": "https://api.openai.com/v1",
        "protocol": "chat_completions",
        "models": [
            {"id": "gpt-4o-mini", "context_window": "128K", "image_support": True},
            {"id": "gpt-4o", "context_window": "128K", "image_support": True},
        ],
    },
    {
        "id": "dashscope",
        "name": "阿里云百炼",
        "description": "通义千问兼容 OpenAI 接口",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "protocol": "chat_completions",
        "models": [
            {"id": "qwen-plus", "context_window": "131K", "image_support": False},
            {"id": "qwen-max", "context_window": "32K", "image_support": False},
            {"id": "qwen-vl-plus", "context_window": "32K", "image_support": True},
        ],
    },
    {
        "id": "siliconflow",
        "name": "硅基流动",
        "description": "聚合多家开源模型的兼容接口",
        "base_url": "https://api.siliconflow.cn/v1",
        "protocol": "chat_completions",
        "models": [
            {"id": "deepseek-ai/DeepSeek-V3", "context_window": "64K", "image_support": False},
            {"id": "Qwen/Qwen2.5-72B-Instruct", "context_window": "32K", "image_support": False},
        ],
    },
    {
        "id": "custom",
        "name": "自定义兼容接口",
        "description": "连接任意 OpenAI Chat Completions 兼容服务",
        "base_url": "http://localhost:11434/v1",
        "protocol": "chat_completions",
        "models": [],
    },
]


class AIConnectionTestRequest(BaseModel):
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    protocol: str = "chat_completions"


class RawConfigUpdateRequest(BaseModel):
    content: str = Field(min_length=1)


_UIA_POLICY_DEFAULTS = {
    "send_mode": "auto",
    "background_post_message": True,
    "allow_foreground_activation": True,
    "background_attempts": 1,
    "foreground_attempts": 1,
}


def _normalize_uia_policy(data: dict | None) -> dict:
    """Validate the small sender policy surface exposed in ChatConfig."""
    source = data if isinstance(data, dict) else {}
    mode = str(source.get("send_mode", _UIA_POLICY_DEFAULTS["send_mode"]) or "").strip().lower()
    if mode not in {"auto", "background_uia", "foreground_uia"}:
        mode = _UIA_POLICY_DEFAULTS["send_mode"]

    def attempts(key: str) -> int:
        try:
            return max(1, min(10, int(source.get(key, _UIA_POLICY_DEFAULTS[key]))))
        except (TypeError, ValueError):
            return int(_UIA_POLICY_DEFAULTS[key])

    return {
        "send_mode": mode,
        "background_post_message": bool(
            source.get("background_post_message", _UIA_POLICY_DEFAULTS["background_post_message"])
        ),
        "allow_foreground_activation": bool(
            source.get(
                "allow_foreground_activation",
                _UIA_POLICY_DEFAULTS["allow_foreground_activation"],
            )
        ),
        "background_attempts": attempts("background_attempts"),
        "foreground_attempts": attempts("foreground_attempts"),
    }


def _get_uia_policy() -> dict:
    cfg = get_config()
    return _normalize_uia_policy(cfg.windows_sender)


def _refresh_runtime_uia_policy() -> None:
    """Apply saved policy to an already-created sender without restarting."""
    try:
        from app.core.platform import Platform

        platform = Platform.get()
        sender = getattr(platform, "_sender", None)
        uia_sender = getattr(sender, "_uia_sender", None)
        refresh = getattr(uia_sender, "refresh_send_policy", None)
        if callable(refresh):
            refresh()
    except Exception:
        # A later sender construction will read the saved config normally.
        pass


def _mask_api_key(value: object) -> str:
    secret = str(value or "")
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:3]}{'*' * max(8, len(secret) - 7)}{secret[-4:]}"


def _mask_sensitive_config(value):
    """递归隐藏配置中的 API Key，避免嵌套 provider 泄露密钥。"""
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if "api_key" in str(key).lower() and isinstance(item, str):
                masked[key] = _mask_api_key(item)
            else:
                masked[key] = _mask_sensitive_config(item)
        return masked
    if isinstance(value, list):
        return [_mask_sensitive_config(item) for item in value]
    return value


def _merge_config_values(existing, incoming):
    """递归合并配置，并保留前端传回的掩码密钥。"""
    if not isinstance(existing, dict) or not isinstance(incoming, dict):
        return incoming

    merged = dict(existing)
    for key, value in incoming.items():
        if (
            "api_key" in str(key).lower()
            and isinstance(value, str)
            and value.startswith("***")
        ):
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config_values(merged[key], value)
        else:
            merged[key] = value
    return merged


def _refresh_embedding_runtime() -> None:
    """让新 Embedding 配置在保存后不再复用旧单例。"""
    try:
        from app.ai.embeddings import reset_embedding_managers
        from app.ai.vector_store import reset_vector_store

        reset_embedding_managers()
        reset_vector_store()
    except Exception:
        # 后续首次请求会重新初始化；刷新失败不应阻止保存配置。
        pass

    try:
        import app.main as main_module

        pipeline = getattr(main_module, "_pipeline", None)
        if pipeline is not None:
            # Agent 内部持有旧 RAG/Embedding 引用，下一条消息时重新创建。
            pipeline._ai_agent = None
    except Exception:
        pass


def _provider_catalog_item(provider_id: str) -> dict:
    return next(
        (item for item in AI_PROVIDER_CATALOG if item["id"] == provider_id),
        AI_PROVIDER_CATALOG[-1],
    )


def _configured_models(ai_cfg: dict) -> list[dict]:
    configured = ai_cfg.get("models")
    if isinstance(configured, list) and configured:
        return [
            {
                "id": str(item.get("id") or item.get("model") or "").strip(),
                "context_window": str(item.get("context_window") or "").strip(),
                "image_support": bool(item.get("image_support", False)),
                "enabled": bool(item.get("enabled", True)),
            }
            for item in configured
            if isinstance(item, dict) and str(item.get("id") or item.get("model") or "").strip()
        ]

    catalog = _provider_catalog_item(str(ai_cfg.get("provider") or "deepseek"))
    models = [dict(item, enabled=True) for item in catalog.get("models", [])]
    current_model = str(ai_cfg.get("model") or "").strip()
    if current_model and not any(item["id"] == current_model for item in models):
        models.insert(0, {"id": current_model, "context_window": "", "image_support": False, "enabled": True})
    return models


def _get_config_path() -> str:
    return os.getenv(
        "WEIX_CONFIG",
        str(get_config_dir() / "config.yaml"),
    )


def _reload_runtime_config() -> None:
    """Reload the singleton config after a raw YAML edit."""
    import app.config as config_module

    refreshed = config_module.Config.from_yaml(_get_config_path())
    current = get_config()
    current.__dict__.clear()
    current.__dict__.update(refreshed.__dict__)


@router.get("/config/raw")
async def get_raw_config():
    """Read the complete editable YAML configuration file."""
    config_path = Path(_get_config_path())
    try:
        return {
            "path": str(config_path),
            "content": config_path.read_text(encoding="utf-8"),
            "format": "yaml",
        }
    except OSError as exc:
        raise HTTPException(500, f"配置文件读取失败: {exc}")


@router.put("/config/raw")
async def update_raw_config(payload: RawConfigUpdateRequest):
    """Validate and write the complete YAML configuration file as-is."""
    try:
        parsed = yaml.safe_load(payload.content)
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"YAML 格式错误: {exc}")

    if not isinstance(parsed, dict):
        raise HTTPException(400, "配置文件必须是 YAML 对象，不能是列表或纯文本")

    config_path = Path(_get_config_path())
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    content = payload.content if payload.content.endswith("\n") else f"{payload.content}\n"
    temp_path = config_path.with_name(f".{config_path.name}.tmp")
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, config_path)
        _reload_runtime_config()
    except Exception as exc:
        try:
            if original:
                config_path.write_text(original, encoding="utf-8")
            elif config_path.exists():
                config_path.unlink()
        except OSError:
            pass
        raise HTTPException(500, f"配置文件保存失败: {exc}")
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass

    return {
        "success": True,
        "path": str(config_path),
        "message": "配置文件已保存并重新加载",
    }


@router.post("/config/raw/validate")
async def validate_raw_config(payload: RawConfigUpdateRequest):
    """Validate YAML without writing it to disk."""
    try:
        parsed = yaml.safe_load(payload.content)
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"YAML 格式错误: {exc}")
    if not isinstance(parsed, dict):
        raise HTTPException(400, "配置文件必须是 YAML 对象，不能是列表或纯文本")
    return {
        "success": True,
        "top_level_keys": list(parsed.keys()),
        "has_ai_section": isinstance(parsed.get("ai"), dict),
    }


# --- Chat Config ---
@router.get("/config/chat")
async def get_chat_config():
    payload = dict(get_config().auto_reply)
    payload["windows_sender"] = _get_uia_policy()
    return payload


@router.put("/config/chat")
async def update_chat_config(data: dict):
    cfg = get_config()
    data = dict(data or {})
    sender_data = data.pop("windows_sender", None)
    cfg.auto_reply.update(data)
    sender_policy = _normalize_uia_policy(sender_data) if sender_data is not None else None
    if sender_policy is not None:
        cfg.windows_sender.update(sender_policy)

    config_path = _get_config_path()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        raw["auto_reply"].update(data)
        if sender_policy is not None:
            raw.setdefault("windows_sender", {}).update(sender_policy)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        raise HTTPException(500, f"配置保存失败: {e}")

    if sender_policy is not None:
        _refresh_runtime_uia_policy()

    return {"success": True, "windows_sender": _get_uia_policy()}


# --- Business and working-hours config ---
@router.get("/config/business")
async def get_business_config():
    from app.ai.business_context import normalize_business_config

    return normalize_business_config(getattr(get_config(), "business", {}))


@router.put("/config/business")
async def update_business_config(data: dict):
    from app.ai.business_context import normalize_business_config

    normalized = normalize_business_config(data or {})
    cfg = get_config()
    cfg.business = normalized

    config_path = _get_config_path()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            raise ValueError("配置文件顶层必须是对象")
        raw["business"] = normalized
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        raise HTTPException(500, f"业务配置保存失败: {e}")

    return normalized


# --- AI Config ---
@router.get("/config/ai")
async def get_ai_config():
    cfg = get_config().ai
    masked = _mask_sensitive_config(dict(cfg))
    if not isinstance(masked, dict):
        masked = {}

    # 向旧配置补一个可编辑的 Embedding 区段；真正写入时仍由用户保存决定。
    if not isinstance(masked.get("embedding"), dict):
        from app.ai.embeddings import DEFAULT_EMBEDDING_CONFIG

        masked["embedding"] = dict(DEFAULT_EMBEDDING_CONFIG, api_key="")

    masked["api_key_configured"] = bool(str(cfg.get("api_key") or "").strip())
    masked["api_key_preview"] = _mask_api_key(cfg.get("api_key"))
    embedding_cfg = cfg.get("embedding") if isinstance(cfg, dict) else {}
    if not isinstance(embedding_cfg, dict):
        embedding_cfg = {}
    embedding_provider = str(embedding_cfg.get("provider") or "").lower()
    embedding_env_name = {
        "dashscope": "DASHSCOPE_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "openai": "OPENAI_API_KEY",
    }.get(embedding_provider, "")
    embedding_env_key = os.getenv(embedding_env_name, "") if embedding_env_name else ""
    embedding_chat_key = (
        str(cfg.get("api_key") or "").strip()
        if embedding_provider == str(cfg.get("provider") or "").lower()
        else ""
    )
    from app.ai.embeddings import is_usable_api_key

    embedding_key = next(
        (
            str(value).strip()
            for value in (embedding_cfg.get("api_key"), embedding_env_key, embedding_chat_key)
            if is_usable_api_key(value)
        ),
        "",
    )
    if isinstance(masked.get("embedding"), dict):
        masked["embedding"]["api_key"] = _mask_api_key(embedding_key)
    masked["embedding_api_key_configured"] = bool(
        embedding_key
    )
    masked["embedding_api_key_preview"] = _mask_api_key(
        embedding_key
    )
    masked["protocol"] = str(cfg.get("protocol") or "chat_completions")
    masked.setdefault("allow_network_search", True)
    masked.setdefault("search_unknown_terms", True)
    return masked


@router.get("/config/ai/providers")
async def get_ai_providers():
    """Return supported providers and their starter model catalogs."""
    return {"providers": AI_PROVIDER_CATALOG}


@router.put("/config/ai")
async def update_ai_config(data: dict):
    cfg = get_config()

    data = {
        key: value
        for key, value in data.items()
        if key
        not in {
            "api_key_configured",
            "api_key_preview",
            "embedding_api_key_configured",
            "embedding_api_key_preview",
            "models",
        }
    }

    # 递归合并，支持 ai.embedding 等嵌套配置，同时保留掩码密钥。
    existing_ai = dict(cfg.ai)
    merged_ai = _merge_config_values(existing_ai, data)
    cfg.ai.clear()
    cfg.ai.update(merged_ai)

    if "persona_replay" in data:
        try:
            from app.ai.agent import WeixAgent

            WeixAgent._replay_engine = None
        except Exception:
            pass

    # 持久化到 YAML（排除掩码值）
    config_path = _get_config_path()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        raw["ai"] = _merge_config_values(raw.get("ai") or {}, data)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        raise HTTPException(500, f"AI 配置保存失败: {e}")

    if "embedding" in data:
        _refresh_embedding_runtime()

    return {"success": True, "embedding_reload_required": "embedding" in data}


@router.post("/config/ai/test")
async def test_ai_connection(payload: AIConnectionTestRequest):
    """Test an unsaved provider configuration without exposing the API key."""
    cfg = get_config().ai
    api_key = payload.api_key.strip()
    if not api_key or api_key.startswith("***"):
        api_key = str(cfg.get("api_key") or "").strip()

    if not api_key:
        return {"success": False, "error": "请先填写 API Key"}
    if not payload.model.strip():
        return {"success": False, "error": "请先选择或填写模型名称"}
    if not payload.base_url.strip():
        return {"success": False, "error": "请先填写 Base URL"}
    if payload.protocol != "chat_completions":
        return {"success": False, "error": "当前连接测试暂只支持 Chat Completions 协议"}

    started = time.perf_counter()
    try:
        from app.ai.models import LLMConfig, create_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = create_llm(
            LLMConfig(
                provider=payload.provider,
                api_key=api_key,
                base_url=payload.base_url.strip(),
                model=payload.model.strip(),
                temperature=0,
                max_tokens=16,
            )
        )
        response = await asyncio.wait_for(
            asyncio.to_thread(
                llm.invoke,
                [
                    SystemMessage(content="你是连接测试助手，只回复 OK。"),
                    HumanMessage(content="连接测试"),
                ],
            ),
            timeout=30,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        content = response.content if hasattr(response, "content") else str(response)
        return {
            "success": True,
            "model": payload.model.strip(),
            "latency_ms": elapsed_ms,
            "preview": str(content).strip()[:80],
        }
    except asyncio.TimeoutError:
        return {"success": False, "error": "连接超时，请检查 Base URL、网络或代理设置"}
    except Exception as exc:
        text = str(exc).casefold()
        if any(marker in text for marker in ("401", "403", "api key", "apikey", "authentication", "unauthorized")):
            return {"success": False, "error": "API Key 鉴权失败，请检查 Key 是否有效"}
        if "404" in text or "not found" in text:
            return {"success": False, "error": "接口或模型不存在，请检查 Base URL 和模型名称"}
        if "429" in text or "rate limit" in text or "quota" in text:
            return {"success": False, "error": "账户额度或请求频率受限"}
        return {"success": False, "error": "连接失败，请检查供应商、Base URL 和模型配置"}


@router.post("/config/ai/test-current")
async def test_current_ai_connection():
    """Test the currently loaded custom AI configuration."""
    ai_cfg = get_config().ai
    return await test_ai_connection(
        AIConnectionTestRequest(
            provider=str(ai_cfg.get("provider") or "custom"),
            api_key=str(ai_cfg.get("api_key") or ""),
            base_url=str(ai_cfg.get("base_url") or ""),
            model=str(ai_cfg.get("model") or ""),
            protocol=str(ai_cfg.get("protocol") or "chat_completions"),
        )
    )


# --- Auto Reply Rules ---
@router.get("/rules", response_model=list[RuleOut])
async def list_rules(session=Depends(get_session)):
    result = await session.execute(select(AutoReplyRule).order_by(AutoReplyRule.priority.desc()))
    return result.scalars().all()


@router.post("/rules", response_model=RuleOut)
async def create_rule(rule: RuleCreate, session=Depends(get_session)):
    record = AutoReplyRule(**rule.model_dump())
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.put("/rules/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, data: RuleUpdate, session=Depends(get_session)):
    result = await session.execute(select(AutoReplyRule).where(AutoReplyRule.id == rule_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Rule not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(record, k, v)
    await session.commit()
    await session.refresh(record)
    return record


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, session=Depends(get_session)):
    result = await session.execute(select(AutoReplyRule).where(AutoReplyRule.id == rule_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Rule not found")
    await session.delete(record)
    await session.commit()
    return {"success": True}


# --- Templates ---
@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(session=Depends(get_session)):
    result = await session.execute(select(MessageTemplate))
    return result.scalars().all()


@router.post("/templates", response_model=TemplateOut)
async def create_template(tpl: TemplateCreate, session=Depends(get_session)):
    record = MessageTemplate(**tpl.model_dump())
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.put("/templates/{tpl_id}", response_model=TemplateOut)
async def update_template(tpl_id: int, data: TemplateUpdate, session=Depends(get_session)):
    result = await session.execute(select(MessageTemplate).where(MessageTemplate.id == tpl_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Template not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(record, k, v)
    await session.commit()
    await session.refresh(record)
    return record


@router.delete("/templates/{tpl_id}")
async def delete_template(tpl_id: int, session=Depends(get_session)):
    result = await session.execute(select(MessageTemplate).where(MessageTemplate.id == tpl_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Template not found")
    await session.delete(record)
    await session.commit()
    return {"success": True}


# --- Workflows ---
@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(session=Depends(get_session)):
    result = await session.execute(select(Workflow))
    return result.scalars().all()


@router.post("/workflows", response_model=WorkflowOut)
async def create_workflow(wf: WorkflowCreate, session=Depends(get_session)):
    record = Workflow(**wf.model_dump())
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.put("/workflows/{wf_id}", response_model=WorkflowOut)
async def update_workflow(wf_id: int, data: WorkflowUpdate, session=Depends(get_session)):
    result = await session.execute(select(Workflow).where(Workflow.id == wf_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Workflow not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(record, k, v)
    await session.commit()
    await session.refresh(record)
    return record


@router.delete("/workflows/{wf_id}")
async def delete_workflow(wf_id: int, session=Depends(get_session)):
    result = await session.execute(select(Workflow).where(Workflow.id == wf_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Workflow not found")
    await session.delete(record)
    await session.commit()
    return {"success": True}


# --- Forward Rules ---
@router.get("/forward-rules", response_model=list[ForwardRuleOut])
async def list_forward_rules(session=Depends(get_session)):
    result = await session.execute(select(ForwardRule))
    return result.scalars().all()


@router.post("/forward-rules", response_model=ForwardRuleOut)
async def create_forward_rule(rule: ForwardRuleCreate, session=Depends(get_session)):
    record = ForwardRule(**rule.model_dump())
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.put("/forward-rules/{rule_id}", response_model=ForwardRuleOut)
async def update_forward_rule(rule_id: int, data: ForwardRuleCreate, session=Depends(get_session)):
    result = await session.execute(select(ForwardRule).where(ForwardRule.id == rule_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Forward rule not found")
    for k, v in data.model_dump().items():
        setattr(record, k, v)
    await session.commit()
    await session.refresh(record)
    return record


@router.delete("/forward-rules/{rule_id}")
async def delete_forward_rule(rule_id: int, session=Depends(get_session)):
    result = await session.execute(select(ForwardRule).where(ForwardRule.id == rule_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "Forward rule not found")
    await session.delete(record)
    await session.commit()
    return {"success": True}


# --- System Config ---
@router.get("/system-config")
async def get_system_config(session=Depends(get_session)):
    """获取系统配置（默认值兜底）。"""
    result = await session.execute(select(SystemConfig))
    rows = result.scalars().all()
    db_map = {r.key: r.value for r in rows}

    defaults = {
        "system_name": "Weix 微信助手",
        "system_version": "0.1.0",
        "admin_email": "",
        "log_level": "INFO",
        "data_retention_days": "30",
        "page_size": "20",
        "alert_enabled": "true",
        "alert_room_id": "",
    }
    for k, v in defaults.items():
        db_map.setdefault(k, v)
    return [{"key": k, "value": db_map[k]} for k in defaults]


@router.put("/system-config")
async def update_system_config(data: SystemConfigUpdate, session=Depends(get_session)):
    """批量更新系统配置。"""
    for item in data.items:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == item.key)
        )
        record = result.scalar_one_or_none()
        if record:
            record.value = item.value
        else:
            session.add(SystemConfig(key=item.key, value=item.value))
    await session.commit()
    return {"success": True}


# --- Scheduler ---
@router.get("/scheduler/jobs")
async def list_jobs():
    from app.services.scheduler_service import get_scheduler
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
            "paused": job.next_run_time is None,
        })
    return jobs


@router.put("/scheduler/jobs/{job_id}")
async def update_job(job_id: str, data: dict):
    from app.services.scheduler_service import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    paused = data.get("paused")
    if paused is not None:
        if paused:
            job.pause()
        else:
            job.resume()
    return {"success": True, "job_id": job_id}


@router.post("/scheduler/jobs/{job_id}/trigger")
async def trigger_job(job_id: str):
    from app.services.scheduler_service import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    # Run the job immediately in background
    import asyncio
    asyncio.create_task(job.func(*job.args, **job.kwargs))
    return {"success": True, "job_id": job_id, "triggered": True}

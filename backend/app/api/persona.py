"""Persona API — 聊天风格分析与个性管理。"""

from __future__ import annotations

import logging
import json
import os

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from app.api.auth import verify_token
from app.config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/persona",
    tags=["persona"],
    dependencies=[Depends(verify_token)],
)


def _normalize_db_key_path(path: str) -> str:
    return path.replace("\\", "/").lower()


def _key_matches_db_path(key_path: str, full_path: str) -> bool:
    normalized_key = _normalize_db_key_path(key_path)
    normalized_full = _normalize_db_key_path(full_path)
    basename = os.path.basename(full_path)
    if "/" in normalized_key:
        return normalized_full.endswith(normalized_key)
    return os.path.normcase(key_path) == os.path.normcase(basename)


class PersonaUpdateRequest(BaseModel):
    """人工编辑 persona skill 的请求体。"""

    meta: dict = Field(default_factory=dict)
    self_memory: str = ""
    persona: str = ""
    private_prompt: str = ""
    group_prompt: str = ""
    mode: str = "contextual"
    simulation_mode: str = ""


class PersonaImportAnalyzeRequest(BaseModel):
    """选择外部导入中的一个人物进行风格分析。"""

    import_id: str
    speaker_id: str
    simulation_mode: str = "persona"
    force: bool = True


@router.get("")
async def get_persona():
    """获取当前缓存的 persona skill。"""
    try:
        from app.ai.style_distiller import StyleDistiller
        d = StyleDistiller(initialize_llm=False)
        if d.has_persona:
            return {
                "ready": True,
                "mode": d.mode,
                "meta": d.meta,
                "self_memory": d.self_memory_md,
                "persona": d.persona_md,
                "private_prompt": d.build_prompt(is_group=False),
                "group_prompt": d.build_prompt(is_group=True),
            }
        return {
            "ready": False,
            "mode": "contextual",
            "meta": {},
            "self_memory": "",
            "persona": "",
            "private_prompt": "",
            "group_prompt": "",
        }
    except Exception as exc:
        return {"ready": False, "error": str(exc)}


@router.post("/analyze")
async def analyze_persona(force: bool = False):
    """提取用户消息并分析语言风格。

    Args:
        force: 是否强制重新分析（忽略缓存）。
    """
    try:
        from app.core.platform import Platform
        from app.ai.style_distiller import StyleDistiller

        # 1. 打开微信 DB 提取用户消息
        platform = Platform.get()
        extractor = platform.key_extractor
        if hasattr(extractor, "load_keys"):
            keys = extractor.load_keys()
        else:
            keys = getattr(extractor, "_keys", {})

        if not keys:
            message = (
                "未获取数据库密钥，请以管理员身份启动服务并保持微信已登录"
                if platform.is_windows
                else "未获取数据库密钥，请以 sudo 启动服务"
            )
            return {"success": False, "error": message}

        platform_reader = getattr(platform, "db_reader", None)
        if platform_reader is not None:
            reader = platform_reader.__class__()
        else:
            from app.core.db_reader_macos import MacOSDBReader

            reader = MacOSDBReader()
        all_dbs = reader.find_database_files()

        msg_db_path = None
        msg_key = None
        for full_path in all_dbs:
            db_name = os.path.basename(full_path)
            for key_path, hex_key in keys.items():
                if _key_matches_db_path(key_path, full_path):
                    if "message_0.db" in key_path or "message_0.db" in db_name:
                        msg_db_path = full_path
                        msg_key = hex_key
                        break
            if msg_db_path:
                break

        if not msg_db_path:
            return {"success": False, "error": "未找到消息数据库"}

        reader.open_db(msg_db_path, bytes.fromhex(msg_key))

        # 2. 提取用户消息
        cfg = get_config()
        ai_cfg = cfg.ai if isinstance(cfg.ai, dict) else {}
        message_limit = int(ai_cfg.get("persona_message_limit", 0))
        since_days = int(ai_cfg.get("persona_since_days", 90))
        # limit=0 表示提取全部消息，传一个大值给 DB reader
        db_limit = message_limit if message_limit > 0 else 100000
        raw_messages = reader.get_my_messages(limit=db_limit, since_days=since_days)
        reader.close()

        if not raw_messages:
            return {"success": False, "error": "未提取到用户消息，请确认微信已登录"}

        contents = [m["content"] for m in raw_messages]

        # 3. LLM 分析
        d = StyleDistiller()
        persona = await d.analyze(contents, force=force)
        from app.ai.agent import WeixAgent
        WeixAgent._distiller = None
        logger.info("Persona skill updated; WeixAgent distiller cache reset")

        meta = persona.get("meta", {})
        sample_size = meta.get("sample_size") or len(contents)

        return {
            "success": True,
            "total_messages": len(raw_messages),
            "sample_size": sample_size,
            "mode": persona.get("mode", "contextual"),
            "simulation_mode": persona.get("simulation_mode", "persona"),
            "meta": meta,
            "self_memory": persona.get("self_memory_md", ""),
            "persona": persona.get("persona_md", ""),
            "private_prompt": persona.get("runtime_prompt_private", ""),
            "group_prompt": persona.get("runtime_prompt_group", ""),
        }

    except Exception as exc:
        logger.error(f"Persona analysis failed: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@router.post("/import")
async def import_persona_chat_files(files: list[UploadFile] = File(...)):
    """上传一份或多份聊天 JSON，并返回可选择的人物列表。"""
    try:
        from app.ai.chat_import import (
            MAX_IMPORT_MESSAGES,
            create_import,
            get_import_max_bytes,
            parse_chat_payload,
            summarize_participants,
        )

        if not files:
            return {"success": False, "error": "请至少选择一个聊天记录 JSON 文件"}

        messages: list[dict[str, str]] = []
        max_import_bytes = get_import_max_bytes()
        for index, upload in enumerate(files, start=1):
            if max_import_bytes is None:
                raw = await upload.read()
            else:
                raw = await upload.read(max_import_bytes + 1)
            if max_import_bytes is not None and len(raw) > max_import_bytes:
                max_import_mb = max_import_bytes / (1024 * 1024)
                return {
                    "success": False,
                    "error": (
                        f"文件过大：{upload.filename or f'文件{index}'}，"
                        f"单文件限制为 {max_import_mb:g}MB；"
                        "可在 config/config.yaml 的 ai.persona_import_max_mb 中调整，"
                        "设为 0 表示不限制文件大小"
                    ),
                }
            try:
                payload = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return {
                    "success": False,
                    "error": f"无法解析 JSON：{upload.filename or f'文件{index}'}",
                }

            filename = os.path.basename(upload.filename or f"chat_{index}.json")
            source_file = f"{index}:{filename}"
            parsed = parse_chat_payload(payload, source_file=source_file)
            messages.extend(parsed)
            if len(messages) > MAX_IMPORT_MESSAGES:
                return {
                    "success": False,
                    "error": f"聊天文本消息过多，最多支持 {MAX_IMPORT_MESSAGES} 条",
                }

        if not messages:
            return {
                "success": False,
                "error": "没有找到可分析的文本消息，请确认 JSON 中包含 type=1 的消息",
            }

        import_id = create_import(messages)
        return {
            "success": True,
            "import_id": import_id,
            "file_count": len(files),
            "total_messages": len(messages),
            "participants": summarize_participants(messages),
        }
    except Exception as exc:
        logger.error(f"Persona chat import failed: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@router.post("/import/analyze")
async def analyze_imported_persona(payload: PersonaImportAnalyzeRequest):
    """分析外部导入中指定稳定 ID 的人物消息。"""
    try:
        from app.ai.chat_import import load_import, summarize_participants
        from app.ai.persona_replay import build_replay_index, normalize_simulation_mode
        from app.ai.style_distiller import StyleDistiller

        messages = load_import(payload.import_id)
        speaker_id = payload.speaker_id.strip()
        simulation_mode = normalize_simulation_mode(payload.simulation_mode)
        selected_messages = [
            item
            for item in messages
            if str(item.get("speaker_id") or "").strip() == speaker_id
        ]
        if not selected_messages:
            return {"success": False, "error": "导入中没有找到所选人物的文本消息"}

        participant = next(
            (
                item
                for item in summarize_participants(messages)
                if item["id"] == speaker_id
            ),
            None,
        )
        if not participant:
            return {"success": False, "error": "所选人物不存在或导入已损坏"}

        contents = [item["content"] for item in selected_messages]
        replay_stats: dict = {}
        if simulation_mode in {"replay", "hybrid"}:
            ai_config = get_config().ai if isinstance(get_config().ai, dict) else {}
            replay_config = ai_config.get("persona_replay", {})
            replay_config = replay_config if isinstance(replay_config, dict) else {}
            replay_index = build_replay_index(
                messages,
                target_speaker_id=speaker_id,
                target_name=participant["name"],
                context_messages=int(replay_config.get("context_messages", 3) or 3),
            )
            replay_stats = replay_index.get("meta", {})

        if simulation_mode == "replay":
            distiller = StyleDistiller(initialize_llm=False)
            persona = distiller.build_replay_skill(
                persona_name=participant["name"],
                target_speaker_id=speaker_id,
                replay_stats=replay_stats,
                source="external_json",
            )
        else:
            distiller = StyleDistiller()
            persona = await distiller.analyze(
                contents,
                force=payload.force,
                mode=simulation_mode,
                persona_name=participant["name"],
                target_speaker_id=speaker_id,
                source="external_json",
            )
            persona = distiller.set_simulation_mode(
                simulation_mode,
                meta_updates={
                    "target_speaker_id": speaker_id,
                    "replay_sample_size": int(replay_stats.get("sample_count") or 0),
                    "replay_unique_reply_count": int(
                        replay_stats.get("unique_reply_count") or 0
                    ),
                    "replay_source_files": replay_stats.get("source_files", []),
                },
            )

        from app.ai.agent import WeixAgent

        WeixAgent._distiller = None
        WeixAgent._replay_engine = None
        logger.info(
            "External persona skill updated for %s; WeixAgent distiller cache reset",
            speaker_id,
        )

        meta = persona.get("meta", {})
        sample_size = meta.get("sample_size") or len(contents)
        return {
            "success": True,
            "speaker_id": speaker_id,
            "simulation_mode": persona.get("simulation_mode", simulation_mode),
            "total_messages": len(selected_messages),
            "import_total_messages": len(messages),
            "sample_size": sample_size,
            "persona_sample_size": sample_size,
            "replay_sample_size": int(replay_stats.get("sample_count") or persona.get("meta", {}).get("replay_sample_size", 0) or 0),
            "mode": persona.get("mode", "contextual"),
            "meta": meta,
            "self_memory": persona.get("self_memory_md", ""),
            "persona": persona.get("persona_md", ""),
            "private_prompt": persona.get("runtime_prompt_private", ""),
            "group_prompt": persona.get("runtime_prompt_group", ""),
            "target_speaker_id": meta.get("target_speaker_id", speaker_id),
        }
    except (FileNotFoundError, ValueError) as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"Imported persona analysis failed: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@router.delete("/import/{import_id}")
async def delete_persona_import(import_id: str):
    """删除外部聊天导入，避免原始聊天内容长期留在本地。"""
    try:
        from app.ai.chat_import import delete_import
        from app.ai.persona_replay import get_replay_index_path

        deleted = delete_import(import_id)
        replay_index_retained = get_replay_index_path().exists()
        return {
            "success": deleted,
            "replay_index_retained": replay_index_retained,
            "message": (
                "聊天记录导入已删除；已生成的历史复用索引仍保留"
                if deleted
                else "聊天记录导入不存在或已过期"
            ),
        }
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.error(f"Persona chat import deletion failed: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@router.put("")
async def update_persona(payload: PersonaUpdateRequest):
    """保存人工编辑后的 persona skill。"""
    try:
        from app.ai.style_distiller import StyleDistiller
        d = StyleDistiller(initialize_llm=False)
        save_kwargs = {
            "self_memory_md": payload.self_memory,
            "persona_md": payload.persona,
            "runtime_prompt_private": payload.private_prompt,
            "runtime_prompt_group": payload.group_prompt,
            "meta": payload.meta,
            "mode": payload.mode,
        }
        if payload.simulation_mode:
            save_kwargs["simulation_mode"] = payload.simulation_mode
        skill = d.save_edits(
            **save_kwargs,
        )

        from app.ai.agent import WeixAgent
        WeixAgent._distiller = None
        WeixAgent._replay_engine = None
        logger.info("Persona skill manually updated; WeixAgent distiller cache reset")

        return {
            "success": True,
            "ready": True,
            "mode": skill.get("mode", "contextual"),
            "simulation_mode": skill.get("simulation_mode", "persona"),
            "meta": skill.get("meta", {}),
            "self_memory": skill.get("self_memory_md", ""),
            "persona": skill.get("persona_md", ""),
            "private_prompt": skill.get("runtime_prompt_private", ""),
            "group_prompt": skill.get("runtime_prompt_group", ""),
        }
    except Exception as exc:
        logger.error(f"Persona update failed: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@router.delete("")
async def clear_persona():
    """清除缓存的 persona，恢复默认 AI 风格。"""
    try:
        from app.ai.style_distiller import StyleDistiller
        d = StyleDistiller(initialize_llm=False)
        d.clear_cache()
        from app.ai.persona_replay import PersonaReplayEngine

        replay_cleared = PersonaReplayEngine().clear()
        # 同时清除 agent 类缓存
        from app.ai.agent import WeixAgent
        WeixAgent._distiller = None
        WeixAgent._replay_engine = None
        return {
            "success": True,
            "replay_cleared": replay_cleared,
            "message": "Persona 和历史复用索引已清除，将恢复默认风格",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

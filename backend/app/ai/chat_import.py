"""Import and persist normalized external chat records for persona analysis."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import get_config
from app.utils.paths import get_data_dir

DEFAULT_MAX_IMPORT_MB = 256
MAX_IMPORT_BYTES = DEFAULT_MAX_IMPORT_MB * 1024 * 1024
MAX_IMPORT_MESSAGES = 100_000
_IMPORT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_RETRACTION_RE = re.compile(r"(?:撤回了一条消息|撤回消息|消息已撤回|已撤回)")


def get_import_max_bytes() -> int | None:
    """Return the configured per-file limit; zero disables the byte limit."""
    try:
        ai_config = get_config().ai
        configured_mb = int(ai_config.get("persona_import_max_mb", DEFAULT_MAX_IMPORT_MB))
    except (TypeError, ValueError, AttributeError):
        configured_mb = DEFAULT_MAX_IMPORT_MB

    if configured_mb <= 0:
        return None
    return configured_mb * 1024 * 1024


def parse_chat_payload(
    payload: Any,
    source_file: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize a chat export into stable speaker/content records.

    The WeChat export format uses ``senderUsername`` as the stable person ID
    and ``senderDisplayName`` as its display label. Other common export shapes
    remain supported as a fallback. Text in the export is always treated as
    data; it is never interpreted as an instruction.
    """
    records = _find_records(payload)
    conversation = payload.get("conversation") if isinstance(payload, dict) else {}
    conversation = conversation if isinstance(conversation, dict) else {}
    default_conversation_id = _extract_text(
        _first_value(conversation, ("username", "conversationUsername", "id"))
    )
    default_is_group = _coerce_bool(
        _first_value(conversation, ("isGroup", "is_group", "group"))
    )
    normalized: list[dict[str, Any]] = []

    for source_index, record in enumerate(records):
        if len(normalized) >= MAX_IMPORT_MESSAGES:
            break
        if not isinstance(record, dict) or not _is_text_record(record):
            continue

        speaker_id = _extract_text(
            _first_value(
                record,
                (
                    "senderUsername",
                    "speaker_id",
                    "sender_id",
                    "fromUsername",
                    "user_id",
                    "username",
                    "sender_name",
                    "speaker",
                    "author",
                    "sender",
                    "from",
                    "user",
                    "name",
                    "nickname",
                    "participant",
                    "member",
                ),
            )
        )
        speaker_name = _extract_text(
            _first_value(
                record,
                (
                    "senderDisplayName",
                    "sender_name",
                    "display_name",
                    "speaker_name",
                    "nickname",
                    "name",
                    "speaker",
                    "author",
                    "sender",
                    "from",
                    "user",
                    "participant",
                    "member",
                ),
            )
        )
        if not speaker_id:
            speaker_id = speaker_name
        if not speaker_name:
            speaker_name = speaker_id
        if not speaker_id or _is_group_identifier(speaker_id):
            continue

        content = _extract_text(
            _first_value(
                record,
                ("content", "text", "message", "body", "msg_content"),
            )
        )
        if not content or _RETRACTION_RE.search(content):
            continue

        normalized_record = {
            "speaker_id": speaker_id,
            "speaker_name": speaker_name,
            "content": content,
        }
        if _first_value(
            record,
            ("sortSeq", "sort_seq", "localId", "local_id", "serverId", "server_id", "id"),
        ) not in (None, "", []):
            normalized_record["source_index"] = source_index
        if source_file:
            normalized_record["source_file"] = source_file
        conversation_id = _extract_text(
            _first_value(record, ("conversationUsername", "conversation_id", "room_id"))
        )
        if not conversation_id:
            conversation_id = default_conversation_id
        if conversation_id:
            normalized_record["conversation_id"] = conversation_id
        is_group = _coerce_bool(
            _first_value(record, ("isGroup", "is_group", "group"))
        )
        if is_group is None:
            is_group = default_is_group
        if is_group is not None:
            normalized_record["is_group"] = is_group
        message_id = _extract_text(_first_value(record, ("id", "message_id", "msg_id")))
        if message_id:
            normalized_record["message_id"] = message_id
        timestamp = _first_value(
            record,
            ("sortSeq", "sort_seq", "createTime", "create_time", "timestamp", "time"),
        )
        if timestamp not in (None, "", []):
            normalized_record["timestamp"] = timestamp
        normalized.append(normalized_record)

    return normalized


def summarize_participants(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return stable-ID participants sorted by message count and display name."""
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    source_files: defaultdict[str, set[str]] = defaultdict(set)

    for item in messages:
        if not isinstance(item, dict):
            continue
        speaker_id = str(item.get("speaker_id") or item.get("speaker") or "").strip()
        if not speaker_id:
            continue
        speaker_name = str(
            item.get("speaker_name") or item.get("speaker") or speaker_id
        ).strip()
        counts[speaker_id] += 1
        names.setdefault(speaker_id, speaker_name or speaker_id)
        source_file = str(item.get("source_file") or "").strip()
        if source_file:
            source_files[speaker_id].add(source_file)

    return [
        {
            "id": speaker_id,
            "name": names[speaker_id],
            "message_count": count,
            "source_files": len(source_files[speaker_id]) or 1,
        }
        for speaker_id, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], names[item[0]].casefold(), item[0].casefold()),
        )
    ]


def create_import(messages: list[dict[str, Any]]) -> str:
    """Persist normalized messages and return a safe opaque import identifier."""
    import_id = uuid4().hex
    path = _import_path(import_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "messages": messages,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return import_id


def load_import(import_id: str) -> list[dict[str, Any]]:
    """Load a previously imported normalized chat dataset."""
    path = _import_path(import_id)
    if not path.exists():
        raise FileNotFoundError("聊天记录导入不存在或已过期")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("聊天记录导入文件无法读取") from exc
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        raise ValueError("聊天记录导入文件格式无效")

    normalized: list[dict[str, Any]] = []
    for item in messages[:MAX_IMPORT_MESSAGES]:
        if not isinstance(item, dict):
            continue
        speaker_id = str(item.get("speaker_id") or item.get("speaker") or "").strip()
        content = str(item.get("content") or "").strip()
        if not speaker_id or not content:
            continue
        speaker_name = str(
            item.get("speaker_name") or item.get("speaker") or speaker_id
        ).strip()
        record = {
            "speaker_id": speaker_id,
            "speaker_name": speaker_name or speaker_id,
            "content": content,
        }
        source_file = str(item.get("source_file") or "").strip()
        if source_file:
            record["source_file"] = source_file
        for key in (
            "source_index",
            "conversation_id",
            "is_group",
            "message_id",
            "timestamp",
        ):
            if key in item and item[key] not in (None, ""):
                record[key] = item[key]
        normalized.append(record)
    return normalized


def delete_import(import_id: str) -> bool:
    """Delete an imported dataset."""
    path = _import_path(import_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def _find_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in ("messages", "records", "items", "chat", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _find_records(value)
            if nested:
                return nested
    return [payload] if _looks_like_message(payload) else []


def _looks_like_message(record: dict[str, Any]) -> bool:
    has_speaker = any(
        key in record
        for key in (
            "senderUsername",
            "sender",
            "speaker",
            "author",
            "from",
            "user",
            "name",
        )
    )
    has_content = any(
        key in record for key in ("content", "text", "message", "body", "msg_content")
    )
    return has_speaker and has_content


def _is_text_record(record: dict[str, Any]) -> bool:
    """Filter WeChat system/media records while keeping generic text exports."""
    if record.get("isSystem") is True or record.get("is_system") is True:
        return False

    message_kind = str(
        record.get("msg_type") or record.get("message_type") or record.get("kind") or ""
    ).strip().casefold()
    if message_kind:
        if message_kind in {"system", "image", "voice", "video", "file", "sticker", "emoji"}:
            return False
        if message_kind in {"text", "plain", "txt", "1"}:
            return True

    if "type" in record and record.get("type") not in (None, ""):
        try:
            return int(record["type"]) == 1
        except (TypeError, ValueError):
            message_type = str(record["type"]).strip().casefold()
            return message_type in {"1", "text", "plain", "txt"}

    render_type = str(record.get("renderType") or "").strip().casefold()
    if render_type:
        return render_type in {"text", "plain", "txt"}
    return True


def _is_group_identifier(value: str) -> bool:
    return value.casefold().endswith("@chatroom")


def _first_value(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", []):
            return value
    return ""


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        for key in (
            "name",
            "display_name",
            "nickname",
            "username",
            "text",
            "content",
            "value",
        ):
            if key in value:
                text = _extract_text(value[key])
                if text:
                    return text
        return ""
    if isinstance(value, list):
        return "".join(_extract_text(item) for item in value).strip()
    return ""


def _coerce_bool(value: Any) -> bool | None:
    if value in (None, "", []):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes", "y", "group"}:
        return True
    if normalized in {"false", "0", "no", "n", "private"}:
        return False
    return None


def _import_path(import_id: str) -> Path:
    if not _IMPORT_ID_PATTERN.fullmatch(import_id or ""):
        raise ValueError("聊天记录导入标识无效")
    return get_data_dir() / "persona_imports" / f"{import_id}.json"

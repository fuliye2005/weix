"""Normalize chat identity fields shared by database readers and message APIs."""

import re


_GROUP_SENDER_PREFIX = re.compile(
    r"^\s*((?:wxid|gh)_[a-z0-9_-]+|\d+@openim)\s*:\s*(?:\r?\n|$)",
    re.IGNORECASE,
)


def is_chatroom_id(value: str) -> bool:
    """Return whether a value is a WeChat group conversation ID."""
    return str(value or "").strip().lower().endswith("@chatroom")


def parse_group_sender_prefix(content: str) -> str:
    """Extract the sender ID used by legacy group-message body prefixes."""
    match = _GROUP_SENDER_PREFIX.match(str(content or ""))
    return match.group(1) if match else ""


def strip_group_sender_prefix(content: str, sender: str = "") -> str:
    """Remove one known sender prefix without touching ordinary ``name: text``."""
    text = str(content or "")
    candidates = [str(sender or "").strip(), parse_group_sender_prefix(text)]
    for candidate in candidates:
        if not candidate:
            continue
        prefix = re.compile(
            rf"^\s*{re.escape(candidate)}\s*:\s*(?:\r?\n|$)",
            re.IGNORECASE,
        )
        cleaned, count = prefix.subn("", text, count=1)
        if count:
            return cleaned.strip()
    return text.strip()


def normalize_group_message(
    content: str,
    sender: str,
    room_id: str,
) -> tuple[str, str]:
    """Return clean body text and a sender ID that is never the room ID.

    A missing ``real_sender_id`` must not turn the group conversation itself
    into the apparent sender. When the sender cannot be recovered from the
    row or the legacy body prefix, the returned sender is empty.
    """
    room = str(room_id or "").strip()
    normalized_sender = str(sender or "").strip()
    prefixed_sender = parse_group_sender_prefix(content)

    if (
        prefixed_sender
        and (
            not normalized_sender
            or normalized_sender.casefold() == room.casefold()
            or is_chatroom_id(normalized_sender)
        )
    ):
        normalized_sender = prefixed_sender

    cleaned = strip_group_sender_prefix(content, normalized_sender or prefixed_sender)
    if (
        not normalized_sender
        or normalized_sender.casefold() == room.casefold()
        or is_chatroom_id(normalized_sender)
    ):
        normalized_sender = ""
    return cleaned, normalized_sender

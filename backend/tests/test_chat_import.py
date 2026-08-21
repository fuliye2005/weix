import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.ai.chat_import import (
    create_import,
    delete_import,
    load_import,
    parse_chat_payload,
    summarize_participants,
)


def test_parse_wechat_export_filters_non_text_and_group_sender():
    payload = {
        "schemaVersion": 1,
        "conversation": {"username": "room@chatroom", "isGroup": True},
        "messages": [
            {
                "type": 10000,
                "renderType": "system",
                "senderUsername": "room@chatroom",
                "senderDisplayName": "群聊",
                "content": "系统文本不应进入样本",
            },
            {
                "type": 1,
                "renderType": "text",
                "senderUsername": "wxid_alice",
                "senderDisplayName": "Alice",
                "content": "第一条",
            },
            {
                "type": 42,
                "renderType": "image",
                "senderUsername": "wxid_alice",
                "senderDisplayName": "Alice",
                "content": "图片说明不应进入样本",
            },
            {
                "type": 1,
                "renderType": "text",
                "senderUsername": "wxid_bob",
                "senderDisplayName": "",
                "content": "没有显示名时仍保留稳定 ID",
            },
        ],
    }

    messages = parse_chat_payload(payload, source_file="one.json")

    assert messages == [
        {
            "speaker_id": "wxid_alice",
            "speaker_name": "Alice",
            "content": "第一条",
            "source_file": "one.json",
        },
        {
            "speaker_id": "wxid_bob",
            "speaker_name": "wxid_bob",
            "content": "没有显示名时仍保留稳定 ID",
            "source_file": "one.json",
        },
    ]


def test_same_person_is_aggregated_across_multiple_files(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ai.chat_import.get_data_dir", lambda: tmp_path)
    first = {
        "messages": [
            {
                "type": 1,
                "senderUsername": "wxid_same",
                "senderDisplayName": "同一个人",
                "content": "来自第一组",
            },
            {
                "type": 1,
                "senderUsername": "wxid_other",
                "senderDisplayName": "另一个人",
                "content": "其他消息",
            },
        ]
    }
    second = {
        "messages": [
            {
                "type": 1,
                "senderUsername": "wxid_same",
                "senderDisplayName": "同一个人",
                "content": "来自第二组",
            }
        ]
    }

    messages = parse_chat_payload(first, source_file="one.json")
    messages.extend(parse_chat_payload(second, source_file="two.json"))
    participants = summarize_participants(messages)

    assert participants == [
        {
            "id": "wxid_same",
            "name": "同一个人",
            "message_count": 2,
            "source_files": 2,
        },
        {
            "id": "wxid_other",
            "name": "另一个人",
            "message_count": 1,
            "source_files": 1,
        },
    ]

    import_id = create_import(messages)
    try:
        loaded = load_import(import_id)
        selected = [item["content"] for item in loaded if item["speaker_id"] == "wxid_same"]
        assert selected == ["来自第一组", "来自第二组"]
    finally:
        assert delete_import(import_id) is True
        assert delete_import(import_id) is False

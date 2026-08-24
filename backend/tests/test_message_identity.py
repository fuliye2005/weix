from app.core.message_identity import normalize_group_message


def test_group_sender_never_falls_back_to_room_id():
    content, sender = normalize_group_message(
        "普通消息",
        "room@chatroom",
        "room@chatroom",
    )

    assert content == "普通消息"
    assert sender == ""


def test_group_prefix_becomes_sender_and_is_removed_from_body():
    content, sender = normalize_group_message(
        "wxid_member:\n你好",
        "room@chatroom",
        "room@chatroom",
    )

    assert sender == "wxid_member"
    assert content == "你好"


def test_ordinary_colon_text_is_not_stripped():
    content, sender = normalize_group_message(
        "时间: 10:00",
        "wxid_member",
        "room@chatroom",
    )

    assert sender == "wxid_member"
    assert content == "时间: 10:00"

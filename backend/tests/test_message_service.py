from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import Base, Message
from app.services.message_service import MessageService


@pytest.mark.asyncio
async def test_message_service_tracks_outbound_attempt_lifecycle(tmp_path):
    db_path = tmp_path / "messages.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        service = MessageService(session)
        inbound = await service.save_message(
            {
                "msg_id": "inbound:1",
                "content": "你好",
                "sender": "wxid_friend",
            }
        )
        attempt = await service.create_outbound_attempt(
            content="你好呀",
            target_id="wxid_friend",
            target_name="朋友",
            reply_to_msg_id=inbound.msg_id,
            reply_source="ai",
            send_method="foreground_uia",
        )

        assert inbound.direction == "inbound"
        assert inbound.status == "received"
        assert attempt.direction == "outbound"
        assert attempt.status == "generated"
        assert attempt.reply_to_msg_id == "inbound:1"
        assert len(attempt.content_hash) == 64

        updated = await service.update_outbound_attempt(
            attempt.attempt_id,
            status="sent",
            sent_at=datetime.now(),
            error_code="",
            error_message="",
        )

        assert updated is not None
        assert updated.status == "sent"
        assert updated.sent_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_message_service_user_filter_matches_inbound_sender_and_outbound_target(tmp_path):
    db_path = tmp_path / "message-filter.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        service = MessageService(session)
        await service.save_message(
            {
                "msg_id": "inbound:filter",
                "content": "收到",
                "sender": "wxid_friend",
            }
        )
        await service.create_outbound_attempt(
            content="回复",
            target_id="wxid_friend",
            target_name="朋友",
        )

        rows, total = await service.get_messages(user_id="wxid_friend", size=20)

    assert total == 2
    assert {row.direction for row in rows} == {"inbound", "outbound"}
    await engine.dispose()

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import messages as messages_api
from app.core.send_result import SendResult
from app.models.database import Base, Message
from app.models.schemas import SendMessageRequest


class FakeStructuredSender:
    _method = "uia"

    async def send_text_result(self, msg, receiver, **kwargs):
        result = SendResult.for_message(
            msg,
            kwargs.get("target_id") or receiver,
            "foreground_uia",
            kwargs.get("attempt_id", ""),
        )
        return result.sent("db_verify", db_verified=True, ui_verified=True)


@pytest.mark.asyncio
async def test_manual_send_api_persists_delivery_result(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    sender = FakeStructuredSender()
    monkeypatch.setattr(
        messages_api.Platform,
        "get",
        lambda: SimpleNamespace(sender=sender),
    )

    async with factory() as session:
        from app.services.message_service import MessageService

        response = await messages_api.send_message(
            SendMessageRequest(
                msg="手动测试",
                receiver="文件传输助手",
                target_id="wxid_filehelper",
            ),
            service=MessageService(session),
        )

    assert response["success"] is True
    assert response["status"] == "sent"
    assert response["attempt_id"] == response["result"]["attempt_id"]

    async with factory() as session:
        row = (
            await session.execute(
                select(Message).where(Message.attempt_id == response["attempt_id"])
            )
        ).scalar_one()

    assert row.direction == "outbound"
    assert row.status == "sent"
    assert row.target_id == "wxid_filehelper"
    assert row.error_stage == "db_verify"
    assert row.send_method == "foreground_uia"

    await engine.dispose()

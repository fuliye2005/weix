import asyncio
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


class FakePendingStructuredSender(FakeStructuredSender):
    def __init__(self):
        self.verify_calls = 0

    async def send_text_result(self, msg, receiver, **kwargs):
        result = SendResult.for_message(
            msg,
            kwargs.get("target_id") or receiver,
            "foreground_uia",
            kwargs.get("attempt_id", ""),
        )
        result.action_performed = True
        result.draft_cleared = True
        result.ui_verified = True
        return result.pending(
            "db_verify",
            error_code="db_not_confirmed",
            error_message="暂未确认",
            db_verify_since_ts=1,
            verification_target_id=kwargs.get("target_id"),
        )

    async def verify_pending_result(self, result, msg, target_id="", **_kwargs):
        self.verify_calls += 1
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


@pytest.mark.asyncio
async def test_manual_pending_send_is_verified_in_background_without_resend(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pending-api.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    sender = FakePendingStructuredSender()
    monkeypatch.setattr(
        messages_api.Platform,
        "get",
        lambda: SimpleNamespace(sender=sender),
    )
    monkeypatch.setattr(messages_api, "get_session_factory", lambda: factory)

    async with factory() as session:
        from app.services.message_service import MessageService

        response = await messages_api.send_message(
            SendMessageRequest(
                msg="手动待验证",
                receiver="文件传输助手",
                target_id="wxid_filehelper",
            ),
            service=MessageService(session),
        )

    await asyncio.sleep(0.05)
    async with factory() as session:
        row = (
            await session.execute(
                select(Message).where(Message.attempt_id == response["attempt_id"])
            )
        ).scalar_one()

    assert response["status"] == "pending_verify"
    assert response["verification_scheduled"] is True
    assert sender.verify_calls == 1
    assert row.status == "sent"
    await engine.dispose()

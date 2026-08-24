import logging
import uuid
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Message

logger = logging.getLogger(__name__)


class MessageService:
    """Core message processing orchestrator."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_message(self, msg: dict) -> Message:
        """Save an inbound or already-materialized message to the database."""
        result = await self.session.execute(
            select(Message).where(Message.msg_id == msg["msg_id"])
        )
        record = result.scalar_one_or_none()
        if record is not None:
            return record

        record = Message(
            msg_id=msg["msg_id"],
            msg_type=msg.get("msg_type", 1),
            content=msg.get("content", ""),
            sender_wxid=msg.get("sender", ""),
            sender_name=msg.get("sender_name", ""),
            room_id=msg.get("room_id", ""),
            room_name=msg.get("room_name", ""),
            is_group=msg.get("is_group", False),
            direction=msg.get("direction", "inbound"),
            status=msg.get("status", "received"),
            reply_to_msg_id=msg.get("reply_to_msg_id"),
            attempt_id=msg.get("attempt_id"),
            send_method=msg.get("send_method"),
            reply_source=msg.get("reply_source"),
            error_stage=msg.get("error_stage"),
            error_code=msg.get("error_code"),
            error_message=msg.get("error_message"),
            sent_at=msg.get("sent_at"),
            target_id=msg.get("target_id"),
            target_name=msg.get("target_name"),
            create_time=msg.get("create_time", datetime.now()),
        )
        self.session.add(record)
        await self.session.commit()
        return record

    async def create_outbound_attempt(
        self,
        *,
        content: str,
        target_id: str,
        target_name: str = "",
        is_group: bool = False,
        reply_to_msg_id: str = "",
        reply_source: str = "manual",
        send_method: str = "",
        status: str = "generated",
        attempt_id: str | None = None,
    ) -> Message:
        """Create the durable record used by one outbound send attempt."""
        attempt_id = attempt_id or uuid.uuid4().hex
        record = Message(
            msg_id=f"outbound:{attempt_id}",
            msg_type=1,
            content=content,
            sender_wxid="",
            sender_name="",
            room_id=target_id if is_group else "",
            room_name=target_name if is_group else "",
            is_group=is_group,
            direction="outbound",
            status=status,
            reply_to_msg_id=reply_to_msg_id or None,
            attempt_id=attempt_id,
            send_method=send_method or None,
            reply_source=reply_source or "manual",
            target_id=target_id,
            target_name=target_name,
            create_time=datetime.now(),
        )
        self.session.add(record)
        await self.session.commit()
        return record

    async def update_outbound_attempt(self, attempt_id: str, **changes) -> Message | None:
        """Update one outbound attempt without creating duplicate log rows."""
        result = await self.session.execute(
            select(Message).where(Message.attempt_id == attempt_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            logger.warning("出站日志不存在，无法更新 | attempt_id=%s", attempt_id)
            return None

        allowed = {
            "status",
            "send_method",
            "error_code",
            "error_stage",
            "error_message",
            "sent_at",
            "target_id",
            "target_name",
            "reply_source",
        }
        for key, value in changes.items():
            if key in allowed:
                setattr(record, key, value)
        await self.session.commit()
        return record

    async def get_messages(
        self, room_id: str = "", user_id: str = "", start_date: str = "", end_date: str = "",
        page: int = 1, size: int = 20, direction: str = "", status: str = "",
    ) -> tuple[list[Message], int]:
        """Query messages with pagination and optional date range."""
        query = select(Message)
        count_q = select(func.count(Message.id))

        if room_id:
            query = query.where(Message.room_id == room_id)
            count_q = count_q.where(Message.room_id == room_id)
        if user_id:
            query = query.where(Message.sender_wxid == user_id)
            count_q = count_q.where(Message.sender_wxid == user_id)
        if direction:
            query = query.where(Message.direction == direction)
            count_q = count_q.where(Message.direction == direction)
        if status:
            query = query.where(Message.status == status)
            count_q = count_q.where(Message.status == status)
        if start_date:
            query = query.where(func.date(Message.create_time) >= start_date)
            count_q = count_q.where(func.date(Message.create_time) >= start_date)
        if end_date:
            query = query.where(func.date(Message.create_time) <= end_date)
            count_q = count_q.where(func.date(Message.create_time) <= end_date)

        query = query.order_by(Message.create_time.desc()).offset((page - 1) * size).limit(size)

        total = (await self.session.execute(count_q)).scalar() or 0
        result = await self.session.execute(query)
        items = result.scalars().all()
        return list(items), total

    async def get_today_message_count(self) -> int:
        """Get today's total message count."""
        today = datetime.now().strftime("%Y-%m-%d")
        result = await self.session.execute(
            select(func.count(Message.id)).where(
                func.date(Message.create_time) == today
            )
        )
        return result.scalar() or 0

    async def get_active_rooms(self) -> int:
        """Count active rooms today."""
        today = datetime.now().strftime("%Y-%m-%d")
        result = await self.session.execute(
            select(func.count(func.distinct(Message.room_id))).where(
                Message.room_id != "",
                func.date(Message.create_time) == today,
            )
        )
        return result.scalar() or 0

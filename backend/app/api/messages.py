import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.auth import verify_token
from app.core.message_identity import normalize_group_message
from app.core.platform import Platform
from app.core.send_result import SendResult
from app.models.database import Message
from app.models.schemas import MessageOut, MessageListResponse, SendMessageRequest
from app.deps import get_message_service, get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/messages", tags=["messages"], dependencies=[Depends(verify_token)])


def _consume_background_task(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("后台消息投递验证任务失败")


def _schedule_pending_delivery_verification(
    *,
    sender,
    result: SendResult,
    content: str,
    target_id: str,
    attempt_id: str,
) -> bool:
    verifier = getattr(sender, "verify_pending_result", None)
    if result.status != "pending_verify" or not callable(verifier):
        return False

    async def settle() -> None:
        final = result
        try:
            from app.config import get_config

            retries = max(
                1,
                int(get_config().windows_sender.get("pending_verify_retries", 2)),
            )
        except (AttributeError, TypeError, ValueError):
            retries = 2

        for index in range(retries):
            final = await verifier(final, content, target_id=target_id)
            if final.status != "pending_verify" or index + 1 >= retries:
                break
            await asyncio.sleep(1.0)

        async with get_session_factory()() as session:
            from app.services.message_service import MessageService

            service = MessageService(session)
            await service.update_outbound_attempt(
                attempt_id,
                status=final.status,
                send_method=final.method,
                error_stage=final.stage,
                error_code=final.error_code,
                error_message=final.error_message,
                sent_at=datetime.now() if final.status == "sent" else None,
            )

    task = asyncio.create_task(settle())
    task.add_done_callback(_consume_background_task)
    return True


def _serialize_message(message: Message) -> MessageOut:
    """Serialize logs while repairing legacy group rows on read."""
    content = message.content or ""
    sender_wxid = message.sender_wxid or ""
    sender_name = message.sender_name or ""

    if message.direction == "inbound" and message.is_group:
        content, sender_wxid = normalize_group_message(
            content,
            sender_wxid,
            message.room_id or "",
        )
        if sender_name in {message.room_name or "", message.room_id or ""}:
            sender_name = ""

    return MessageOut(
        msg_id=message.msg_id,
        msg_type=message.msg_type,
        content=content,
        sender_wxid=sender_wxid,
        sender_name=sender_name,
        room_id=message.room_id,
        room_name=message.room_name or "",
        is_group=message.is_group,
        direction=message.direction,
        status=message.status,
        reply_to_msg_id=message.reply_to_msg_id,
        attempt_id=message.attempt_id or "",
        content_hash=message.content_hash or "",
        send_method=message.send_method or "",
        reply_source=message.reply_source or "",
        error_stage=message.error_stage or "",
        error_code=message.error_code or "",
        error_message=message.error_message or "",
        sent_at=message.sent_at,
        target_id=message.target_id or "",
        target_name=message.target_name or "",
        create_time=message.create_time,
    )


@router.get("", response_model=MessageListResponse)
async def list_messages(
    room_id: str = Query(""),
    user_id: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    direction: str = Query(""),
    status: str = Query(""),
    service=Depends(get_message_service),
):
    items, total = await service.get_messages(
        room_id,
        user_id,
        start_date,
        end_date,
        page,
        size,
        direction,
        status,
    )
    return MessageListResponse(
        items=[_serialize_message(m) for m in items],
        total=total,
        page=page,
        size=size,
    )


@router.post("/send")
async def send_message(
    req: SendMessageRequest,
    service=Depends(get_message_service),
):
    platform = Platform.get()
    sender = platform.sender
    target_id = req.target_id or req.receiver
    target_name = req.target_name or req.receiver
    is_group = req.is_group or target_id.endswith("@chatroom")
    send_method = str(getattr(sender, "_method", "") or "")
    outbound = await service.create_outbound_attempt(
        content=req.msg,
        target_id=target_id,
        target_name=target_name,
        is_group=is_group,
        reply_source="manual",
        send_method=send_method,
        status="generated",
    )
    await service.update_outbound_attempt(outbound.attempt_id, status="sending")

    try:
        structured = getattr(sender, "send_text_result", None)
        if structured is not None:
            try:
                result = await structured(
                    req.msg,
                    req.receiver,
                    force_skip=False,
                    is_group=is_group,
                    target_id=target_id,
                    attempt_id=outbound.attempt_id,
                    wait_for_db_verify=False,
                )
            except TypeError as exc:
                if not any(
                    name in str(exc)
                    for name in ("attempt_id", "force_skip", "wait_for_db_verify")
                ):
                    raise
                result = await structured(
                    req.msg,
                    req.receiver,
                    is_group=is_group,
                    target_id=target_id,
                )
        else:
            success = await sender.send_text(
                req.msg,
                req.receiver,
                force_skip=False,
                is_group=is_group,
                target_id=target_id,
            )
            result = SendResult.for_message(
                req.msg,
                target_id,
                send_method or "legacy",
                outbound.attempt_id,
            )
            if success:
                result.action_performed = True
                result.sent("invoke", action_performed=True)
            else:
                result.fail("invoke", "send_failed", "发送器返回失败")
    except Exception as exc:
        result = SendResult.for_message(
            req.msg,
            target_id,
            send_method or "legacy",
            outbound.attempt_id,
        ).fail("invoke", "send_exception", str(exc))

    await service.update_outbound_attempt(
        outbound.attempt_id,
        status=result.status,
        send_method=result.method,
        error_stage=result.stage,
        error_code=result.error_code,
        error_message=result.error_message,
        sent_at=datetime.now() if result.status == "sent" else None,
    )
    verification_scheduled = _schedule_pending_delivery_verification(
        sender=sender,
        result=result,
        content=req.msg,
        target_id=target_id,
        attempt_id=outbound.attempt_id,
    )
    return {
        "success": result.success,
        "status": result.status,
        "msg": req.msg,
        "receiver": req.receiver,
        "attempt_id": outbound.attempt_id,
        "verification_scheduled": verification_scheduled,
        "result": result.as_dict(),
    }

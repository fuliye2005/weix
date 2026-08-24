from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.auth import verify_token
from app.core.platform import Platform
from app.core.send_result import SendResult
from app.models.database import Message
from app.models.schemas import MessageOut, MessageListResponse, SendMessageRequest
from app.deps import get_message_service

router = APIRouter(prefix="/api/messages", tags=["messages"], dependencies=[Depends(verify_token)])


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
        items=[
            MessageOut(
                msg_id=m.msg_id,
                msg_type=m.msg_type,
                content=m.content,
                sender_wxid=m.sender_wxid,
                sender_name=m.sender_name,
                room_id=m.room_id,
                room_name=m.room_name,
                is_group=m.is_group,
                direction=m.direction,
                status=m.status,
                reply_to_msg_id=m.reply_to_msg_id,
                attempt_id=m.attempt_id or "",
                content_hash=m.content_hash or "",
                send_method=m.send_method or "",
                reply_source=m.reply_source or "",
                error_stage=m.error_stage or "",
                error_code=m.error_code or "",
                error_message=m.error_message or "",
                sent_at=m.sent_at,
                target_id=m.target_id or "",
                target_name=m.target_name or "",
                create_time=m.create_time,
            )
            for m in items
        ],
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
                )
            except TypeError as exc:
                if not any(name in str(exc) for name in ("attempt_id", "force_skip")):
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
    return {
        "success": result.success,
        "status": result.status,
        "msg": req.msg,
        "receiver": req.receiver,
        "attempt_id": outbound.attempt_id,
        "result": result.as_dict(),
    }

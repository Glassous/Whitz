from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user, get_owned_conversation
from app.api.schemas import (
    ApprovalRequest,
    ChatTicketOut,
    ChatTicketRequest,
    ClarifyRequest,
    SendMessageRequest,
)
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.services import audit, chat_stream, chat_tickets, limits, membership
from app.services.hermes import HermesClient, HermesError

router = APIRouter(prefix="/api/conversations", tags=["chat"])


def _reset_hint(status: dict) -> str:
    windows = [status.get("weekly") or {}, status.get("five_hour") or {}]
    candidates = [
        (window["remaining"], window.get("reset_at"))
        for window in windows
        if window.get("remaining") is not None
    ]
    if not candidates:
        return ""
    reset_at = min(candidates, key=lambda item: item[0])[1]
    if not reset_at:
        return ""
    try:
        moment = datetime.fromisoformat(str(reset_at))
    except ValueError:
        return ""
    return f"，额度将于 {moment.astimezone(timezone.utc).strftime('%m-%d %H:%M UTC')} 刷新"


async def _client_for(user: User) -> HermesClient:
    return HermesClient(user.hermes_profile, user.hermes_api_key)


@router.post("/{conversation_id}/tickets", response_model=ChatTicketOut)
async def create_ticket(
    body: ChatTicketRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
) -> dict:
    return await chat_tickets.issue(user.id, conv.id, body.action, body.nonce, chat_tickets.client_ip(request))


@router.post("/{conversation_id}/messages")
async def send_message(
    body: SendMessageRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await chat_tickets.require(request, user.id, conv.id, "send")
    if conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前会话有进行中的任务，请先停止或等待完成")
    plan = membership.plan_for(membership.effective_tier(user))
    if not await limits.allow_chat(user.id, plan.chat_per_minute):
        await audit.record(
            "chat.rate_limited",
            actor=user,
            target_type="conversation",
            target_id=conv.id,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "发送过于频繁，请稍后再试")
    credits = await membership.status(db, user)
    if credits["remaining"] <= 0:
        await audit.record(
            "chat.credits_exhausted",
            actor=user,
            target_type="conversation",
            target_id=conv.id,
            outcome="failure",
            severity="warning",
            request=request,
            metadata={"tier": credits["tier"], "remaining": credits["remaining"]},
        )
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"积分已用尽{_reset_hint(credits)}，升级 Plus / Pro 可获得更多积分",
        )
    await audit.record(
        "chat.send",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata={"content_length": len(body.content), "file_count": len(body.file_ids)},
    )

    client = await _client_for(user)
    try:
        ready = await client.health()
    finally:
        await client.aclose()
    if not ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "agent_warming_up")

    sse_slot = await limits.acquire_sse(user.id)
    if sse_slot is None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "当前对话并发已满，请稍后再试")
    run_slot = await limits.acquire_run(user.id, plan.max_runs_per_user)
    if run_slot is None:
        await limits.release_sse(user.id, sse_slot)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "当前任务并发已满，请稍后再试")

    inner = chat_stream.stream_chat(
        conv.id,
        user.id,
        user.hermes_profile,
        user.hermes_api_key,
        body.content,
        file_ids=body.file_ids,
        max_seconds=plan.run_max_seconds,
    )
    return EventSourceResponse(
        limits.wrap_stream(inner, user.id, run_slot=run_slot, sse_slot=sse_slot), ping=10
    )


@router.get("/{conversation_id}/runs/{run_id}/events")
async def reconnect_events(
    run_id: str,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
):
    await chat_tickets.require(request, user.id, conv.id, "reconnect")
    sse_slot = await limits.acquire_sse(user.id)
    if sse_slot is None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "当前对话并发已满，请稍后再试")
    plan = membership.plan_for(membership.effective_tier(user))
    inner = chat_stream.stream_reconnect(
        conv.id,
        user.hermes_profile,
        user.hermes_api_key,
        run_id,
        max_seconds=plan.run_max_seconds,
    )
    return EventSourceResponse(
        limits.wrap_stream(inner, user.id, sse_slot=sse_slot), ping=10
    )


@router.post("/{conversation_id}/stop")
async def stop_run(
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await chat_tickets.require(request, user.id, conv.id, "stop")
    if not conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有进行中的任务")
    run_id = conv.active_run_id
    client = await _client_for(user)
    try:
        result = await client.stop_run(run_id)
    except HermesError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    finally:
        await client.aclose()
    row = await db.execute(
        select(Message).where(Message.conversation_id == conv.id, Message.hermes_run_id == run_id, Message.role == "assistant")
    )
    assistant = row.scalars().first()
    if assistant is not None and assistant.status in ("streaming", "waiting"):
        assistant.status = "cancelled"
    conv.active_run_id = None
    conv.active_run_status = None
    await db.commit()
    await audit.record(
        "chat.stop",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata={"run_id": run_id},
    )
    return result


@router.post("/{conversation_id}/approval")
async def approval(
    body: ApprovalRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
) -> dict:
    await chat_tickets.require(request, user.id, conv.id, "approval")
    if not conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有进行中的任务")
    client = await _client_for(user)
    try:
        result = await client.approve(conv.active_run_id, body.request_id, body.execution_generation, body.choice)
    except HermesError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    finally:
        await client.aclose()
    await audit.record(
        "chat.approval",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata={"choice": body.choice},
    )
    return result


@router.post("/{conversation_id}/clarify")
async def clarify(
    body: ClarifyRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
) -> dict:
    await chat_tickets.require(request, user.id, conv.id, "clarify")
    if not conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有进行中的任务")
    client = await _client_for(user)
    try:
        result = await client.clarify(conv.active_run_id, body.request_id, body.execution_generation, body.answer)
    except HermesError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    finally:
        await client.aclose()
    await audit.record("chat.clarify", actor=user, target_type="conversation", target_id=conv.id, request=request)
    return result

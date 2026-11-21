import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user, get_owned_conversation
from app.api.schemas import (
    ApprovalRequest,
    ChatTicketOut,
    ChatTicketRequest,
    ClarifyRequest,
    EditMessageRequest,
    RegenerateMessageRequest,
    SendMessageRequest,
)
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.services import audit, chat_stream, chat_tickets, limits, membership, realtime_bus
from app.services.agent_client import AgentClient, AgentError

router = APIRouter(prefix="/api/conversations", tags=["chat"])
events_router = APIRouter(prefix="/api/events", tags=["events"])


@events_router.get("/stream")
async def user_events_stream(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Lightweight per-user real-time sync SSE stream for multi-device/multi-tab state convergence."""

    async def _gen():
        yield chat_stream.sse("sync.connected", {"user_id": str(user.id)})
        async for ev_name, payload in realtime_bus.subscribe_user_events(user.id):
            if await request.is_disconnected():
                return
            yield chat_stream.sse(ev_name, payload)

    return EventSourceResponse(_gen(), ping=15)


def _reset_hint(status_info: dict) -> str:
    windows = [status_info.get("weekly") or {}, status_info.get("five_hour") or {}]
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


async def _client_for(user: User) -> AgentClient:
    return AgentClient(user.agent_namespace, user.agent_api_key)


async def _preflight_chat_turn(
    request: Request,
    conv: Conversation,
    user: User,
    db: AsyncSession,
    *,
    audit_action: str,
    audit_metadata: dict,
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
        audit_action,
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata=audit_metadata,
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

    return plan, sse_slot, run_slot


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
    plan, sse_slot, run_slot = await _preflight_chat_turn(
        request,
        conv,
        user,
        db,
        audit_action="chat.send",
        audit_metadata={
            "content_length": len(body.content),
            "file_count": len(body.file_ids),
            "skill_count": len(body.skill_names),
            "model_route": body.model_route,
        },
    )
    idemp = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
    inner = chat_stream.stream_chat(
        conv.id,
        user.id,
        user.agent_namespace,
        user.agent_api_key,
        body.content,
        file_ids=body.file_ids,
        skill_names=body.skill_names,
        model_route=body.model_route,
        max_seconds=plan.run_max_seconds,
        run_slot=run_slot,
        idempotency_key=idemp,
    )
    # run_slot is owned and released by detached RunSupervisor; SSE only owns sse_slot!
    return EventSourceResponse(
        limits.wrap_stream(inner, user.id, sse_slot=sse_slot), ping=10
    )


@router.post("/{conversation_id}/messages/{message_id}/regenerate")
async def regenerate_message(
    message_id: uuid.UUID,
    request: Request,
    body: RegenerateMessageRequest | None = Body(default=None),
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = list(
        (await db.execute(select(Message).where(Message.conversation_id == conv.id))).scalars().all()
    )
    ordered = chat_stream.sort_messages(rows)
    target_idx = next((idx for idx, m in enumerate(ordered) if m.id == message_id), None)
    if target_idx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "消息不存在")
    if ordered[target_idx].role != "assistant":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持重新生成助手回复")
    has_user_before = any(m.role == "user" for m in ordered[:target_idx])
    if not has_user_before:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "未找到对应的用户消息")

    route = body.model_route if body is not None else "auto"
    plan, sse_slot, run_slot = await _preflight_chat_turn(
        request,
        conv,
        user,
        db,
        audit_action="chat.regenerate",
        audit_metadata={"target_message_id": str(message_id), "model_route": route},
    )
    idemp = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
    inner = chat_stream.stream_regenerate(
        conv.id,
        user.id,
        user.agent_namespace,
        user.agent_api_key,
        message_id,
        model_route=route,
        max_seconds=plan.run_max_seconds,
        run_slot=run_slot,
        idempotency_key=idemp,
    )
    return EventSourceResponse(
        limits.wrap_stream(inner, user.id, sse_slot=sse_slot), ping=10
    )


@router.post("/{conversation_id}/messages/{message_id}/edit")
async def edit_and_resend_message(
    message_id: uuid.UUID,
    body: EditMessageRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(Message, message_id)
    if target is None or target.conversation_id != conv.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "消息不存在")
    if target.role != "user":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持编辑用户消息并重发")

    plan, sse_slot, run_slot = await _preflight_chat_turn(
        request,
        conv,
        user,
        db,
        audit_action="chat.edit",
        audit_metadata={
            "target_message_id": str(message_id),
            "content_length": len(body.content),
            "file_count": len(body.file_ids),
            "skill_count": len(body.skill_names),
            "model_route": body.model_route,
        },
    )
    idemp = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
    inner = chat_stream.stream_edit(
        conv.id,
        user.id,
        user.agent_namespace,
        user.agent_api_key,
        message_id,
        body.content,
        file_ids=body.file_ids,
        skill_names=body.skill_names,
        model_route=body.model_route,
        max_seconds=plan.run_max_seconds,
        run_slot=run_slot,
        idempotency_key=idemp,
    )
    return EventSourceResponse(
        limits.wrap_stream(inner, user.id, sse_slot=sse_slot), ping=10
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
    last_event_id = request.headers.get("last-event-id")
    inner = chat_stream.stream_reconnect(
        conv.id,
        user.agent_namespace,
        user.agent_api_key,
        run_id,
        last_event_id=last_event_id,
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
    result: dict = {"id": run_id, "run_id": run_id, "status": "cancelled"}
    if run_id != "pending":
        client = await _client_for(user)
        try:
            result = await client.cancel_run(run_id)
        except AgentError as exc:
            # Never brick a conversation when the agent run already expired (404)
            if exc.status_code != 404:
                raise HTTPException(exc.status_code, exc.detail)
        finally:
            await client.aclose()
    row = await db.execute(
        select(Message).where(
            Message.conversation_id == conv.id,
            Message.run_id == run_id,
            Message.role == "assistant",
        )
    )
    assistant = row.scalars().first()
    if assistant is not None and assistant.status in ("streaming", "waiting"):
        assistant.status = "cancelled"
    conv.active_run_id = None
    conv.active_run_status = None
    conv.pending_control = None
    await db.commit()
    await realtime_bus.publish_user_event(
        user.id,
        "conversation.run_updated",
        {
            "conversation_id": str(conv.id),
            "active_run_id": None,
            "active_run_status": None,
            "last_status": "cancelled",
            "pending_control": None,
        },
    )
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
    db: AsyncSession = Depends(get_db),
) -> dict:
    await chat_tickets.require(request, user.id, conv.id, "approval")
    if not conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有进行中的任务")
    run_id = conv.active_run_id
    client = await _client_for(user)
    try:
        result = await client.resume_run(
            run_id,
            kind="approval",
            request_id=body.request_id,
            execution_generation=body.execution_generation,
            choice=body.choice,
        )
    except AgentError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    finally:
        await client.aclose()
    conv.pending_control = None
    conv.active_run_status = "running"
    assistant = (
        await db.execute(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.run_id == run_id,
                Message.role == "assistant",
            )
        )
    ).scalars().first()
    if assistant is not None and assistant.status == "waiting":
        assistant.status = "streaming"
    await db.commit()
    await realtime_bus.publish_user_event(
        user.id,
        "control.resolved",
        {"conversation_id": str(conv.id), "run_id": run_id, "kind": "approval"},
    )
    await realtime_bus.publish_user_event(
        user.id,
        "conversation.run_updated",
        {
            "conversation_id": str(conv.id),
            "active_run_id": run_id,
            "active_run_status": "running",
            "pending_control": None,
        },
    )
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
    db: AsyncSession = Depends(get_db),
) -> dict:
    await chat_tickets.require(request, user.id, conv.id, "clarify")
    if not conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有进行中的任务")
    run_id = conv.active_run_id
    client = await _client_for(user)
    try:
        result = await client.resume_run(
            run_id,
            kind="clarify",
            request_id=body.request_id,
            execution_generation=body.execution_generation,
            answer=body.answer,
        )
    except AgentError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    finally:
        await client.aclose()
    conv.pending_control = None
    conv.active_run_status = "running"
    assistant = (
        await db.execute(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.run_id == run_id,
                Message.role == "assistant",
            )
        )
    ).scalars().first()
    if assistant is not None and assistant.status == "waiting":
        assistant.status = "streaming"
    await db.commit()
    await realtime_bus.publish_user_event(
        user.id,
        "control.resolved",
        {"conversation_id": str(conv.id), "run_id": run_id, "kind": "clarify"},
    )
    await realtime_bus.publish_user_event(
        user.id,
        "conversation.run_updated",
        {
            "conversation_id": str(conv.id),
            "active_run_id": run_id,
            "active_run_status": "running",
            "pending_control": None,
        },
    )
    await audit.record("chat.clarify", actor=user, target_type="conversation", target_id=conv.id, request=request)
    return result

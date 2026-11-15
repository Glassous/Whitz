from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user, get_owned_conversation
from app.api.schemas import ApprovalRequest, ClarifyRequest, SendMessageRequest
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.services import chat_stream
from app.services.hermes import HermesClient, HermesError

router = APIRouter(prefix="/api/conversations", tags=["chat"])


async def _client_for(user: User) -> HermesClient:
    return HermesClient(user.hermes_profile, user.hermes_api_key)


@router.post("/{conversation_id}/messages")
async def send_message(
    body: SendMessageRequest,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
):
    if conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前会话有进行中的任务，请先停止或等待完成")
    client = await _client_for(user)
    try:
        ready = await client.health()
    finally:
        await client.aclose()
    if not ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "agent_warming_up")
    return EventSourceResponse(
        chat_stream.stream_chat(conv.id, user.hermes_profile, user.hermes_api_key, body.content),
        ping=10,
    )


@router.get("/{conversation_id}/runs/{run_id}/events")
async def reconnect_events(
    run_id: str,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
):
    return EventSourceResponse(
        chat_stream.stream_reconnect(conv.id, user.hermes_profile, user.hermes_api_key, run_id),
        ping=10,
    )


@router.post("/{conversation_id}/stop")
async def stop_run(
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
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
    return result


@router.post("/{conversation_id}/approval")
async def approval(
    body: ApprovalRequest,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
) -> dict:
    if not conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有进行中的任务")
    client = await _client_for(user)
    try:
        return await client.approve(conv.active_run_id, body.request_id, body.execution_generation, body.choice)
    except HermesError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    finally:
        await client.aclose()


@router.post("/{conversation_id}/clarify")
async def clarify(
    body: ClarifyRequest,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
) -> dict:
    if not conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有进行中的任务")
    client = await _client_for(user)
    try:
        return await client.clarify(conv.active_run_id, body.request_id, body.execution_generation, body.answer)
    except HermesError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    finally:
        await client.aclose()
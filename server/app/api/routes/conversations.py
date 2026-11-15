import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user, get_owned_conversation
from app.api.schemas import ConversationCreate, ConversationDetail, ConversationOut, ConversationUpdate
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.services import titles
from app.services.hermes import HermesClient, HermesError

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Conversation]:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    conv = Conversation(user_id=user.id, title=body.title, hermes_session_id="")
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    client = HermesClient(user.hermes_profile, user.hermes_api_key)
    try:
        session = await client.create_session(body.title)
        conv.hermes_session_id = str(session.get("id") or session.get("session_id") or "")
        await db.commit()
        await db.refresh(conv)
    except HermesError:
        pass
    finally:
        await client.aclose()
    return conv


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conv: Conversation = Depends(get_owned_conversation), db: AsyncSession = Depends(get_db)
) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conv.id)
        .options(selectinload(Conversation.messages))
    )
    conv = result.scalar_one()
    role_order = {"user": 0, "assistant": 1, "tool": 2}
    conv.messages.sort(key=lambda m: (m.created_at, role_order.get(m.role, 3)))
    return conv


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    body: ConversationUpdate,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    conv.title = body.title
    await db.commit()
    await db.refresh(conv)
    if conv.hermes_session_id:
        client = HermesClient(user.hermes_profile, user.hermes_api_key)
        try:
            await client.patch_session(conv.hermes_session_id, body.title)
        except HermesError:
            pass
        finally:
            await client.aclose()
    return conv


@router.post("/{conversation_id}/title/generate")
async def generate_conversation_title(
    conv: Conversation = Depends(get_owned_conversation),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Message.content)
        .where(Message.conversation_id == conv.id, Message.role == "user")
        .order_by(Message.created_at)
    )
    messages = [text for text in result.scalars() if isinstance(text, str) and text.strip()]
    if not messages:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前对话还没有可用的用户消息")
    prompt = titles.build_user_messages_prompt(messages)
    return EventSourceResponse(titles.title_events(prompt), ping=10)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if conv.hermes_session_id:
        client = HermesClient(user.hermes_profile, user.hermes_api_key)
        try:
            await client.delete_session(conv.hermes_session_id)
        except HermesError:
            pass
        finally:
            await client.aclose()
    await db.delete(conv)
    await db.commit()
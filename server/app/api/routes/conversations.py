import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user, get_owned_conversation
from app.api.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationSearchHit,
    ConversationUpdate,
)
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.services import audit, titles
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


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_snippet(text: str, query: str, before_chars: int = 36, after_chars: int = 76) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return ""
    idx = collapsed.lower().find(query.lower())
    if idx < 0:
        return collapsed[: before_chars + after_chars] + ("…" if len(collapsed) > before_chars + after_chars else "")
    start = max(0, idx - before_chars)
    end = min(len(collapsed), idx + len(query) + after_chars)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(collapsed) else ""
    return f"{prefix}{collapsed[start:end]}{suffix}"


@router.get("/search", response_model=list[ConversationSearchHit])
async def search_conversations(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=30, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationSearchHit]:
    term = q.strip()
    if not term:
        return []
    pattern = f"%{_escape_like(term)}%"

    msg_rows = (
        await db.execute(
            select(Message, Conversation.title)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.user_id == user.id,
                Message.role.in_(("user", "assistant")),
                Message.content.ilike(pattern, escape="\\"),
            )
            .order_by(Message.created_at.desc())
            .limit(limit * 3)
        )
    ).all()

    hits: list[ConversationSearchHit] = []
    per_conv_counts: dict[uuid.UUID, int] = {}
    matched_conv_ids: set[uuid.UUID] = set()

    for msg, conv_title in msg_rows:
        cnt = per_conv_counts.get(msg.conversation_id, 0)
        if cnt >= 3:
            continue
        snippet = _build_snippet(msg.content, term)
        if not snippet:
            continue
        per_conv_counts[msg.conversation_id] = cnt + 1
        matched_conv_ids.add(msg.conversation_id)
        hits.append(
            ConversationSearchHit(
                conversation_id=msg.conversation_id,
                conversation_title=conv_title,
                message_id=msg.id,
                role=msg.role,
                snippet=snippet,
                match_in="message",
                created_at=msg.created_at,
            )
        )
        if len(hits) >= limit:
            break

    if len(hits) < limit:
        title_convs = (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.user_id == user.id,
                    Conversation.title.ilike(pattern, escape="\\"),
                )
                .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()

        for conv in title_convs:
            if conv.id in matched_conv_ids:
                continue
            hits.append(
                ConversationSearchHit(
                    conversation_id=conv.id,
                    conversation_title=conv.title,
                    message_id=None,
                    role=None,
                    snippet="",
                    match_in="title",
                    created_at=conv.last_message_at or conv.updated_at or conv.created_at,
                )
            )
            if len(hits) >= limit:
                break

    hits.sort(key=lambda h: h.created_at, reverse=True)
    return hits[:limit]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    request: Request,
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
    await audit.record(
        "conversation.create",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
    )
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
    request: Request,
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
    await audit.record(
        "conversation.rename",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata={"title": body.title},
    )
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
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    conv_id = conv.id
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
    await audit.record(
        "conversation.delete",
        actor=user,
        target_type="conversation",
        target_id=conv_id,
        request=request,
    )
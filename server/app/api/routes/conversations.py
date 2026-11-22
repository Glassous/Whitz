import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, select, update
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
from app.db.models import Conversation, ConversationFile, FileChunk, Message, ScheduledTask, User
from app.db.session import get_db
from app.services import audit, cross_chat_memory, realtime_bus, titles
from app.services.agent_client import AgentClient, AgentError

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


async def _scheduled_conversation_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(ScheduledTask.conversation_id).where(
            ScheduledTask.user_id == user_id,
            ScheduledTask.conversation_id.is_not(None),
        )
    )
    return {cid for cid in rows.scalars() if cid is not None}


def _apply_scheduled_flag(convs: list[Conversation], scheduled_ids: set[uuid.UUID]) -> None:
    for conv in convs:
        is_sched = conv.kind != "main" and (
            conv.id in scheduled_ids or (conv.title or "").startswith("[定时]")
        )
        setattr(conv, "is_scheduled", is_sched)


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Conversation]:
    await cross_chat_memory.ensure_main_conversation(db, user)
    main_first = case((Conversation.kind == "main", 0), else_=1)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(
            main_first.asc(),
            Conversation.is_pinned.desc(),
            Conversation.pinned_at.desc().nullslast(),
            Conversation.last_message_at.desc().nullslast(),
            Conversation.created_at.desc(),
        )
    )
    convs = list(result.scalars().all())
    scheduled_ids = await _scheduled_conversation_ids(db, user.id)
    _apply_scheduled_flag(convs, scheduled_ids)
    return convs


@router.get("/main", response_model=ConversationDetail)
async def get_main_conversation(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Conversation:
    main_conv = await cross_chat_memory.ensure_main_conversation(db, user)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == main_conv.id)
        .options(selectinload(Conversation.messages).selectinload(Message.reactions))
    )
    conv = result.scalar_one()
    role_order = {"user": 0, "assistant": 1, "tool": 2}
    conv.messages.sort(key=lambda m: (m.created_at, role_order.get(m.role, 3), str(m.id)))
    return conv


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
            select(Message, Conversation.title, Conversation.kind)
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
    assistant_label = (user.assistant_name or "").strip() or "Whitz"
    scheduled_ids = await _scheduled_conversation_ids(db, user.id)

    for msg, conv_title, conv_kind in msg_rows:
        cnt = per_conv_counts.get(msg.conversation_id, 0)
        if cnt >= 3:
            continue
        snippet = _build_snippet(msg.content, term)
        if not snippet:
            continue
        per_conv_counts[msg.conversation_id] = cnt + 1
        matched_conv_ids.add(msg.conversation_id)
        display_title = assistant_label if conv_kind == "main" else conv_title
        is_sched = conv_kind != "main" and (
            msg.conversation_id in scheduled_ids or (conv_title or "").startswith("[定时]")
        )
        hits.append(
            ConversationSearchHit(
                conversation_id=msg.conversation_id,
                conversation_kind="main" if conv_kind == "main" else "side",
                conversation_title=display_title,
                is_scheduled=is_sched,
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
            display_title = assistant_label if conv.kind == "main" else conv.title
            is_sched = conv.kind != "main" and (
                conv.id in scheduled_ids or (conv.title or "").startswith("[定时]")
            )
            hits.append(
                ConversationSearchHit(
                    conversation_id=conv.id,
                    conversation_kind="main" if conv.kind == "main" else "side",
                    conversation_title=display_title,
                    is_scheduled=is_sched,
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
    conv = Conversation(user_id=user.id, kind="side", title=body.title, thread_id=str(uuid.uuid4()))
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    await audit.record(
        "conversation.create",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
    )
    await realtime_bus.publish_user_event(
        user.id,
        "conversation.updated",
        {"action": "created", "conversation_id": str(conv.id), "title": conv.title, "kind": conv.kind},
    )
    return conv


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conv.id)
        .options(selectinload(Conversation.messages).selectinload(Message.reactions))
    )
    conv = result.scalar_one()
    role_order = {"user": 0, "assistant": 1, "tool": 2}
    conv.messages.sort(key=lambda m: (m.created_at, role_order.get(m.role, 3), str(m.id)))
    scheduled_ids = await _scheduled_conversation_ids(db, user.id)
    _apply_scheduled_flag([conv], scheduled_ids)
    return conv


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    body: ConversationUpdate,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    if conv.kind == "main":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "主聊天不支持置顶或重命名，请前往助手设置修改昵称")

    title_changed = False
    pin_changed = False

    if body.title is not None:
        cleaned = body.title.strip()
        if not cleaned:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "对话标题不能为空")
        if cleaned != conv.title:
            conv.title = cleaned
            title_changed = True

    if body.is_pinned is not None and body.is_pinned != conv.is_pinned:
        conv.is_pinned = body.is_pinned
        conv.pinned_at = datetime.now(timezone.utc) if body.is_pinned else None
        pin_changed = True

    if title_changed or pin_changed:
        await db.commit()
        await db.refresh(conv)
        await realtime_bus.publish_user_event(
            user.id,
            "conversation.updated",
            {
                "action": "updated",
                "conversation_id": str(conv.id),
                "title": conv.title,
                "is_pinned": conv.is_pinned,
                "pinned_at": conv.pinned_at.isoformat() if conv.pinned_at else None,
            },
        )

    if title_changed:
        await audit.record(
            "conversation.rename",
            actor=user,
            target_type="conversation",
            target_id=conv.id,
            request=request,
            metadata={"title": conv.title},
        )
    if pin_changed:
        await audit.record(
            "conversation.pin",
            actor=user,
            target_type="conversation",
            target_id=conv.id,
            request=request,
            metadata={"is_pinned": conv.is_pinned},
        )
    scheduled_ids = await _scheduled_conversation_ids(db, user.id)
    _apply_scheduled_flag([conv], scheduled_ids)
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
    background_tasks: BackgroundTasks,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if conv.kind == "main":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "主聊天不可删除")

    conv_id = conv.id
    if conv.thread_id:
        client = AgentClient(user.agent_namespace, user.agent_api_key)
        try:
            await client.delete_thread(conv.thread_id)
        except AgentError:
            pass
        finally:
            await client.aclose()

    # All uploaded & generated files remain globally shared in the Library after deleting a side chat.
    await db.execute(
        update(ConversationFile)
        .where(ConversationFile.conversation_id == conv_id)
        .values(conversation_id=None, is_global=True)
    )
    await db.execute(
        update(FileChunk)
        .where(FileChunk.conversation_id == conv_id)
        .values(conversation_id=None, is_global=True)
    )

    await db.delete(conv)
    await db.commit()
    await realtime_bus.publish_user_event(
        user.id,
        "conversation.updated",
        {"action": "deleted", "conversation_id": str(conv_id)},
    )
    await audit.record(
        "conversation.delete",
        actor=user,
        target_type="conversation",
        target_id=conv_id,
        request=request,
    )
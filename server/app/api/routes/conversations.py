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
    ConversationContextStateOut,
    ConversationCreate,
    ConversationDetail,
    ConversationEpisodeOut,
    ConversationOut,
    ConversationSearchHit,
    ConversationUpdate,
    WorkingStateUpdateRequest,
)
from app.db.models import (
    Conversation,
    ConversationEpisode,
    ConversationFile,
    FileChunk,
    MemoryEntry,
    Message,
    ScheduledTask,
    User,
)
from app.db.session import get_db
from app.services import audit, cross_chat_memory, realtime_bus, run_supervisor, titles
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
            bool(getattr(conv, "is_scheduled", False))
            or conv.id in scheduled_ids
            or (conv.title or "").startswith("[定时]")
        )
        setattr(conv, "is_scheduled", is_sched)


async def _load_conversation_with_messages(
    db: AsyncSession,
    conv_id: uuid.UUID,
    *,
    before_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> Conversation:
    conv = await db.get(Conversation, conv_id)
    assert conv is not None
    role_order = {"user": 0, "assistant": 1, "tool": 2}
    if limit is not None or before_id is not None:
        page_size = max(1, min(int(limit or 60), 200))
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .options(selectinload(Message.reactions))
        )
        if before_id is not None:
            anchor = await db.get(Message, before_id)
            if anchor is not None and anchor.conversation_id == conv_id:
                stmt = stmt.where(Message.created_at < anchor.created_at)
        rows = list(
            (await db.execute(stmt.order_by(Message.created_at.desc()).limit(page_size + 1)))
            .scalars()
            .all()
        )
        has_more = len(rows) > page_size
        page = rows[:page_size]
        page.sort(key=lambda m: (m.created_at, role_order.get(m.role, 3), str(m.id)))
        conv.messages = page
        setattr(conv, "has_more_messages", has_more)
        setattr(conv, "next_before_id", str(page[0].id) if (has_more and page) else None)
        return conv

    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conv_id)
        .options(selectinload(Conversation.messages).selectinload(Message.reactions))
    )
    loaded = result.scalar_one()
    loaded.messages.sort(key=lambda m: (m.created_at, role_order.get(m.role, 3), str(m.id)))
    setattr(loaded, "has_more_messages", False)
    setattr(loaded, "next_before_id", None)
    return loaded


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
    before_id: uuid.UUID | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    main_conv = await cross_chat_memory.ensure_main_conversation(db, user)
    return await _load_conversation_with_messages(db, main_conv.id, before_id=before_id, limit=limit)


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
    before_id: uuid.UUID | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    loaded = await _load_conversation_with_messages(db, conv.id, before_id=before_id, limit=limit)
    scheduled_ids = await _scheduled_conversation_ids(db, user.id)
    _apply_scheduled_flag([loaded], scheduled_ids)
    return loaded


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


@router.get("/{conversation_id}/context-state", response_model=ConversationContextStateOut)
async def get_conversation_context_state(
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationContextStateOut:
    """Return L1 structured working_state, L2 archived episodes timeline, and L0 pinned memory count."""
    from sqlalchemy import func

    ep_rows = list(
        (
            await db.execute(
                select(ConversationEpisode)
                .where(ConversationEpisode.conversation_id == conv.id)
                .order_by(ConversationEpisode.episode_index.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    pinned_count = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(MemoryEntry)
                .where(MemoryEntry.user_id == user.id, MemoryEntry.is_pinned.is_(True))
            )
        )
        or 0
    )
    return ConversationContextStateOut(
        conversation_id=str(conv.id),
        conversation_kind=conv.kind or "side",
        working_state=cross_chat_memory.normalize_working_state(conv.working_state) if conv.working_state else None,
        rolling_summary=conv.rolling_summary,
        working_state_updated_at=conv.working_state_updated_at or conv.summary_updated_at,
        episodes=[
            ConversationEpisodeOut(
                id=str(ep.id),
                conversation_id=str(ep.conversation_id),
                conversation_kind=ep.conversation_kind or "main",
                episode_index=int(ep.episode_index or 1),
                topic=ep.topic or "",
                summary=ep.summary or "",
                key_facts=list(ep.key_facts or []),
                entities=list(ep.entities or []),
                start_msg_id=str(ep.start_msg_id) if ep.start_msg_id else None,
                end_msg_id=str(ep.end_msg_id) if ep.end_msg_id else None,
                started_at=ep.started_at,
                ended_at=ep.ended_at,
                message_count=int(ep.message_count or 0),
                created_at=ep.created_at,
            )
            for ep in ep_rows
        ],
        pinned_memories_count=pinned_count,
    )


@router.patch("/{conversation_id}/working-state", response_model=ConversationContextStateOut)
async def update_conversation_working_state(
    body: WorkingStateUpdateRequest,
    request: Request,
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationContextStateOut:
    """Allow users to inspect and prune/edit L1 structured Working State for transparent long-horizon control."""
    normalized = cross_chat_memory.normalize_working_state(body.working_state)
    now_dt = datetime.now(timezone.utc)
    conv.working_state = normalized
    conv.working_state_updated_at = now_dt
    conv.rolling_summary = cross_chat_memory.format_working_state_prompt(normalized)
    conv.summary_updated_at = now_dt
    await db.commit()
    await db.refresh(conv)
    await audit.record(
        "conversation.working_state_update",
        actor=user,
        target_type="conversation",
        target_id=conv.id,
        request=request,
    )
    return await get_conversation_context_state(conv=conv, user=user, db=db)


@router.post("/{conversation_id}/archive-episode", response_model=ConversationContextStateOut)
async def manual_archive_conversation_episode(
    conv: Conversation = Depends(get_owned_conversation),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationContextStateOut:
    """Manually trigger L1+L2 archival of older unarchived turns into an immutable ConversationEpisode."""
    await cross_chat_memory.archive_conversation_episode_if_needed(db, conv, force=True)
    await db.refresh(conv)
    return await get_conversation_context_state(conv=conv, user=user, db=db)


@router.post("/{conversation_id}/title/generate")
async def generate_conversation_title(
    conv: Conversation = Depends(get_owned_conversation),
    db: AsyncSession = Depends(get_db),
):
    if conv.kind == "main":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "主聊天不支持自动生成标题")
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
    if conv.active_run_id and conv.active_run_id != "pending":
        await run_supervisor.cancel_local_supervisor(conv.active_run_id)
        client = AgentClient(user.agent_namespace, user.agent_api_key)
        try:
            await client.cancel_run(conv.active_run_id)
        except AgentError:
            pass
        finally:
            await client.aclose()
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
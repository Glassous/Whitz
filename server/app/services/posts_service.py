"""Private AI & User Posts service: quota calculation, web-grounded daily AI posting,
user posting with automatic memory ingestion, and realistic delayed AI engagement.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import (
    AiPostDailyRun,
    AiPostPendingInteraction,
    Conversation,
    MemoryCollection,
    MemoryEntry,
    Post,
    PostComment,
    User,
)
from app.db.session import SessionLocal
from app.services import membership, memory_service, realtime_bus, usage, web_search

logger = logging.getLogger("whitz.posts")

TIER_POST_QUOTAS: dict[str, dict[str, Any]] = {
    "free": {"max_daily": 2, "category_weight": 0.5},
    "plus": {"max_daily": 5, "category_weight": 1.0},
    "pro": {"max_daily": 8, "category_weight": 1.25},
}

VALID_POST_KINDS = frozenset({"opinion", "digest", "insight", "inspiration", "note"})
AI_POST_KINDS = ("opinion", "digest", "insight", "inspiration")

_DAILY_SCHEDULER_TASK: asyncio.Task[Any] | None = None
_INTERACTION_SCHEDULER_TASK: asyncio.Task[Any] | None = None
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class PostServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def compute_daily_post_count(tier: str | None, total_entries: int, active_collections: int) -> int:
    """Compute daily AI post count based on membership tier, memory count, and active category count.

    When memory count is 0 (or no active non-empty collection), returns 0.
    """
    entries = int(total_entries or 0)
    collections = int(active_collections or 0)
    if entries <= 0 or collections <= 0:
        return 0
    key = (tier or membership.FREE).strip().lower()
    cfg = TIER_POST_QUOTAS.get(key, TIER_POST_QUOTAS[membership.FREE])
    category_based = math.floor(collections * float(cfg["category_weight"]))
    volume_bonus = min(2, entries // 10)
    raw = max(1, category_based + volume_bonus)
    return min(int(cfg["max_daily"]), entries, raw)


def _user_local_now(tz_name: str | None, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo((tz_name or "Asia/Shanghai").strip() or "Asia/Shanghai")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Asia/Shanghai")
    return current.astimezone(tz)


def _sanitize_tags(raw: list[str] | None, *, limit: int = 6) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        cleaned = " ".join(str(item or "").strip().lstrip("#").split())[:24]
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def _sanitize_web_sources(raw: list[dict[str, Any]] | None, *, limit: int = 5) -> list[dict[str, str]]:
    if not raw:
        return []
    out: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()[:500]
        title = str(item.get("title") or "").strip()[:200]
        if not url or not url.startswith(("http://", "https://")) or url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(
            {
                "title": title or url,
                "url": url,
                "site_name": str(item.get("site_name") or "").strip()[:80],
                "published_at": str(item.get("published_at") or "").strip()[:40],
            }
        )
        if len(out) >= limit:
            break
    return out


def _normalize_post_kind(raw: str | None, *, default: str = "opinion") -> str:
    cleaned = (raw or "").strip().lower()
    if cleaned in VALID_POST_KINDS:
        return cleaned
    return default


def _extract_json_payload(raw_text: str) -> Any:
    text_val = (raw_text or "").strip()
    if not text_val:
        return None
    fence = _JSON_FENCE_RE.search(text_val)
    if fence:
        text_val = fence.group(1).strip()
    try:
        return json.loads(text_val)
    except (json.JSONDecodeError, ValueError):
        pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text_val.find(open_ch)
        end = text_val.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text_val[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def _llm_endpoint_and_model() -> tuple[str, str, str]:
    settings = get_settings()
    base = (settings.llm_fast_base_url or settings.llm_base_url or "").strip().rstrip("/")
    api_key = (settings.llm_fast_api_key or settings.llm_api_key or "").strip()
    model = (settings.llm_fast_model or settings.llm_model or "").strip()
    if not base or not api_key or not model:
        raise PostServiceError(503, "模型服务未配置")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    return url, api_key, model


def _estimate_tokens(messages: list[dict[str, str]], output_text: str) -> int:
    in_chars = sum(len(m.get("content") or "") for m in messages)
    return max(1, (in_chars + len(output_text or "")) // 3)


def _content_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [str(p.get("text") or "") for p in value if isinstance(p, dict)]
        return "".join(parts)
    return ""


async def _call_llm_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 2400,
) -> tuple[Any, int]:
    """Call OpenAI-compatible chat completions and return (parsed_json, total_tokens)."""
    url, api_key, model = _llm_endpoint_and_model()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=8.0), trust_env=False) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise PostServiceError(502, f"模型调用失败 ({resp.status_code})")
        data = resp.json()
    choices = data.get("choices") if isinstance(data, dict) else None
    msg = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
    raw_content = _content_value((msg or {}).get("content"))
    tokens = usage.tokens_from_usage(data.get("usage")) or _estimate_tokens(messages, raw_content)
    parsed = _extract_json_payload(raw_content)
    return parsed, tokens


async def _settle_tokens(db: AsyncSession, user_id: uuid.UUID, tokens: int) -> None:
    if tokens <= 0:
        return
    await usage.record_tokens(db, user_id, tokens)
    await membership.settle(db, user_id, tokens)


async def _gather_memory_snapshot(
    db: AsyncSession, user_id: uuid.UUID
) -> tuple[int, int, list[tuple[MemoryCollection, list[MemoryEntry]]]]:
    """Return (total_entries, active_collections, [(collection, entries), ...]) for enabled collections."""
    cols = list(
        (
            await db.execute(
                select(MemoryCollection)
                .where(MemoryCollection.user_id == user_id, MemoryCollection.enabled.is_(True))
                .order_by(MemoryCollection.sort_order.asc(), MemoryCollection.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not cols:
        return 0, 0, []

    col_by_id = {c.id: c for c in cols}
    col_by_slug = {c.slug: c for c in cols}

    entries = list(
        (
            await db.execute(
                select(MemoryEntry)
                .where(MemoryEntry.user_id == user_id)
                .order_by(
                    MemoryEntry.is_pinned.desc(),
                    MemoryEntry.priority.asc(),
                    MemoryEntry.updated_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )

    grouped: dict[uuid.UUID, list[MemoryEntry]] = {c.id: [] for c in cols}
    total = 0
    for entry in entries:
        target_col = None
        if entry.collection_id is not None:
            target_col = col_by_id.get(entry.collection_id)
        else:
            target_col = col_by_slug.get(memory_service.normalize_slug(entry.target))
        if target_col is not None and (entry.content or "").strip():
            grouped[target_col.id].append(entry)
            total += 1

    active_pairs = [(c, grouped[c.id]) for c in cols if grouped[c.id]]
    return total, len(active_pairs), active_pairs


async def get_user_post_quota_summary(db: AsyncSession, user: User, *, now: datetime | None = None) -> dict[str, Any]:
    tier = membership.effective_tier(user, now)
    plan = membership.plan_for(tier)
    cfg = TIER_POST_QUOTAS.get(tier, TIER_POST_QUOTAS[membership.FREE])
    total_entries, active_collections, _ = await _gather_memory_snapshot(db, user.id)
    estimated = (
        compute_daily_post_count(tier, total_entries, active_collections)
        if bool(user.memory_enabled)
        else 0
    )

    local_today = _user_local_now(user.timezone, now).date()
    today_run = (
        await db.execute(
            select(AiPostDailyRun).where(
                AiPostDailyRun.user_id == user.id,
                AiPostDailyRun.local_date == local_today,
            )
        )
    ).scalar_one_or_none()

    return {
        "ai_posts_enabled": bool(user.ai_posts_enabled),
        "ai_posts_consented_at": user.ai_posts_consented_at,
        "memory_enabled": bool(user.memory_enabled),
        "tier": tier,
        "tier_label": plan.label,
        "max_daily_cap": int(cfg["max_daily"]),
        "memory_entry_count": total_entries,
        "active_collection_count": active_collections,
        "estimated_daily_count": estimated,
        "today_generated_count": int(today_run.generated_count) if today_run else 0,
        "today_status": today_run.status if today_run else None,
        "local_date": local_today.isoformat(),
    }


def _serialize_comment(
    row: PostComment,
    *,
    by_id: dict[uuid.UUID, PostComment] | None = None,
) -> dict[str, Any]:
    parent = by_id.get(row.reply_to_id) if (by_id and row.reply_to_id) else None
    excerpt = None
    if parent is not None:
        raw = " ".join((parent.content or "").split())
        excerpt = raw[:60] + ("…" if len(raw) > 60 else "")
    return {
        "id": row.id,
        "post_id": row.post_id,
        "author_type": row.author_type,
        "content": row.content,
        "reply_to_id": row.reply_to_id,
        "reply_to_author_type": parent.author_type if parent is not None else None,
        "reply_to_excerpt": excerpt,
        "ai_liked": bool(row.ai_liked),
        "created_at": row.created_at,
    }


def _serialize_post(post: Post, comments: list[PostComment]) -> dict[str, Any]:
    by_id = {c.id: c for c in comments}
    return {
        "id": post.id,
        "author_type": post.author_type,
        "post_kind": post.post_kind or ("note" if post.author_type == "user" else "opinion"),
        "title": post.title or "",
        "content": post.content,
        "tags": list(post.tags or []),
        "web_sources": list(post.web_sources or []),
        "source_collection_id": post.source_collection_id,
        "source_collection_name": post.source_collection_name,
        "source_memory_ids": list(post.source_memory_ids or []),
        "memory_entry_id": post.memory_entry_id,
        "is_liked": bool(post.is_liked),
        "ai_liked": bool(post.ai_liked),
        "is_bookmarked": bool(post.is_bookmarked),
        "conversation_id": post.conversation_id,
        "comment_count": len(comments),
        "comments": [_serialize_comment(c, by_id=by_id) for c in comments],
        "created_at": post.created_at,
        "updated_at": post.updated_at,
    }


async def _load_comments_map(db: AsyncSession, post_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PostComment]]:
    if not post_ids:
        return {}
    rows = list(
        (
            await db.execute(
                select(PostComment)
                .where(PostComment.post_id.in_(post_ids))
                .order_by(PostComment.created_at.asc(), PostComment.id.asc())
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[PostComment]] = {pid: [] for pid in post_ids}
    for r in rows:
        grouped.setdefault(r.post_id, []).append(r)
    return grouped


async def list_posts(
    db: AsyncSession,
    user: User,
    *,
    author_type: str | None = None,
    bookmarked_only: bool = False,
    collection_id: uuid.UUID | None = None,
    post_kind: str | None = None,
    cursor: datetime | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    page_size = max(1, min(int(limit or 20), 50))
    stmt = select(Post).where(Post.user_id == user.id)
    if author_type in ("ai", "user"):
        stmt = stmt.where(Post.author_type == author_type)
    if bookmarked_only:
        stmt = stmt.where(Post.is_bookmarked.is_(True))
    if collection_id is not None:
        stmt = stmt.where(Post.source_collection_id == collection_id)
    if post_kind in VALID_POST_KINDS:
        stmt = stmt.where(Post.post_kind == post_kind)
    if cursor is not None:
        stmt = stmt.where(Post.created_at < cursor)

    stmt = stmt.order_by(desc(Post.created_at), desc(Post.id)).limit(page_size + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > page_size
    page_rows = rows[:page_size]
    next_cursor = page_rows[-1].created_at if has_more and page_rows else None

    comments_map = await _load_comments_map(db, [p.id for p in page_rows])
    quota = await get_user_post_quota_summary(db, user)
    return {
        "items": [_serialize_post(p, comments_map.get(p.id, [])) for p in page_rows],
        "next_cursor": next_cursor,
        "quota": quota,
    }


async def get_post_detail(db: AsyncSession, user: User, post_id: uuid.UUID) -> dict[str, Any]:
    post = await db.get(Post, post_id)
    if post is None or post.user_id != user.id:
        raise PostServiceError(404, "动态不存在")
    comments_map = await _load_comments_map(db, [post.id])
    return _serialize_post(post, comments_map.get(post.id, []))


def _pick_delay_seconds(min_sec: int, max_sec: int) -> int:
    lo = max(0, int(min_sec))
    hi = max(lo, int(max_sec))
    return random.randint(lo, hi)


async def create_user_post(
    db: AsyncSession,
    user: User,
    *,
    content: str,
    title: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    cleaned_content = (content or "").strip()
    if not cleaned_content:
        raise PostServiceError(400, "动态内容不能为空")
    cleaned_title = " ".join((title or "").strip().split())[:120]
    cleaned_tags = _sanitize_tags(tags)

    post = Post(
        user_id=user.id,
        author_type="user",
        post_kind="note",
        title=cleaned_title,
        content=cleaned_content,
        tags=cleaned_tags,
    )
    db.add(post)
    await db.flush()

    # Auto-ingest user post into long-term memory so future AI posts & chats can reference it.
    if bool(user.memory_enabled):
        try:
            mem_title = cleaned_title or f"用户动态 · {cleaned_content[:24]}"
            mem_tags = _sanitize_tags([*cleaned_tags, "私人动态"], limit=8)
            entry_dict = await memory_service.add_entry(
                db,
                user.id,
                "memory",
                cleaned_content[:2000],
                title=mem_title[:120],
                tags=mem_tags,
                source="post",
                priority=2,
            )
            if entry_dict and entry_dict.get("id"):
                post.memory_entry_id = uuid.UUID(str(entry_dict["id"]))
        except Exception as exc:
            logger.warning("Failed to ingest user post into memory user=%s: %s", user.id, exc)

    # Enqueue realistic delayed AI engagement (like + comment after a natural delay)
    if bool(user.ai_posts_enabled):
        settings = get_settings()
        delay_s = _pick_delay_seconds(
            settings.post_ai_post_delay_min_seconds,
            settings.post_ai_post_delay_max_seconds,
        )
        now = datetime.now(timezone.utc)
        db.add(
            AiPostPendingInteraction(
                user_id=user.id,
                post_id=post.id,
                kind="user_post_engage",
                status="pending",
                scheduled_for=now + timedelta(seconds=delay_s),
            )
        )

    await db.commit()
    await db.refresh(post)
    return _serialize_post(post, [])


async def delete_post(db: AsyncSession, user: User, post_id: uuid.UUID) -> None:
    post = await db.get(Post, post_id)
    if post is None or post.user_id != user.id:
        raise PostServiceError(404, "动态不存在")
    await db.delete(post)
    await db.commit()


async def toggle_like(db: AsyncSession, user: User, post_id: uuid.UUID) -> dict[str, Any]:
    post = await db.get(Post, post_id)
    if post is None or post.user_id != user.id:
        raise PostServiceError(404, "动态不存在")
    post.is_liked = not bool(post.is_liked)
    await db.commit()
    await db.refresh(post)
    comments_map = await _load_comments_map(db, [post.id])
    return _serialize_post(post, comments_map.get(post.id, []))


async def toggle_bookmark(db: AsyncSession, user: User, post_id: uuid.UUID) -> dict[str, Any]:
    post = await db.get(Post, post_id)
    if post is None or post.user_id != user.id:
        raise PostServiceError(404, "动态不存在")
    post.is_bookmarked = not bool(post.is_bookmarked)
    await db.commit()
    await db.refresh(post)
    comments_map = await _load_comments_map(db, [post.id])
    return _serialize_post(post, comments_map.get(post.id, []))


async def create_comment(
    db: AsyncSession,
    user: User,
    post_id: uuid.UUID,
    *,
    content: str,
    reply_to_id: uuid.UUID | None = None,
    trigger_ai_reply: bool = True,
) -> dict[str, Any]:
    post = await db.get(Post, post_id)
    if post is None or post.user_id != user.id:
        raise PostServiceError(404, "动态不存在")

    cleaned = (content or "").strip()
    if not cleaned:
        raise PostServiceError(400, "评论内容不能为空")

    parent: PostComment | None = None
    if reply_to_id is not None:
        parent = await db.get(PostComment, reply_to_id)
        if parent is None or parent.post_id != post.id or parent.user_id != user.id:
            raise PostServiceError(404, "被回复的评论不存在")

    comment = PostComment(
        post_id=post.id,
        user_id=user.id,
        author_type="user",
        content=cleaned[:2000],
        reply_to_id=parent.id if parent else None,
    )
    db.add(comment)
    await db.flush()

    ai_reply_scheduled = False
    if trigger_ai_reply and bool(user.ai_posts_enabled):
        settings = get_settings()
        delay_s = _pick_delay_seconds(
            settings.post_ai_comment_delay_min_seconds,
            settings.post_ai_comment_delay_max_seconds,
        )
        now = datetime.now(timezone.utc)
        db.add(
            AiPostPendingInteraction(
                user_id=user.id,
                post_id=post.id,
                trigger_comment_id=comment.id,
                kind="comment_reply",
                status="pending",
                scheduled_for=now + timedelta(seconds=delay_s),
            )
        )
        ai_reply_scheduled = True

    await db.commit()
    await db.refresh(comment)
    by_id = {parent.id: parent} if parent is not None else {}
    return {
        "comment": _serialize_comment(comment, by_id=by_id),
        "ai_reply_scheduled": ai_reply_scheduled,
    }


async def delete_comment(
    db: AsyncSession,
    user: User,
    post_id: uuid.UUID,
    comment_id: uuid.UUID,
) -> None:
    comment = await db.get(PostComment, comment_id)
    if comment is None or comment.post_id != post_id or comment.user_id != user.id:
        raise PostServiceError(404, "评论不存在")
    await db.delete(comment)
    await db.commit()


async def start_discussion_from_post(
    db: AsyncSession,
    user: User,
    post_id: uuid.UUID,
) -> dict[str, Any]:
    post = await db.get(Post, post_id)
    if post is None or post.user_id != user.id:
        raise PostServiceError(404, "动态不存在")

    if post.conversation_id is not None:
        existing_conv = await db.get(Conversation, post.conversation_id)
        if existing_conv is not None and existing_conv.user_id == user.id:
            return {
                "conversation_id": existing_conv.id,
                "prefill_prompt": _build_discuss_prefill(post),
            }

    raw_title = (post.title or "").strip() or " ".join((post.content or "").split())[:24]
    conv_title = f"聊聊动态：{raw_title}"[:60]
    conv = Conversation(
        user_id=user.id,
        kind="side",
        title=conv_title,
        thread_id="",
    )
    db.add(conv)
    await db.flush()
    post.conversation_id = conv.id
    await db.commit()
    await db.refresh(conv)

    await realtime_bus.publish_user_event(
        user.id,
        "conversation.updated",
        {"conversation_id": str(conv.id), "action": "created", "title": conv.title},
    )
    return {
        "conversation_id": conv.id,
        "prefill_prompt": _build_discuss_prefill(post),
    }


def _build_discuss_prefill(post: Post) -> str:
    header = f"关于你刚才发的这条动态「{post.title}」" if post.title else "关于这条动态"
    snippet = " ".join((post.content or "").split())[:260]
    return f"{header}：\n> {snippet}\n\n我想和你进一步聊聊这个话题："


# ---------------------------------------------------------------------------
# Three-stage web-grounded daily AI post generation
# ---------------------------------------------------------------------------


def _sample_memories_for_prompt(
    active_pairs: list[tuple[MemoryCollection, list[MemoryEntry]]],
    *,
    max_items: int = 24,
) -> tuple[str, dict[str, MemoryCollection], dict[str, list[str]]]:
    """Round-robin sample across active collections so every category is represented."""
    col_by_slug: dict[str, MemoryCollection] = {}
    sampled_ids_by_slug: dict[str, list[str]] = {}
    picked: list[tuple[MemoryCollection, MemoryEntry]] = []

    idx = 0
    while len(picked) < max_items:
        added_round = False
        for col, entries in active_pairs:
            if idx < len(entries):
                picked.append((col, entries[idx]))
                added_round = True
                if len(picked) >= max_items:
                    break
        if not added_round:
            break
        idx += 1

    lines: list[str] = []
    for col, entry in picked:
        col_by_slug[col.slug] = col
        sampled_ids_by_slug.setdefault(col.slug, []).append(str(entry.id))
        title_part = f"《{entry.title}》" if entry.title else ""
        tags_part = f" [{' '.join('#' + t for t in (entry.tags or [])[:4])}]" if entry.tags else ""
        snippet = " ".join((entry.content or "").split())[:240]
        lines.append(f"- [{col.slug} / {col.name}] {title_part}{tags_part}: {snippet}")

    return "\n".join(lines), col_by_slug, sampled_ids_by_slug


async def _gather_recent_feed_context(db: AsyncSession, user_id: uuid.UUID) -> tuple[str, str, str]:
    """Collect recent user posts, user comments/likes, and recent AI posts (for dedup)."""
    recent_user_posts = list(
        (
            await db.execute(
                select(Post)
                .where(Post.user_id == user_id, Post.author_type == "user")
                .order_by(desc(Post.created_at))
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    user_posts_text = "\n".join(
        f"- {p.title + '：' if p.title else ''}{' '.join((p.content or '').split())[:180]}"
        for p in recent_user_posts
    )

    recent_comments = list(
        (
            await db.execute(
                select(PostComment, Post.title, Post.content)
                .join(Post, Post.id == PostComment.post_id)
                .where(PostComment.user_id == user_id, PostComment.author_type == "user")
                .order_by(desc(PostComment.created_at))
                .limit(15)
            )
        ).all()
    )
    liked_ai_posts = list(
        (
            await db.execute(
                select(Post)
                .where(
                    Post.user_id == user_id,
                    Post.author_type == "ai",
                    (Post.is_liked.is_(True) | Post.is_bookmarked.is_(True)),
                )
                .order_by(desc(Post.created_at))
                .limit(8)
            )
        )
        .scalars()
        .all()
    )

    interaction_lines: list[str] = []
    for comment, p_title, p_content in recent_comments:
        post_ref = (p_title or " ".join((p_content or "").split())[:40]).strip()
        c_text = " ".join((comment.content or "").split())[:160]
        interaction_lines.append(f"- 用户在动态《{post_ref}》下评论：{c_text}")
    for p in liked_ai_posts:
        mark = "收藏" if p.is_bookmarked else "点赞"
        interaction_lines.append(
            f"- 用户{mark}了动态《{p.title or p.content[:30]}》(标签: {', '.join(p.tags or [])})"
        )
    interactions_text = "\n".join(interaction_lines)

    recent_ai_posts = list(
        (
            await db.execute(
                select(Post)
                .where(Post.user_id == user_id, Post.author_type == "ai")
                .order_by(desc(Post.created_at))
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    recent_ai_text = "\n".join(
        f"- {p.title or ' '.join((p.content or '').split())[:60]}"
        for p in recent_ai_posts
    )
    return user_posts_text, interactions_text, recent_ai_text


async def _generate_daily_posts_for_user(
    db: AsyncSession,
    user: User,
    daily_run: AiPostDailyRun,
    active_pairs: list[tuple[MemoryCollection, list[MemoryEntry]]],
    target_count: int,
) -> tuple[list[Post], int]:
    """Run 3-stage pipeline: Topic Planning -> Web Search -> Grounded Writing."""
    memories_text, col_by_slug, sampled_ids_by_slug = _sample_memories_for_prompt(active_pairs)
    user_posts_text, interactions_text, recent_ai_text = await _gather_recent_feed_context(db, user.id)
    today_str = _user_local_now(user.timezone).strftime("%Y-%m-%d")
    assistant_name = (user.assistant_name or "").strip() or "Whitz"
    lang = (user.preferred_language or "zh-CN").strip() or "zh-CN"

    # Stage 1: Plan topics & web search queries
    plan_system = (
        f"你是用户的专属 AI 助手「{assistant_name}」。现在需要为用户策划今日（{today_str}）的私人动态选题。"
        "动态内容严格仅该用户可见，目标是围绕用户可能感兴趣的话题，通过联网搜索最新资讯，发表有洞察的观点或整理实用信息。"
        "你必须输出严格合法的 JSON 数组，不要输出任何额外文字。"
    )
    plan_user = (
        f"请规划恰好 {target_count} 个互不重复的话题，尽量覆盖不同的记忆分类。\n"
        f"语言偏好：{lang}\n"
        f"【用户长期记忆（按分类）】\n{memories_text}\n\n"
        + (f"【用户近期自己发的动态】\n{user_posts_text}\n\n" if user_posts_text else "")
        + (f"【用户近期评论与点赞偏好】\n{interactions_text}\n\n" if interactions_text else "")
        + (f"【近期已发过的动态（请避免重复）】\n{recent_ai_text}\n\n" if recent_ai_text else "")
        + "请输出 JSON 数组，每项字段：\n"
        '{"collection_slug": "记忆分类slug", "post_kind": "opinion|digest|insight|inspiration", '
        '"topic": "话题简述", "angle": "切入角度或观点方向", "search_query": "用于联网搜索最新信息的精准关键词"}'
    )
    plan_parsed, plan_tokens = await _call_llm_json(
        [{"role": "system", "content": plan_system}, {"role": "user", "content": plan_user}],
        temperature=0.75,
        max_tokens=1200,
    )

    plans: list[dict[str, str]] = []
    raw_list = plan_parsed if isinstance(plan_parsed, list) else (
        plan_parsed.get("topics") if isinstance(plan_parsed, dict) and isinstance(plan_parsed.get("topics"), list) else []
    )
    default_slugs = [c.slug for c, _ in active_pairs]
    for i, item in enumerate(raw_list[:target_count]):
        if not isinstance(item, dict):
            continue
        slug = str(item.get("collection_slug") or "").strip()
        if slug not in col_by_slug:
            slug = default_slugs[i % len(default_slugs)]
        query = str(item.get("search_query") or item.get("topic") or "").strip()[:120]
        if not query:
            col_obj = col_by_slug[slug]
            query = f"{col_obj.name} 最新动态"
        plans.append(
            {
                "collection_slug": slug,
                "post_kind": _normalize_post_kind(item.get("post_kind"), default=AI_POST_KINDS[i % len(AI_POST_KINDS)]),
                "topic": str(item.get("topic") or query)[:120],
                "angle": str(item.get("angle") or "")[:200],
                "search_query": query,
            }
        )

    # Fallback plan if LLM returned fewer items than target_count
    while len(plans) < target_count:
        i = len(plans)
        col_obj, col_entries = active_pairs[i % len(active_pairs)]
        seed_text = (col_entries[0].title or col_entries[0].content[:40]).strip()
        plans.append(
            {
                "collection_slug": col_obj.slug,
                "post_kind": AI_POST_KINDS[i % len(AI_POST_KINDS)],
                "topic": seed_text,
                "angle": "结合用户记忆整理最新进展并分享观点",
                "search_query": f"{seed_text} 最新趋势 进展",
            }
        )

    # Stage 2: Concurrent web search for every planned topic
    sem = asyncio.Semaphore(4)

    async def _run_search(query: str) -> list[dict[str, str]]:
        async with sem:
            return await web_search.search_web(query, max_results=4, freshness="oneWeek")

    search_results_per_plan = await asyncio.gather(*[_run_search(p["search_query"]) for p in plans])

    # Stage 3: Grounded writing combining memory + web search + persona
    research_blocks: list[str] = []
    for idx, (p, results) in enumerate(zip(plans, search_results_per_plan), 1):
        col_obj = col_by_slug[p["collection_slug"]]
        src_lines = []
        for s in results:
            site = f" ({s['site_name']})" if s.get("site_name") else ""
            pub = f" [{s['published_at']}]" if s.get("published_at") else ""
            src_lines.append(f"  - {s['title']}{site}{pub}: {s['snippet'][:240]} | URL: {s['url']}")
        src_block = "\n".join(src_lines) if src_lines else "  - （本次未检索到额外网页，请基于最新已知背景与用户记忆展开深度思考）"
        research_blocks.append(
            f"选题 {idx} [分类: {col_obj.slug}/{col_obj.name}, 类型: {p['post_kind']}]:\n"
            f"  话题: {p['topic']}\n"
            f"  角度: {p['angle']}\n"
            f"  联网资料:\n{src_block}"
        )

    persona_note = f"\n助手人设要求：{(user.persona or '').strip()[:400]}" if (user.persona or "").strip() else ""
    write_system = (
        f"你是用户的专属 AI 助手「{assistant_name}」，正在用户的私人动态流里发帖（仅用户一人可见）。"
        f"{persona_note}\n"
        "写作风格：自然真诚、有观点有温度、信息密度高，像一位懂用户且紧跟前沿的聪明朋友分享思考或精选资讯，"
        "避免空洞说教和机械播报。支持适度使用 Markdown 列表或加粗提升可读性。每条正文建议 120~380 字。"
        "你必须输出严格合法的 JSON 数组，不要输出任何额外文字。"
    )
    write_user = (
        f"今天是 {today_str}，语言偏好：{lang}。\n"
        f"【用户长期记忆】\n{memories_text}\n\n"
        + (f"【用户近期动态】\n{user_posts_text}\n\n" if user_posts_text else "")
        + (f"【用户近期评论互动】\n{interactions_text}\n\n" if interactions_text else "")
        + f"【今日选题与联网资料】\n" + "\n\n".join(research_blocks) + "\n\n"
        f"请严格按顺序为以上 {len(plans)} 个选题各写 1 条动态，输出 JSON 数组，每项格式：\n"
        '{"title": "吸引人的简短标题(<=30字)", "content": "动态正文", "tags": ["标签1", "标签2"], '
        '"post_kind": "opinion|digest|insight|inspiration", "collection_slug": "对应分类slug"}'
    )
    write_parsed, write_tokens = await _call_llm_json(
        [{"role": "system", "content": write_system}, {"role": "user", "content": write_user}],
        temperature=0.8,
        max_tokens=min(4096, 650 * len(plans)),
    )

    total_tokens = int(plan_tokens) + int(write_tokens)
    raw_posts = write_parsed if isinstance(write_parsed, list) else (
        write_parsed.get("posts") if isinstance(write_parsed, dict) and isinstance(write_parsed.get("posts"), list) else []
    )

    created_posts: list[Post] = []
    for idx, item in enumerate(raw_posts[:target_count]):
        if not isinstance(item, dict):
            continue
        content_val = str(item.get("content") or "").strip()
        if not content_val:
            continue
        plan_ref = plans[idx] if idx < len(plans) else plans[-1]
        search_ref = search_results_per_plan[idx] if idx < len(search_results_per_plan) else []
        slug = str(item.get("collection_slug") or plan_ref["collection_slug"]).strip()
        col_obj = col_by_slug.get(slug) or col_by_slug.get(plan_ref["collection_slug"])

        post = Post(
            user_id=user.id,
            author_type="ai",
            post_kind=_normalize_post_kind(item.get("post_kind"), default=plan_ref["post_kind"]),
            title=" ".join(str(item.get("title") or plan_ref["topic"]).strip().split())[:120],
            content=content_val[:4000],
            tags=_sanitize_tags(item.get("tags") if isinstance(item.get("tags"), list) else []),
            web_sources=_sanitize_web_sources(search_ref, limit=4),
            source_collection_id=col_obj.id if col_obj else None,
            source_collection_name=col_obj.name if col_obj else None,
            source_memory_ids=list(sampled_ids_by_slug.get(col_obj.slug, []))[:5] if col_obj else [],
            daily_run_id=daily_run.id,
        )
        db.add(post)
        created_posts.append(post)

    await db.flush()
    return created_posts, total_tokens


async def _execute_daily_run_for_user(
    session_factory: Callable[[], Any],
    user_id: uuid.UUID,
    local_date: date,
) -> int:
    """Execute one claimed daily run for a single user. Returns number of generated posts."""
    async with session_factory() as db:
        user = await db.get(User, user_id)
        run_row = (
            await db.execute(
                select(AiPostDailyRun).where(
                    AiPostDailyRun.user_id == user_id,
                    AiPostDailyRun.local_date == local_date,
                )
            )
        ).scalar_one_or_none()
        if user is None or run_row is None:
            return 0

        now = datetime.now(timezone.utc)
        tier = membership.effective_tier(user, now)
        run_row.tier = tier

        if not user.is_active or not user.ai_posts_enabled:
            run_row.status = "skipped_disabled"
            run_row.finished_at = now
            await db.commit()
            return 0

        if not user.memory_enabled:
            run_row.status = "skipped_empty_memory"
            run_row.target_count = 0
            run_row.generated_count = 0
            run_row.finished_at = now
            await db.commit()
            return 0

        total_entries, active_collections, active_pairs = await _gather_memory_snapshot(db, user.id)
        target_count = compute_daily_post_count(tier, total_entries, active_collections)
        run_row.memory_entry_count = total_entries
        run_row.active_collection_count = active_collections
        run_row.target_count = target_count

        if target_count <= 0:
            run_row.status = "skipped_empty_memory"
            run_row.generated_count = 0
            run_row.finished_at = now
            await db.commit()
            return 0

        if await membership.credit_exhausted(db, user):
            run_row.status = "skipped_no_credits"
            run_row.generated_count = 0
            run_row.finished_at = now
            await db.commit()
            return 0

        try:
            created_posts, total_tokens = await _generate_daily_posts_for_user(
                db, user, run_row, active_pairs, target_count
            )
            run_row.generated_count = len(created_posts)
            run_row.tokens_used = total_tokens
            run_row.status = "completed"
            run_row.finished_at = datetime.now(timezone.utc)
            await db.commit()
            await _settle_tokens(db, user.id, total_tokens)

            if created_posts:
                await realtime_bus.publish_user_event(
                    user.id,
                    "post.created",
                    {
                        "count": len(created_posts),
                        "post_ids": [str(p.id) for p in created_posts],
                    },
                )
            return len(created_posts)
        except Exception as exc:
            logger.exception("Daily AI post generation failed user=%s date=%s", user.id, local_date)
            await db.rollback()
            run_row_reload = (
                await db.execute(
                    select(AiPostDailyRun).where(
                        AiPostDailyRun.user_id == user_id,
                        AiPostDailyRun.local_date == local_date,
                    )
                )
            ).scalar_one_or_none()
            if run_row_reload is not None:
                run_row_reload.status = "failed"
                run_row_reload.error = str(exc)[:500]
                run_row_reload.finished_at = datetime.now(timezone.utc)
                await db.commit()
            return 0


async def dispatch_daily_ai_posts(
    *,
    session_factory: Callable[[], Any] | None = None,
    now: datetime | None = None,
    batch_size: int | None = None,
    execute_inline: bool = False,
) -> int:
    """Atomically claim users due for today's AI auto-posts and dispatch generation."""
    factory = session_factory or SessionLocal
    settings = get_settings()
    limit_n = max(1, int(batch_size or settings.post_scheduler_batch_size))
    current = now or datetime.now(timezone.utc)
    trigger_hour = int(settings.post_scheduler_trigger_hour)

    claimed: list[tuple[uuid.UUID, date]] = []
    async with factory() as db:
        users = list(
            (
                await db.execute(
                    select(User)
                    .where(User.is_active.is_(True), User.ai_posts_enabled.is_(True))
                    .order_by(User.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        for user in users:
            if len(claimed) >= limit_n:
                break
            local_now = _user_local_now(user.timezone, current)
            if local_now.hour < trigger_hour:
                continue
            local_today = local_now.date()
            stmt = (
                pg_insert(AiPostDailyRun)
                .values(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    local_date=local_today,
                    tier=membership.effective_tier(user, current),
                    status="running",
                )
                .on_conflict_do_nothing(constraint="uq_ai_post_daily_runs_user_date")
            )
            res = await db.execute(stmt)
            if res.rowcount:
                claimed.append((user.id, local_today))
        if claimed:
            await db.commit()

    if execute_inline:
        for uid, ldate in claimed:
            await _execute_daily_run_for_user(factory, uid, ldate)
    else:
        for uid, ldate in claimed:
            _track_task(
                _execute_daily_run_for_user(factory, uid, ldate),
                name=f"ai-daily-posts-{uid}-{ldate}",
            )
    return len(claimed)


# ---------------------------------------------------------------------------
# Realistic delayed AI engagement (likes + comments + threaded replies)
# ---------------------------------------------------------------------------


async def _execute_pending_interaction(
    session_factory: Callable[[], Any],
    interaction_id: uuid.UUID,
) -> bool:
    async with session_factory() as db:
        job = await db.get(AiPostPendingInteraction, interaction_id)
        if job is None:
            return False

        user = await db.get(User, job.user_id)
        post = await db.get(Post, job.post_id)
        now = datetime.now(timezone.utc)

        if user is None or post is None or not user.is_active or not user.ai_posts_enabled:
            job.status = "skipped"
            job.executed_at = now
            await db.commit()
            return False

        if await membership.credit_exhausted(db, user):
            job.status = "skipped"
            job.error = "credit_exhausted"
            job.executed_at = now
            await db.commit()
            return False

        assistant_name = (user.assistant_name or "").strip() or "Whitz"
        persona_note = f"\n助手人设：{(user.persona or '').strip()[:300]}" if (user.persona or "").strip() else ""
        _, _, active_pairs = await _gather_memory_snapshot(db, user.id)
        memories_text, _, _ = _sample_memories_for_prompt(active_pairs, max_items=10)

        try:
            if job.kind == "user_post_engage":
                sys_prompt = (
                    f"你是用户的专属 AI 助手「{assistant_name}」。用户刚刚在私人动态里发了一条新动态，你过了一会儿刷到了它。"
                    f"{persona_note}\n"
                    "请像真正了解用户的朋友一样自然互动：决定是否点赞（一般值得鼓励或有共鸣就点赞），并写一条真诚、自然、简短（30~150字）的评论。"
                    "只输出严格 JSON：{\"should_like\": true, \"comment\": \"你的评论内容\"}"
                )
                user_prompt = (
                    (f"【你对用户的长期记忆】\n{memories_text}\n\n" if memories_text else "")
                    + f"【用户刚发的动态】\n标题：{post.title or '（无标题）'}\n正文：{post.content}\n标签：{', '.join(post.tags or [])}"
                )
                parsed, tokens = await _call_llm_json(
                    [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                    temperature=0.8,
                    max_tokens=400,
                )
                should_like = True if not isinstance(parsed, dict) else bool(parsed.get("should_like", True))
                comment_text = str(parsed.get("comment") or "").strip() if isinstance(parsed, dict) else ""

                if should_like:
                    post.ai_liked = True
                new_comment: PostComment | None = None
                if comment_text:
                    new_comment = PostComment(
                        post_id=post.id,
                        user_id=user.id,
                        author_type="ai",
                        content=comment_text[:2000],
                    )
                    db.add(new_comment)
                    await db.flush()

                job.status = "completed"
                job.tokens_used = tokens
                job.executed_at = datetime.now(timezone.utc)
                await db.commit()
                await _settle_tokens(db, user.id, tokens)

                if should_like:
                    await realtime_bus.publish_user_event(
                        user.id,
                        "post.updated",
                        {"post_id": str(post.id), "ai_liked": True},
                    )
                if new_comment is not None:
                    await realtime_bus.publish_user_event(
                        user.id,
                        "post.comment_created",
                        {"post_id": str(post.id), "comment": _serialize_comment(new_comment)},
                    )
                return True

            if job.kind == "comment_reply":
                trigger_comment = await db.get(PostComment, job.trigger_comment_id) if job.trigger_comment_id else None
                if trigger_comment is None:
                    job.status = "skipped"
                    job.executed_at = now
                    await db.commit()
                    return False

                all_comments = list(
                    (
                        await db.execute(
                            select(PostComment)
                            .where(PostComment.post_id == post.id)
                            .order_by(PostComment.created_at.asc())
                            .limit(30)
                        )
                    )
                    .scalars()
                    .all()
                )
                by_id = {c.id: c for c in all_comments}
                thread_lines = []
                for c in all_comments[-12:]:
                    who = "用户" if c.author_type == "user" else assistant_name
                    reply_hint = ""
                    if c.reply_to_id and c.reply_to_id in by_id:
                        parent_who = "用户" if by_id[c.reply_to_id].author_type == "user" else assistant_name
                        reply_hint = f" (回复 {parent_who})"
                    thread_lines.append(f"- {who}{reply_hint}: {c.content[:240]}")

                sys_prompt = (
                    f"你是用户的专属 AI 助手「{assistant_name}」，正在动态评论区与用户自然交流。"
                    f"{persona_note}\n"
                    "请紧扣原帖内容与评论上下文，回复用户最新的一条评论（自然、真诚、30~180字），并可决定是否给这条评论点赞。"
                    "只输出严格 JSON：{\"should_like_comment\": true, \"reply\": \"你的回复内容\"}"
                )
                user_prompt = (
                    (f"【用户长期记忆】\n{memories_text}\n\n" if memories_text else "")
                    + f"【原动态（{'AI发帖' if post.author_type == 'ai' else '用户发帖'}）】\n"
                    f"标题：{post.title or '（无标题）'}\n正文：{post.content[:800]}\n\n"
                    f"【评论区记录】\n" + "\n".join(thread_lines) + "\n\n"
                    f"【需要你回复的用户最新评论】\n{trigger_comment.content}"
                )
                parsed, tokens = await _call_llm_json(
                    [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                    temperature=0.75,
                    max_tokens=450,
                )
                should_like_comment = bool(parsed.get("should_like_comment", False)) if isinstance(parsed, dict) else False
                reply_text = str(parsed.get("reply") or "").strip() if isinstance(parsed, dict) else ""

                if should_like_comment:
                    trigger_comment.ai_liked = True
                ai_reply: PostComment | None = None
                if reply_text:
                    ai_reply = PostComment(
                        post_id=post.id,
                        user_id=user.id,
                        author_type="ai",
                        content=reply_text[:2000],
                        reply_to_id=trigger_comment.id,
                    )
                    db.add(ai_reply)
                    await db.flush()

                job.status = "completed"
                job.tokens_used = tokens
                job.executed_at = datetime.now(timezone.utc)
                await db.commit()
                await _settle_tokens(db, user.id, tokens)

                if ai_reply is not None:
                    await realtime_bus.publish_user_event(
                        user.id,
                        "post.comment_created",
                        {
                            "post_id": str(post.id),
                            "comment": _serialize_comment(ai_reply, by_id={trigger_comment.id: trigger_comment}),
                            "liked_comment_id": str(trigger_comment.id) if should_like_comment else None,
                        },
                    )
                elif should_like_comment:
                    await realtime_bus.publish_user_event(
                        user.id,
                        "post.updated",
                        {"post_id": str(post.id), "liked_comment_id": str(trigger_comment.id)},
                    )
                return True

            job.status = "skipped"
            job.executed_at = now
            await db.commit()
            return False
        except Exception as exc:
            logger.exception("Pending AI post interaction failed id=%s kind=%s", job.id, job.kind)
            await db.rollback()
            reload_job = await db.get(AiPostPendingInteraction, interaction_id)
            if reload_job is not None:
                reload_job.status = "failed"
                reload_job.error = str(exc)[:500]
                reload_job.executed_at = datetime.now(timezone.utc)
                await db.commit()
            return False


async def dispatch_due_interactions(
    *,
    session_factory: Callable[[], Any] | None = None,
    now: datetime | None = None,
    batch_size: int = 20,
    execute_inline: bool = False,
) -> int:
    """Claim due delayed AI post interactions with SKIP LOCKED and execute them."""
    factory = session_factory or SessionLocal
    current = now or datetime.now(timezone.utc)
    claimed_ids: list[uuid.UUID] = []

    async with factory() as db:
        stmt = (
            select(AiPostPendingInteraction)
            .where(
                AiPostPendingInteraction.status == "pending",
                AiPostPendingInteraction.scheduled_for <= current,
            )
            .order_by(AiPostPendingInteraction.scheduled_for.asc())
            .limit(max(1, int(batch_size or 20)))
            .with_for_update(skip_locked=True)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        for row in rows:
            row.status = "running"
            claimed_ids.append(row.id)
        if claimed_ids:
            await db.commit()

    if execute_inline:
        for jid in claimed_ids:
            await _execute_pending_interaction(factory, jid)
    else:
        for jid in claimed_ids:
            _track_task(
                _execute_pending_interaction(factory, jid),
                name=f"ai-post-interact-{jid}",
            )
    return len(claimed_ids)


# ---------------------------------------------------------------------------
# Background scheduler lifecycle
# ---------------------------------------------------------------------------


def _track_task(coro: Any, *, name: str) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro, name=name)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


async def _daily_posts_loop() -> None:
    await asyncio.sleep(8.0)
    while True:
        settings = get_settings()
        if settings.post_scheduler_enabled:
            try:
                await dispatch_daily_ai_posts()
            except Exception as exc:
                logger.warning("Daily AI posts scheduler tick failed: %s", exc)
        await asyncio.sleep(max(30.0, float(settings.post_scheduler_poll_interval_seconds)))


async def _interactions_loop() -> None:
    await asyncio.sleep(5.0)
    while True:
        settings = get_settings()
        if settings.post_scheduler_enabled:
            try:
                await dispatch_due_interactions()
            except Exception as exc:
                logger.warning("Delayed AI post interactions tick failed: %s", exc)
        await asyncio.sleep(max(5.0, float(settings.post_interaction_poll_interval_seconds)))


def start_post_scheduler() -> None:
    global _DAILY_SCHEDULER_TASK, _INTERACTION_SCHEDULER_TASK
    if not get_settings().post_scheduler_enabled:
        return
    if _DAILY_SCHEDULER_TASK is None or _DAILY_SCHEDULER_TASK.done():
        _DAILY_SCHEDULER_TASK = asyncio.create_task(_daily_posts_loop(), name="ai-daily-posts-dispatcher")
    if _INTERACTION_SCHEDULER_TASK is None or _INTERACTION_SCHEDULER_TASK.done():
        _INTERACTION_SCHEDULER_TASK = asyncio.create_task(_interactions_loop(), name="ai-post-interactions-dispatcher")


async def stop_post_scheduler() -> None:
    global _DAILY_SCHEDULER_TASK, _INTERACTION_SCHEDULER_TASK
    for task in (_DAILY_SCHEDULER_TASK, _INTERACTION_SCHEDULER_TASK):
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    _DAILY_SCHEDULER_TASK = None
    _INTERACTION_SCHEDULER_TASK = None
    if _BACKGROUND_TASKS:
        await asyncio.wait(list(_BACKGROUND_TASKS), timeout=3.0)

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.db.models import MemoryCollection, MemoryEntry, MemoryPendingProposal, User, is_pgvector_enabled
from app.db.session import detect_pgvector
from app.services import embeddings

logger = logging.getLogger("whitz.memory")

MEMORY_CHAR_LIMIT = 12000
USER_CHAR_LIMIT = 8000
PROJECTS_CHAR_LIMIT = 16000
DEFAULT_COLLECTION_CHAR_LIMIT = 12000
DEFAULT_COLLECTION_MAX_ENTRIES = 200
MIN_COLLECTION_CHAR_LIMIT = 2000
MAX_COLLECTION_CHAR_LIMIT = 50000
MAX_COLLECTIONS_PER_USER = 50
TOTAL_CHAR_LIMIT = 200000
ENTRY_DELIMITER = "\n§\n"
PINNED_MAX_ENTRIES = 10
PINNED_MAX_CHARS = 1200

SYSTEM_COLLECTIONS: tuple[dict[str, Any], ...] = (
    {
        "slug": "memory",
        "name": "通用笔记",
        "description": "跨对话沉淀的事实、约定、方法论与通用记录",
        "char_limit": MEMORY_CHAR_LIMIT,
        "max_entries": DEFAULT_COLLECTION_MAX_ENTRIES,
        "sort_order": 10,
    },
    {
        "slug": "user",
        "name": "个人画像与偏好",
        "description": "用户的身份背景、沟通风格、技术栈与长期偏好",
        "char_limit": USER_CHAR_LIMIT,
        "max_entries": DEFAULT_COLLECTION_MAX_ENTRIES,
        "sort_order": 20,
    },
    {
        "slug": "projects",
        "name": "项目与工作",
        "description": "进行中的项目架构、决策、路径与工作流上下文",
        "char_limit": PROJECTS_CHAR_LIMIT,
        "max_entries": DEFAULT_COLLECTION_MAX_ENTRIES,
        "sort_order": 30,
    },
)
_SYSTEM_BY_SLUG: dict[str, dict[str, Any]] = {item["slug"]: item for item in SYSTEM_COLLECTIONS}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9_-]+")


class MemoryServiceError(ValueError):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def normalize_slug(raw: str | None, *, fallback_name: str | None = None) -> str:
    cleaned = (raw or "").strip().lower()
    if cleaned in ("user", "user.md", "profile"):
        return "user"
    if cleaned in ("memory", "memory.md", "memories", ""):
        if not fallback_name:
            return "memory"
    if cleaned in ("projects", "project", "work"):
        return "projects"

    source = cleaned or (fallback_name or "").strip().lower()
    if not source:
        return "memory"

    slug = _SLUG_INVALID_RE.sub("-", source).strip("-_")
    if not slug:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
        slug = f"col-{digest}"
    return slug[:64]


def _sanitize_entry_text(raw: str) -> str:
    text_val = (raw or "").strip()
    if not text_val:
        return ""
    text_val = re.sub(r"(?m)^\s*§\s*$", "-", text_val)
    return text_val.strip()


def _sanitize_title(raw: str | None) -> str:
    return " ".join((raw or "").strip().split())[:120]


def _sanitize_tags(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        cleaned = " ".join(str(item or "").strip().split())[:32]
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            out.append(cleaned)
        if len(out) >= 10:
            break
    return out


def _serialized_length(contents: list[str]) -> int:
    cleaned = [c.strip() for c in contents if c and c.strip()]
    if not cleaned:
        return 0
    return len(ENTRY_DELIMITER.join(cleaned))


def _embed_text_for_entry(collection_name: str, title: str, content: str, tags: list[str]) -> str:
    parts: list[str] = []
    if collection_name:
        parts.append(f"[{collection_name}]")
    if title:
        parts.append(title)
    if tags:
        parts.append(" ".join(f"#{t}" for t in tags))
    header = " ".join(parts).strip()
    return f"{header}\n{content}" if header else content


def _tsv_text_for_entry(title: str, content: str, tags: list[str]) -> str:
    tag_str = " ".join(tags) if tags else ""
    return " ".join(p for p in (title, tag_str, content) if p).strip()


def _serialize_collection(
    row: MemoryCollection,
    *,
    entry_count: int = 0,
    char_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "slug": row.slug,
        "name": row.name,
        "description": row.description or "",
        "kind": row.kind or "custom",
        "enabled": bool(row.enabled),
        "entry_count": int(entry_count),
        "char_count": int(char_count),
        "char_limit": int(row.char_limit or DEFAULT_COLLECTION_CHAR_LIMIT),
        "max_entries": int(row.max_entries or DEFAULT_COLLECTION_MAX_ENTRIES),
        "sort_order": int(row.sort_order or 100),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_entry(
    row: MemoryEntry,
    *,
    collection_name: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "collection_id": str(row.collection_id) if row.collection_id else None,
        "collection_name": collection_name,
        "target": row.target or "memory",
        "title": getattr(row, "title", "") or "",
        "content": row.content,
        "tags": list(getattr(row, "tags", None) or []),
        "source": row.source or "manual",
        "is_pinned": bool(getattr(row, "is_pinned", False)),
        "priority": int(getattr(row, "priority", 2) or 2),
        "access_count": int(getattr(row, "access_count", 0) or 0),
        "last_accessed_at": getattr(row, "last_accessed_at", None),
        "supersedes_id": str(row.supersedes_id) if getattr(row, "supersedes_id", None) else None,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_pending(row: MemoryPendingProposal) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "collection_id": str(row.collection_id) if getattr(row, "collection_id", None) else None,
        "target": row.target,
        "title": getattr(row, "title", "") or "",
        "tags": list(getattr(row, "tags", None) or []),
        "action": row.action,
        "content": row.content,
        "old_content": row.old_content,
        "conversation_id": row.conversation_id,
        "created_at": row.created_at,
    }


async def _optional_embed(text_val: str) -> list[float] | None:
    vectors = await embeddings.embed_texts([text_val])
    return vectors[0] if vectors else None


async def ensure_default_collections(db: AsyncSession, user_id: uuid.UUID) -> list[MemoryCollection]:
    existing = list(
        (
            await db.execute(
                select(MemoryCollection)
                .where(MemoryCollection.user_id == user_id)
                .order_by(MemoryCollection.sort_order.asc(), MemoryCollection.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    existing_slugs = {c.slug for c in existing}
    missing = [spec for spec in SYSTEM_COLLECTIONS if spec["slug"] not in existing_slugs]
    if missing:
        for spec in missing:
            db.add(
                MemoryCollection(
                    user_id=user_id,
                    slug=spec["slug"],
                    name=spec["name"],
                    description=spec["description"],
                    kind="system",
                    enabled=True,
                    char_limit=spec["char_limit"],
                    max_entries=spec["max_entries"],
                    sort_order=spec["sort_order"],
                )
            )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        existing = list(
            (
                await db.execute(
                    select(MemoryCollection)
                    .where(MemoryCollection.user_id == user_id)
                    .order_by(MemoryCollection.sort_order.asc(), MemoryCollection.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
    return existing


async def _resolve_collection(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    collection_id: str | None = None,
    target: str | None = None,
    auto_create: bool = False,
    auto_name: str | None = None,
    auto_description: str = "",
) -> MemoryCollection:
    collections = await ensure_default_collections(db, user_id)
    if collection_id:
        try:
            cid = uuid.UUID(str(collection_id))
        except ValueError as exc:
            raise MemoryServiceError("记忆集不存在", 404) from exc
        for col in collections:
            if col.id == cid:
                return col
        raise MemoryServiceError("记忆集不存在", 404)

    slug = normalize_slug(target, fallback_name=auto_name)
    for col in collections:
        if col.slug == slug:
            return col

    if not auto_create:
        raise MemoryServiceError(f"记忆集 '{slug}' 不存在", 404)

    if len(collections) >= MAX_COLLECTIONS_PER_USER:
        raise MemoryServiceError(f"记忆集数量已达上限（最多 {MAX_COLLECTIONS_PER_USER} 个）", 400)

    col = MemoryCollection(
        user_id=user_id,
        slug=slug,
        name=(auto_name or slug).strip()[:80],
        description=(auto_description or "").strip()[:300],
        kind="custom",
        enabled=True,
        char_limit=DEFAULT_COLLECTION_CHAR_LIMIT,
        max_entries=DEFAULT_COLLECTION_MAX_ENTRIES,
        sort_order=100 + len(collections),
    )
    db.add(col)
    try:
        await db.commit()
        await db.refresh(col)
        return col
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(MemoryCollection).where(
                    MemoryCollection.user_id == user_id,
                    MemoryCollection.slug == slug,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        raise MemoryServiceError("创建记忆集失败，请重试", 409)


async def list_collections(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    cols = await ensure_default_collections(db, user_id)
    entries = list(
        (
            await db.execute(
                select(MemoryEntry)
                .options(defer(MemoryEntry.embedding))
                .where(MemoryEntry.user_id == user_id)
                .order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc())
            )
        )
        .scalars()
        .all()
    )
    by_col_id: dict[uuid.UUID, list[str]] = {}
    by_slug: dict[str, MemoryCollection] = {c.slug: c for c in cols}
    for row in entries:
        cid = row.collection_id
        if cid is None:
            fallback = by_slug.get(normalize_slug(row.target)) or by_slug.get("memory")
            if fallback is not None:
                cid = fallback.id
        if cid is not None:
            by_col_id.setdefault(cid, []).append(row.content)

    return [
        _serialize_collection(
            col,
            entry_count=len(by_col_id.get(col.id, [])),
            char_count=_serialized_length(by_col_id.get(col.id, [])),
        )
        for col in cols
    ]


async def create_collection(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    slug: str | None = None,
    description: str = "",
    char_limit: int = DEFAULT_COLLECTION_CHAR_LIMIT,
) -> dict[str, Any]:
    cleaned_name = " ".join((name or "").strip().split())[:80]
    if not cleaned_name:
        raise MemoryServiceError("记忆集名称不能为空", 400)

    collections = await ensure_default_collections(db, user_id)
    if len(collections) >= MAX_COLLECTIONS_PER_USER:
        raise MemoryServiceError(f"记忆集数量已达上限（最多 {MAX_COLLECTIONS_PER_USER} 个）", 400)

    norm_slug = normalize_slug(slug, fallback_name=cleaned_name)
    if any(c.slug == norm_slug for c in collections):
        raise MemoryServiceError(f"记忆集标识 '{norm_slug}' 已存在", 409)

    bounded_limit = max(MIN_COLLECTION_CHAR_LIMIT, min(int(char_limit or DEFAULT_COLLECTION_CHAR_LIMIT), MAX_COLLECTION_CHAR_LIMIT))
    col = MemoryCollection(
        user_id=user_id,
        slug=norm_slug,
        name=cleaned_name,
        description=(description or "").strip()[:300],
        kind="custom",
        enabled=True,
        char_limit=bounded_limit,
        max_entries=DEFAULT_COLLECTION_MAX_ENTRIES,
        sort_order=100 + len(collections),
    )
    db.add(col)
    try:
        await db.commit()
        await db.refresh(col)
    except IntegrityError as exc:
        await db.rollback()
        raise MemoryServiceError(f"记忆集标识 '{norm_slug}' 已存在", 409) from exc
    return _serialize_collection(col, entry_count=0, char_count=0)


async def update_collection(
    db: AsyncSession,
    user_id: uuid.UUID,
    collection_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    enabled: bool | None = None,
    char_limit: int | None = None,
    sort_order: int | None = None,
) -> dict[str, Any]:
    try:
        cid = uuid.UUID(str(collection_id))
    except ValueError as exc:
        raise MemoryServiceError("记忆集不存在", 404) from exc

    col = (
        await db.execute(
            select(MemoryCollection).where(
                MemoryCollection.id == cid,
                MemoryCollection.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if col is None:
        raise MemoryServiceError("记忆集不存在", 404)

    if name is not None:
        cleaned_name = " ".join(name.strip().split())[:80]
        if not cleaned_name:
            raise MemoryServiceError("记忆集名称不能为空", 400)
        col.name = cleaned_name
    if description is not None:
        col.description = description.strip()[:300]
    if enabled is not None:
        col.enabled = bool(enabled)
    if char_limit is not None:
        col.char_limit = max(MIN_COLLECTION_CHAR_LIMIT, min(int(char_limit), MAX_COLLECTION_CHAR_LIMIT))
    if sort_order is not None:
        col.sort_order = int(sort_order)

    await db.commit()
    await db.refresh(col)
    rows = await _collection_rows(db, user_id, col)
    return _serialize_collection(
        col,
        entry_count=len(rows),
        char_count=_serialized_length([r.content for r in rows]),
    )


async def delete_collection(db: AsyncSession, user_id: uuid.UUID, collection_id: str) -> None:
    try:
        cid = uuid.UUID(str(collection_id))
    except ValueError as exc:
        raise MemoryServiceError("记忆集不存在", 404) from exc

    col = (
        await db.execute(
            select(MemoryCollection).where(
                MemoryCollection.id == cid,
                MemoryCollection.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if col is None:
        raise MemoryServiceError("记忆集不存在", 404)
    if col.kind == "system" or col.slug in _SYSTEM_BY_SLUG:
        raise MemoryServiceError("系统预置记忆集不可删除，可关闭或清空条目", 400)

    await db.delete(col)
    await db.commit()


async def _collection_rows(
    db: AsyncSession,
    user_id: uuid.UUID,
    col: MemoryCollection,
) -> list[MemoryEntry]:
    result = await db.execute(
        select(MemoryEntry)
        .options(defer(MemoryEntry.embedding))
        .where(
            MemoryEntry.user_id == user_id,
            (MemoryEntry.collection_id == col.id) | ((MemoryEntry.collection_id.is_(None)) & (MemoryEntry.target == col.slug)),
        )
        .order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc())
    )
    return list(result.scalars().all())


async def _total_user_chars(db: AsyncSession, user_id: uuid.UUID, exclude_id: uuid.UUID | None = None) -> int:
    stmt = select(func.coalesce(func.sum(func.length(MemoryEntry.content)), 0)).where(
        MemoryEntry.user_id == user_id
    )
    if exclude_id is not None:
        stmt = stmt.where(MemoryEntry.id != exclude_id)
    return int(await db.scalar(stmt) or 0)


def _check_collection_limits(col: MemoryCollection, contents: list[str]) -> int:
    max_entries = int(col.max_entries or DEFAULT_COLLECTION_MAX_ENTRIES)
    if len(contents) > max_entries:
        raise MemoryServiceError(
            f"超出「{col.name}」条目上限（当前 {len(contents)} / {max_entries} 条），请精简或新建其他记忆集",
            400,
        )
    limit = int(col.char_limit or DEFAULT_COLLECTION_CHAR_LIMIT)
    length = _serialized_length(contents)
    if length > limit:
        raise MemoryServiceError(
            f"超出「{col.name}」字符上限（当前 {length} / {limit} 字符），请精简或删除旧记忆",
            400,
        )
    return length


async def list_entries(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    collections_map: dict[uuid.UUID, MemoryCollection] | None = None,
) -> tuple[list[dict[str, Any]], int, int, int]:
    cols = list(collections_map.values()) if collections_map is not None else await ensure_default_collections(db, user_id)
    by_id = {c.id: c for c in cols}
    by_slug = {c.slug: c for c in cols}

    result = await db.execute(
        select(MemoryEntry)
        .options(defer(MemoryEntry.embedding))
        .where(MemoryEntry.user_id == user_id)
        .order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc())
    )
    rows = list(result.scalars().all())
    items: list[dict[str, Any]] = []
    by_target: dict[str, list[str]] = {"memory": [], "user": []}
    total_chars = 0
    for row in rows:
        col = by_id.get(row.collection_id) if row.collection_id else by_slug.get(normalize_slug(row.target))
        slug = col.slug if col else (row.target or "memory")
        if slug in by_target:
            by_target[slug].append(row.content)
        total_chars += len(row.content or "")
        items.append(_serialize_entry(row, collection_name=col.name if col else slug))
    return (
        items,
        _serialized_length(by_target["memory"]),
        _serialized_length(by_target["user"]),
        total_chars,
    )


async def _enforce_pinned_budget(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    keep_id: uuid.UUID | None = None,
) -> list[str]:
    """Keep L0 always-on pinned core memory strictly bounded (<=10 items & <=1200 chars).

    Returns list of entry IDs that were automatically unpinned due to budget eviction.
    """
    rows = list(
        (
            await db.execute(
                select(MemoryEntry)
                .options(defer(MemoryEntry.embedding))
                .where(MemoryEntry.user_id == user_id, MemoryEntry.is_pinned.is_(True))
                .order_by(
                    MemoryEntry.priority.asc(),
                    MemoryEntry.last_accessed_at.desc().nullslast(),
                    MemoryEntry.updated_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    kept: list[MemoryEntry] = []
    unpinned_ids: list[str] = []
    used_chars = 0
    # Ensure keep_id always wins budget first if pinned
    ordered = sorted(rows, key=lambda r: (0 if (keep_id and r.id == keep_id) else 1))
    for r in ordered:
        entry_len = len(r.title or "") + len(r.content or "") + 16
        if len(kept) < PINNED_MAX_ENTRIES and (not kept or used_chars + entry_len <= PINNED_MAX_CHARS):
            kept.append(r)
            used_chars += entry_len
        else:
            r.is_pinned = False
            unpinned_ids.append(str(r.id))
    return unpinned_ids


async def add_entry(
    db: AsyncSession,
    user_id: uuid.UUID,
    target: str,
    raw_content: str,
    *,
    collection_id: str | None = None,
    title: str = "",
    tags: list[str] | None = None,
    source: str = "manual",
    is_pinned: bool = False,
    priority: int = 2,
    auto_create_collection: bool = False,
    collection_name: str | None = None,
    collection_description: str = "",
) -> dict[str, Any]:
    col = await _resolve_collection(
        db,
        user_id,
        collection_id=collection_id,
        target=target,
        auto_create=auto_create_collection,
        auto_name=collection_name,
        auto_description=collection_description,
    )
    content = _sanitize_entry_text(raw_content)
    if not content:
        raise MemoryServiceError("记忆内容不能为空", 400)

    cleaned_title = _sanitize_title(title)
    cleaned_tags = _sanitize_tags(tags)

    existing_rows = await _collection_rows(db, user_id, col)
    existing_texts = [r.content for r in existing_rows]
    if content in existing_texts:
        raise MemoryServiceError("该记忆条目已存在", 409)

    _check_collection_limits(col, [*existing_texts, content])
    if await _total_user_chars(db, user_id) + len(content) > TOTAL_CHAR_LIMIT:
        raise MemoryServiceError(f"超出全部记忆总字符上限（{TOTAL_CHAR_LIMIT} 字符）", 400)

    vec = await _optional_embed(_embed_text_for_entry(col.name, cleaned_title, content, cleaned_tags))
    tsv_text = _tsv_text_for_entry(cleaned_title, content, cleaned_tags)
    m_tag = embeddings.current_embedding_model_tag() or None if vec is not None else None

    row = MemoryEntry(
        user_id=user_id,
        collection_id=col.id,
        target=col.slug,
        title=cleaned_title,
        content=content,
        tags=cleaned_tags,
        source=source,
        is_pinned=bool(is_pinned),
        priority=max(1, min(3, int(priority or 2))),
        search_tsv=func.to_tsvector("simple", tsv_text),
        embedding=vec,
        embedding_model=m_tag,
    )
    db.add(row)
    await db.flush()
    unpinned_ids: list[str] = []
    if row.is_pinned:
        unpinned_ids = await _enforce_pinned_budget(db, user_id, keep_id=row.id)
    await db.commit()
    await db.refresh(row)
    out = _serialize_entry(row, collection_name=col.name)
    if unpinned_ids:
        out["auto_unpinned_ids"] = unpinned_ids
    return out


async def update_entry(
    db: AsyncSession,
    user_id: uuid.UUID,
    entry_id: str,
    raw_content: str | None = None,
    *,
    new_target: str | None = None,
    new_collection_id: str | None = None,
    title: str | None = None,
    tags: list[str] | None = None,
    is_pinned: bool | None = None,
    priority: int | None = None,
) -> dict[str, Any]:
    try:
        entry_uuid = uuid.UUID(str(entry_id))
    except ValueError as exc:
        raise MemoryServiceError("记忆条目不存在", 404) from exc

    row = (
        await db.execute(
            select(MemoryEntry).where(MemoryEntry.id == entry_uuid, MemoryEntry.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise MemoryServiceError("记忆条目不存在", 404)

    content = _sanitize_entry_text(raw_content) if raw_content is not None else row.content
    if not content:
        raise MemoryServiceError("记忆内容不能为空", 400)

    if new_collection_id is not None or new_target is not None:
        dest_col = await _resolve_collection(
            db,
            user_id,
            collection_id=new_collection_id,
            target=new_target,
        )
    elif row.collection_id is not None:
        dest_col = await _resolve_collection(db, user_id, collection_id=str(row.collection_id))
    else:
        dest_col = await _resolve_collection(db, user_id, target=row.target)

    content_changed = (
        content != row.content
        or dest_col.id != row.collection_id
        or (title is not None and _sanitize_title(title) != (row.title or ""))
        or (tags is not None and _sanitize_tags(tags) != list(row.tags or []))
    )

    if content_changed:
        dest_rows = await _collection_rows(db, user_id, dest_col)
        for other in dest_rows:
            if other.id != row.id and other.content == content:
                raise MemoryServiceError("目标记忆集中已存在相同的记忆条目", 409)

        if row.collection_id == dest_col.id or (row.collection_id is None and row.target == dest_col.slug):
            next_texts = [content if r.id == row.id else r.content for r in dest_rows]
        else:
            next_texts = [r.content for r in dest_rows] + [content]
        _check_collection_limits(dest_col, next_texts)
        if await _total_user_chars(db, user_id, exclude_id=row.id) + len(content) > TOTAL_CHAR_LIMIT:
            raise MemoryServiceError(f"超出全部记忆总字符上限（{TOTAL_CHAR_LIMIT} 字符）", 400)

        next_title = _sanitize_title(title) if title is not None else (getattr(row, "title", "") or "")
        next_tags = _sanitize_tags(tags) if tags is not None else list(getattr(row, "tags", None) or [])

        vec = await _optional_embed(_embed_text_for_entry(dest_col.name, next_title, content, next_tags))
        tsv_text = _tsv_text_for_entry(next_title, content, next_tags)

        row.collection_id = dest_col.id
        row.target = dest_col.slug
        row.title = next_title
        row.content = content
        row.tags = next_tags
        row.source = "manual"
        row.search_tsv = func.to_tsvector("simple", tsv_text)
        row.embedding = vec
        row.embedding_model = embeddings.current_embedding_model_tag() or None if vec is not None else None

    if is_pinned is not None:
        row.is_pinned = bool(is_pinned)
    if priority is not None:
        row.priority = max(1, min(3, int(priority)))

    await db.flush()
    unpinned_ids: list[str] = []
    if row.is_pinned:
        unpinned_ids = await _enforce_pinned_budget(db, user_id, keep_id=row.id)
    await db.commit()
    await db.refresh(row)
    out = _serialize_entry(row, collection_name=dest_col.name)
    if unpinned_ids:
        out["auto_unpinned_ids"] = unpinned_ids
    return out


async def delete_entry(db: AsyncSession, user_id: uuid.UUID, entry_id: str) -> None:
    try:
        entry_uuid = uuid.UUID(str(entry_id))
    except ValueError as exc:
        raise MemoryServiceError("记忆条目不存在", 404) from exc

    row = (
        await db.execute(
            select(MemoryEntry).where(MemoryEntry.id == entry_uuid, MemoryEntry.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise MemoryServiceError("记忆条目不存在", 404)
    await db.delete(row)
    await db.commit()


async def clear_all(db: AsyncSession, user_id: uuid.UUID, *, collection_id: str | None = None) -> None:
    if collection_id:
        col = await _resolve_collection(db, user_id, collection_id=collection_id)
        await db.execute(
            delete(MemoryEntry).where(
                MemoryEntry.user_id == user_id,
                (MemoryEntry.collection_id == col.id) | ((MemoryEntry.collection_id.is_(None)) & (MemoryEntry.target == col.slug)),
            )
        )
        await db.commit()
        return

    await db.execute(delete(MemoryEntry).where(MemoryEntry.user_id == user_id))
    await db.execute(delete(MemoryPendingProposal).where(MemoryPendingProposal.user_id == user_id))
    await db.commit()


async def list_pending(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(MemoryPendingProposal).where(
        MemoryPendingProposal.user_id == user_id,
        MemoryPendingProposal.status == "pending",
    )
    if conversation_id:
        try:
            conv_uuid = uuid.UUID(str(conversation_id))
            stmt = stmt.where(MemoryPendingProposal.conversation_id == conv_uuid)
        except ValueError:
            return []
    result = await db.execute(
        stmt.order_by(MemoryPendingProposal.created_at.asc(), MemoryPendingProposal.id.asc())
    )
    return [_serialize_pending(row) for row in result.scalars().all()]


async def resolve_pending(
    db: AsyncSession,
    user_id: uuid.UUID,
    pending_id: str,
    action: str,
    *,
    content_override: str | None = None,
) -> None:
    if not _SAFE_ID_RE.match(pending_id) or ".." in pending_id:
        raise MemoryServiceError("无效的待审批记忆 ID", 400)
    try:
        pending_uuid = uuid.UUID(pending_id)
    except ValueError as exc:
        raise MemoryServiceError("待审批记忆不存在", 404) from exc

    proposal = (
        await db.execute(
            select(MemoryPendingProposal).where(
                MemoryPendingProposal.id == pending_uuid,
                MemoryPendingProposal.user_id == user_id,
                MemoryPendingProposal.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise MemoryServiceError("待审批记忆不存在", 404)

    if action == "reject":
        proposal.status = "rejected"
        await db.commit()
        return
    if action != "approve":
        raise MemoryServiceError(f"不支持的审批动作: {action}", 400)

    col = await _resolve_collection(
        db,
        user_id,
        collection_id=str(proposal.collection_id) if getattr(proposal, "collection_id", None) else None,
        target=proposal.target,
        auto_create=True,
    )
    op = (proposal.action or "add").strip().lower()
    resolved_text = _sanitize_entry_text(
        content_override if content_override is not None else proposal.content
    )
    resolved_title = _sanitize_title(getattr(proposal, "title", ""))
    resolved_tags = _sanitize_tags(list(getattr(proposal, "tags", None) or []))
    existing_rows = await _collection_rows(db, user_id, col)

    if op == "remove":
        needle = (proposal.old_content or resolved_text).strip()
        if not needle:
            raise MemoryServiceError("待删除内容为空", 400)
        to_delete = [r for r in existing_rows if r.content == needle]
        if not to_delete and len(needle) >= 6:
            substring_matches = [r for r in existing_rows if needle in r.content]
            if len(substring_matches) == 1:
                to_delete = substring_matches
            elif len(substring_matches) > 1:
                raise MemoryServiceError(
                    f"待删除内容匹配了 {len(substring_matches)} 条记忆，请手动选择精确条目删除",
                    409,
                )
        for row in to_delete:
            await db.delete(row)
        proposal.status = "approved"
        await db.commit()
        return

    if not resolved_text:
        raise MemoryServiceError("记忆内容不能为空", 400)

    tsv_text = _tsv_text_for_entry(resolved_title, resolved_text, resolved_tags)

    if op == "replace":
        old_text = (proposal.old_content or "").strip()
        matched_row = next((r for r in existing_rows if old_text and r.content == old_text), None)
        if matched_row is None and old_text and len(old_text) >= 6:
            sub = [r for r in existing_rows if old_text in r.content]
            if len(sub) == 1:
                matched_row = sub[0]
        if matched_row is None:
            if old_text:
                raise MemoryServiceError("原记忆条目已不存在，无法替换", 409)
            if not any(r.content == resolved_text for r in existing_rows):
                _check_collection_limits(col, [r.content for r in existing_rows] + [resolved_text])
                if await _total_user_chars(db, user_id) + len(resolved_text) > TOTAL_CHAR_LIMIT:
                    raise MemoryServiceError(f"超出全部记忆总字符上限（{TOTAL_CHAR_LIMIT} 字符）", 400)
                vec = await _optional_embed(_embed_text_for_entry(col.name, resolved_title, resolved_text, resolved_tags))
                m_tag = embeddings.current_embedding_model_tag() or None if vec is not None else None
                db.add(
                    MemoryEntry(
                        user_id=user_id,
                        collection_id=col.id,
                        target=col.slug,
                        title=resolved_title,
                        content=resolved_text,
                        tags=resolved_tags,
                        source="agent",
                        search_tsv=func.to_tsvector("simple", tsv_text),
                        embedding=vec,
                        embedding_model=m_tag,
                    )
                )
        else:
            next_texts = [resolved_text if r.id == matched_row.id else r.content for r in existing_rows]
            _check_collection_limits(col, next_texts)
            if await _total_user_chars(db, user_id, exclude_id=matched_row.id) + len(resolved_text) > TOTAL_CHAR_LIMIT:
                raise MemoryServiceError(f"超出全部记忆总字符上限（{TOTAL_CHAR_LIMIT} 字符）", 400)
            matched_row.collection_id = col.id
            matched_row.target = col.slug
            if resolved_title:
                matched_row.title = resolved_title
            if resolved_tags:
                matched_row.tags = resolved_tags
            matched_row.content = resolved_text
            matched_row.source = "agent"
            matched_row.search_tsv = func.to_tsvector("simple", tsv_text)
            vec = await _optional_embed(
                _embed_text_for_entry(col.name, matched_row.title or "", resolved_text, list(matched_row.tags or []))
            )
            matched_row.embedding = vec
            matched_row.embedding_model = embeddings.current_embedding_model_tag() or None if vec is not None else None
    else:
        if not any(r.content == resolved_text for r in existing_rows):
            _check_collection_limits(col, [r.content for r in existing_rows] + [resolved_text])
            if await _total_user_chars(db, user_id) + len(resolved_text) > TOTAL_CHAR_LIMIT:
                raise MemoryServiceError(f"超出全部记忆总字符上限（{TOTAL_CHAR_LIMIT} 字符）", 400)
            vec = await _optional_embed(_embed_text_for_entry(col.name, resolved_title, resolved_text, resolved_tags))
            m_tag = embeddings.current_embedding_model_tag() or None if vec is not None else None
            db.add(
                MemoryEntry(
                    user_id=user_id,
                    collection_id=col.id,
                    target=col.slug,
                    title=resolved_title,
                    content=resolved_text,
                    tags=resolved_tags,
                    source="agent",
                    search_tsv=func.to_tsvector("simple", tsv_text),
                    embedding=vec,
                    embedding_model=m_tag,
                )
            )

    proposal.status = "approved"
    await db.commit()


async def build_pinned_memory_prompt(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    max_items: int = PINNED_MAX_ENTRIES,
    max_chars: int = PINNED_MAX_CHARS,
) -> str:
    """Build L0 Always-On Core Memory block (strictly bounded, KV-prefix-cache friendly, never needs RAG)."""
    cols = await ensure_default_collections(db, user_id)
    enabled_cols = {c.id: c for c in cols if c.enabled}
    enabled_slugs = {c.slug: c for c in cols if c.enabled}
    if not enabled_cols:
        return ""

    rows = list(
        (
            await db.execute(
                select(MemoryEntry)
                .options(defer(MemoryEntry.embedding))
                .where(MemoryEntry.user_id == user_id, MemoryEntry.is_pinned.is_(True))
                .order_by(
                    MemoryEntry.priority.asc(),
                    MemoryEntry.updated_at.desc(),
                )
                .limit(max_items * 2)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return ""

    lines: list[str] = []
    used = 0
    for row in rows:
        col = enabled_cols.get(row.collection_id) if row.collection_id else enabled_slugs.get(normalize_slug(row.target))
        if col is None:
            continue
        title = (getattr(row, "title", "") or "").strip()
        content = " ".join((row.content or "").split()).strip()
        if not content:
            continue
        if len(content) > 220:
            content = content[:219].rstrip() + "…"
        prefix = f"[{col.name}] {title}：" if title else f"[{col.name}] "
        line = f"- {prefix}{content}"
        if lines and used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
        if len(lines) >= max_items:
            break
    return "\n".join(lines)


async def build_memory_index_prompt(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    max_chars: int = 1200,
) -> str:
    """Build a lightweight directory index of enabled memory collections for system prompt injection."""
    cols = await ensure_default_collections(db, user_id)
    enabled_cols = [c for c in cols if c.enabled]
    if not enabled_cols:
        return ""

    entries = list(
        (
            await db.execute(
                select(MemoryEntry)
                .options(defer(MemoryEntry.embedding))
                .where(MemoryEntry.user_id == user_id)
                .order_by(MemoryEntry.updated_at.desc(), MemoryEntry.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    by_col: dict[uuid.UUID, list[MemoryEntry]] = {}
    by_slug = {c.slug: c for c in enabled_cols}
    for row in entries:
        cid = row.collection_id
        if cid is None:
            fallback = by_slug.get(normalize_slug(row.target))
            if fallback is not None:
                cid = fallback.id
        if cid is not None:
            by_col.setdefault(cid, []).append(row)

    lines: list[str] = [
        "以下为当前已启用的记忆集目录（未预灌全文，请按需调用 `memory_search` 做 RAG 检索或 `memory_list` 查阅明细，也可以用 `memory_propose` / `memory_manage_collection` 自主新建集、写入或修改）："
    ]
    used = len(lines[0])
    for col in enabled_cols:
        col_entries = by_col.get(col.id, [])
        sample_hints: list[str] = []
        for e in col_entries[:3]:
            hint = (getattr(e, "title", "") or "").strip() or (e.content or "").strip().splitlines()[0]
            if len(hint) > 28:
                hint = hint[:27].rstrip() + "…"
            if hint:
                sample_hints.append(hint)
        desc_part = f" — {col.description}" if col.description else ""
        hint_part = f"（近况：{' / '.join(sample_hints)}）" if sample_hints else "（暂无条目）"
        line = f"- `{col.slug}`【{col.name}】({len(col_entries)} 条){desc_part}{hint_part}"
        if used + len(line) + 1 > max_chars:
            lines.append("- …（更多记忆集请调用 `memory_list()` 查看）")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


async def search_entries_rag(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    collection: str | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Hybrid RAG search over memory_entries powered by shared UnifiedKnowledgeRetriever (3-leg + RRF + Rerank + MMR)."""
    from whitz_rag import UnifiedKnowledgeRetriever

    cleaned = (query or "").strip()
    if not cleaned:
        return []

    await ensure_default_collections(db, user_id)
    target_slug = normalize_slug(collection) if collection else None
    await detect_pgvector(db)

    retriever = UnifiedKnowledgeRetriever(
        session=db,
        embedding_client=embeddings.get_embedding_client(),
        rerank_client=embeddings.get_rerank_client(),
    )
    items = await retriever.search_memories(
        user_id=str(user_id),
        query=cleaned,
        collection=target_slug,
        top_k=limit,
        apply_rerank=True,
    )
    return [
        {
            "id": it.source_id,
            "collection_id": it.metadata.get("collection_id"),
            "target": str(it.metadata.get("collection") or "memory"),
            "collection_name": str(it.metadata.get("collection_name") or it.title),
            "title": it.title,
            "content": it.content,
            "tags": list(it.metadata.get("tags") or []),
            "source": str(it.metadata.get("source") or "manual"),
            "score": round(float(it.score), 6),
        }
        for it in items
    ]


async def get_overview(db: AsyncSession, user: User) -> dict[str, Any]:
    cols = await ensure_default_collections(db, user.id)
    cols_map = {c.id: c for c in cols}
    entries, memory_chars, user_chars, total_chars = await list_entries(db, user.id, collections_map=cols_map)
    pending = await list_pending(db, user.id)

    by_col_id: dict[str, list[str]] = {}
    for e in entries:
        cid = e.get("collection_id")
        if cid:
            by_col_id.setdefault(cid, []).append(e["content"])
    serialized_cols = [
        _serialize_collection(
            col,
            entry_count=len(by_col_id.get(str(col.id), [])),
            char_count=_serialized_length(by_col_id.get(str(col.id), [])),
        )
        for col in cols
    ]
    mem_col = next((c for c in cols if c.slug == "memory"), None)
    user_col = next((c for c in cols if c.slug == "user"), None)
    mem_limit = int(mem_col.char_limit) if mem_col else MEMORY_CHAR_LIMIT
    user_limit = int(user_col.char_limit) if user_col else USER_CHAR_LIMIT

    return {
        "memory_enabled": bool(user.memory_enabled),
        "memory_consented_at": user.memory_consented_at,
        "memory_require_confirm": bool(user.memory_require_confirm),
        "collections": serialized_cols,
        "entries": entries,
        "pending": pending,
        "char_count": memory_chars,
        "char_limit": mem_limit,
        "memory_char_count": memory_chars,
        "memory_char_limit": mem_limit,
        "user_char_count": user_chars,
        "user_char_limit": user_limit,
        "total_char_count": total_chars,
        "total_char_limit": TOTAL_CHAR_LIMIT,
        "collection_limit": MAX_COLLECTIONS_PER_USER,
        "pinned_count": sum(1 for e in entries if e.get("is_pinned")),
        "pinned_limit": PINNED_MAX_ENTRIES,
    }

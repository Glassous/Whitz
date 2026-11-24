from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MemoryEntry, MemoryPendingProposal, User
from app.services import embeddings

logger = logging.getLogger("whitz.memory")

MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375
ENTRY_DELIMITER = "\n§\n"

_TARGET_SPEC: dict[str, tuple[str, int]] = {
    "memory": ("MEMORY.md", MEMORY_CHAR_LIMIT),
    "user": ("USER.md", USER_CHAR_LIMIT),
}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class MemoryServiceError(ValueError):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _normalize_target(target: str | None) -> str:
    cleaned = (target or "memory").strip().lower()
    if cleaned in ("user", "user.md", "profile"):
        return "user"
    if cleaned in ("memory", "memory.md", "memories", ""):
        return "memory"
    raise MemoryServiceError(f"不支持的记忆目标类型: {target}", 400)


def _sanitize_entry_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?m)^\s*§\s*$", "-", text)
    return text.strip()


def _serialized_length(contents: list[str]) -> int:
    cleaned = [c.strip() for c in contents if c and c.strip()]
    if not cleaned:
        return 0
    return len(ENTRY_DELIMITER.join(cleaned))


def _check_target_limit(target: str, contents: list[str]) -> int:
    filename, limit = _TARGET_SPEC[target]
    length = _serialized_length(contents)
    if length > limit:
        raise MemoryServiceError(
            f"超出 {filename} 字符上限（当前 {length} / {limit} 字符），请精简或删除旧记忆",
            400,
        )
    return length


def _serialize_entry(row: MemoryEntry) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "target": row.target,
        "content": row.content,
        "source": row.source or "manual",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _serialize_pending(row: MemoryPendingProposal) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "target": row.target,
        "action": row.action,
        "content": row.content,
        "old_content": row.old_content,
        "conversation_id": row.conversation_id,
        "created_at": row.created_at,
    }


async def _optional_embed(text: str) -> list[float] | None:
    vectors = await embeddings.embed_texts([text])
    return vectors[0] if vectors else None


async def _target_rows(db: AsyncSession, user_id: uuid.UUID, target: str) -> list[MemoryEntry]:
    result = await db.execute(
        select(MemoryEntry)
        .where(MemoryEntry.user_id == user_id, MemoryEntry.target == target)
        .order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc())
    )
    return list(result.scalars().all())


async def list_entries(db: AsyncSession, user_id: uuid.UUID) -> tuple[list[dict[str, Any]], int, int]:
    result = await db.execute(
        select(MemoryEntry)
        .where(MemoryEntry.user_id == user_id)
        .order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc())
    )
    rows = list(result.scalars().all())
    items: list[dict[str, Any]] = []
    by_target: dict[str, list[str]] = {"memory": [], "user": []}
    for row in rows:
        t = row.target if row.target in by_target else "memory"
        by_target[t].append(row.content)
        items.append(_serialize_entry(row))
    return items, _serialized_length(by_target["memory"]), _serialized_length(by_target["user"])


async def add_entry(
    db: AsyncSession,
    user_id: uuid.UUID,
    target: str,
    raw_content: str,
    *,
    source: str = "manual",
) -> dict[str, Any]:
    norm_target = _normalize_target(target)
    content = _sanitize_entry_text(raw_content)
    if not content:
        raise MemoryServiceError("记忆内容不能为空", 400)

    existing_rows = await _target_rows(db, user_id, norm_target)
    existing_texts = [r.content for r in existing_rows]
    if content in existing_texts:
        raise MemoryServiceError("该记忆条目已存在", 409)

    _check_target_limit(norm_target, [*existing_texts, content])
    vec = await _optional_embed(content)

    row = MemoryEntry(
        user_id=user_id,
        target=norm_target,
        content=content,
        source=source,
        embedding=vec,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_entry(row)


async def update_entry(
    db: AsyncSession,
    user_id: uuid.UUID,
    entry_id: str,
    raw_content: str,
    *,
    new_target: str | None = None,
) -> dict[str, Any]:
    content = _sanitize_entry_text(raw_content)
    if not content:
        raise MemoryServiceError("记忆内容不能为空", 400)

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

    current_target = row.target
    dest_target = _normalize_target(new_target) if new_target is not None else current_target

    dest_rows = await _target_rows(db, user_id, dest_target)
    for other in dest_rows:
        if other.id != row.id and other.content == content:
            raise MemoryServiceError("目标中已存在相同的记忆条目", 409)

    if dest_target == current_target:
        next_texts = [content if r.id == row.id else r.content for r in dest_rows]
    else:
        next_texts = [r.content for r in dest_rows] + [content]
    _check_target_limit(dest_target, next_texts)

    vec = await _optional_embed(content)
    row.target = dest_target
    row.content = content
    row.source = "manual"
    row.embedding = vec
    await db.commit()
    await db.refresh(row)
    return _serialize_entry(row)


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


async def clear_all(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(delete(MemoryEntry).where(MemoryEntry.user_id == user_id))
    await db.execute(delete(MemoryPendingProposal).where(MemoryPendingProposal.user_id == user_id))
    await db.commit()


async def list_pending(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await db.execute(
        select(MemoryPendingProposal)
        .where(MemoryPendingProposal.user_id == user_id, MemoryPendingProposal.status == "pending")
        .order_by(MemoryPendingProposal.created_at.asc(), MemoryPendingProposal.id.asc())
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
        await db.delete(proposal)
        await db.commit()
        return
    if action != "approve":
        raise MemoryServiceError(f"不支持的审批动作: {action}", 400)

    target = _normalize_target(proposal.target)
    op = (proposal.action or "add").strip().lower()
    resolved_text = _sanitize_entry_text(
        content_override if content_override is not None else proposal.content
    )
    existing_rows = await _target_rows(db, user_id, target)

    if op == "remove":
        needle = (proposal.old_content or resolved_text).strip()
        if not needle:
            raise MemoryServiceError("待删除内容为空", 400)
        to_delete = [r for r in existing_rows if r.content == needle]
        if not to_delete:
            to_delete = [r for r in existing_rows if needle in r.content]
        for row in to_delete:
            await db.delete(row)
        await db.delete(proposal)
        await db.commit()
        return

    if not resolved_text:
        raise MemoryServiceError("记忆内容不能为空", 400)

    if op == "replace":
        old_text = (proposal.old_content or "").strip()
        matched_row = None
        for r in existing_rows:
            if old_text and (r.content == old_text or old_text in r.content):
                matched_row = r
                break
        if matched_row is None:
            if old_text:
                raise MemoryServiceError("原记忆条目已不存在，无法替换", 409)
            if not any(r.content == resolved_text for r in existing_rows):
                _check_target_limit(target, [r.content for r in existing_rows] + [resolved_text])
                vec = await _optional_embed(resolved_text)
                db.add(
                    MemoryEntry(
                        user_id=user_id,
                        target=target,
                        content=resolved_text,
                        source="agent",
                        embedding=vec,
                    )
                )
        else:
            next_texts = [resolved_text if r.id == matched_row.id else r.content for r in existing_rows]
            _check_target_limit(target, next_texts)
            matched_row.content = resolved_text
            matched_row.source = "agent"
            matched_row.embedding = await _optional_embed(resolved_text)
    else:
        if not any(r.content == resolved_text for r in existing_rows):
            _check_target_limit(target, [r.content for r in existing_rows] + [resolved_text])
            vec = await _optional_embed(resolved_text)
            db.add(
                MemoryEntry(
                    user_id=user_id,
                    target=target,
                    content=resolved_text,
                    source="agent",
                    embedding=vec,
                )
            )

    await db.delete(proposal)
    await db.commit()


async def get_overview(db: AsyncSession, user: User) -> dict[str, Any]:
    entries, memory_chars, user_chars = await list_entries(db, user.id)
    pending = await list_pending(db, user.id)
    return {
        "memory_enabled": bool(user.memory_enabled),
        "memory_consented_at": user.memory_consented_at,
        "memory_require_confirm": bool(user.memory_require_confirm),
        "entries": entries,
        "pending": pending,
        "char_count": memory_chars,
        "char_limit": MEMORY_CHAR_LIMIT,
        "memory_char_count": memory_chars,
        "memory_char_limit": MEMORY_CHAR_LIMIT,
        "user_char_count": user_chars,
        "user_char_limit": USER_CHAR_LIMIT,
    }

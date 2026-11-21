from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageReaction

USER_ALLOWED_REACTIONS = ("like", "love", "insightful", "celebrate", "dislike")
AI_ALLOWED_REACTIONS = ("like", "love", "sparkle", "insightful")
POSITIVE_REACTIONS = frozenset({"like", "love", "insightful", "celebrate", "sparkle"})
NEGATIVE_REACTIONS = frozenset({"dislike"})


def serialize_reaction(row: MessageReaction) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "message_id": str(row.message_id),
        "author_type": row.author_type,
        "reaction": row.reaction,
        "reason_code": row.reason_code,
        "comment": row.comment,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def validate_reaction(*, author_type: str, reaction: str) -> str:
    cleaned = (reaction or "").strip().lower()
    if author_type == "assistant":
        if cleaned not in AI_ALLOWED_REACTIONS:
            raise ValueError("ai_reaction_must_be_positive")
        return cleaned
    if cleaned not in USER_ALLOWED_REACTIONS:
        raise ValueError("unsupported_reaction")
    return cleaned


async def upsert_reaction(
    db: AsyncSession,
    *,
    message: Message,
    user_id: uuid.UUID,
    author_type: str,
    reaction: str,
    reason_code: str | None = None,
    comment: str | None = None,
) -> MessageReaction:
    eff_reaction = validate_reaction(author_type=author_type, reaction=reaction)
    if author_type == "assistant" and message.role != "user":
        raise ValueError("ai_can_only_react_to_user_messages")

    existing = (
        await db.execute(
            select(MessageReaction).where(
                MessageReaction.message_id == message.id,
                MessageReaction.author_type == author_type,
                MessageReaction.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    cleaned_reason = (reason_code or "").strip()[:40] or None
    cleaned_comment = (comment or "").strip()[:500] or None
    if author_type == "assistant":
        cleaned_reason = None

    if existing is None:
        existing = MessageReaction(
            message_id=message.id,
            conversation_id=message.conversation_id,
            user_id=user_id,
            author_type=author_type,
            reaction=eff_reaction,
            reason_code=cleaned_reason,
            comment=cleaned_comment,
        )
        db.add(existing)
    else:
        existing.reaction = eff_reaction
        existing.reason_code = cleaned_reason
        existing.comment = cleaned_comment

    await db.commit()
    await db.refresh(existing)
    return existing


async def delete_reaction(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    author_type: str = "user",
) -> bool:
    existing = (
        await db.execute(
            select(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.author_type == author_type,
                MessageReaction.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return False
    await db.delete(existing)
    await db.commit()
    return True


async def list_message_reactions(db: AsyncSession, message_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(MessageReaction)
            .where(MessageReaction.message_id == message_id)
            .order_by(MessageReaction.created_at.asc())
        )
    ).scalars().all()
    return [serialize_reaction(r) for r in rows]

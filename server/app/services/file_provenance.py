from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ConversationFile, Message, User

INLINE_FILE_TOKEN_RE = re.compile(r"\[\[file:([0-9a-fA-F-]{36})\|([^\]]+)\]\]")


def extract_inline_file_ids(text: str | None) -> list[uuid.UUID]:
    """Extract unique file UUIDs referenced via [[file:<uuid>|<filename>]] in message text."""
    if not text:
        return []
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []
    for match in INLINE_FILE_TOKEN_RE.finditer(text):
        try:
            fid = uuid.UUID(match.group(1))
        except ValueError:
            continue
        if fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


def format_qa_snippet(text: str | None, max_len: int = 64) -> str | None:
    if not text:
        return None
    cleaned = INLINE_FILE_TOKEN_RE.sub(lambda m: f"「{m.group(2).strip()}」", text)
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        return None
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


async def resolve_files_provenance(
    db: AsyncSession,
    user: User,
    files: list[ConversationFile],
) -> dict[uuid.UUID, dict[str, Any]]:
    """Batch-resolve conversation title/kind and Q&A turn snippet for a list of files."""
    if not files:
        return {}

    conv_ids = {f.conversation_id for f in files if f.conversation_id is not None}
    msg_ids = {f.message_id for f in files if f.message_id is not None}

    conv_map: dict[uuid.UUID, tuple[str, str]] = {}
    if conv_ids:
        conv_rows = (
            await db.execute(
                select(Conversation.id, Conversation.title, Conversation.kind).where(
                    Conversation.id.in_(conv_ids),
                    Conversation.user_id == user.id,
                )
            )
        ).all()
        assistant_label = (getattr(user, "assistant_name", None) or "").strip() or "Whitz"
        for cid, title, kind in conv_rows:
            display_title = f"{assistant_label}（主聊）" if kind == "main" else (title or "未命名对话")
            conv_map[cid] = (display_title, kind or "side")

    msg_map: dict[uuid.UUID, Message] = {}
    if msg_ids:
        msg_rows = (
            await db.execute(select(Message).where(Message.id.in_(msg_ids)))
        ).scalars().all()
        for m in msg_rows:
            msg_map[m.id] = m

    # For files bound to assistant messages, fetch user messages in those conversations to locate the Q&A prompt
    assistant_conv_ids = {
        m.conversation_id for m in msg_map.values() if m.role == "assistant"
    }
    user_msgs_by_conv: dict[uuid.UUID, list[Message]] = {}
    if assistant_conv_ids:
        u_rows = (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id.in_(assistant_conv_ids),
                    Message.role == "user",
                )
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()
        for um in u_rows:
            user_msgs_by_conv.setdefault(um.conversation_id, []).append(um)

    result: dict[uuid.UUID, dict[str, Any]] = {}
    for f in files:
        conv_title, conv_kind = conv_map.get(f.conversation_id, (None, None)) if f.conversation_id else (None, None)
        qa_snippet: str | None = None
        turn_role: str | None = None

        msg = msg_map.get(f.message_id) if f.message_id else None
        if msg is not None:
            turn_role = msg.role
            if msg.role == "user":
                qa_snippet = format_qa_snippet(msg.content)
            elif msg.role == "assistant":
                candidates = user_msgs_by_conv.get(msg.conversation_id) or []
                preceding: Message | None = None
                for um in candidates:
                    if um.created_at <= msg.created_at:
                        preceding = um
                    else:
                        break
                qa_snippet = format_qa_snippet(preceding.content if preceding is not None else msg.content)

        result[f.id] = {
            "conversation_title": conv_title,
            "conversation_kind": conv_kind,
            "qa_snippet": qa_snippet,
            "turn_role": turn_role,
        }
    return result

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from whitz_rag import UnifiedKnowledgeRetriever

from app.api.deps import get_current_user
from app.core.ratelimit import unified_search_limiter
from app.db.models import Conversation, Message, User
from app.db.session import detect_pgvector, get_db
from app.services import embeddings

router = APIRouter(prefix="/api/search", tags=["search"])


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_snippet(text: str, query: str, before: int = 40, after: int = 90) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    if not collapsed:
        return ""
    idx = collapsed.lower().find(query.lower())
    if idx < 0:
        return collapsed[: before + after] + ("…" if len(collapsed) > before + after else "")
    start = max(0, idx - before)
    end = min(len(collapsed), idx + len(query) + after)
    return ("…" if start > 0 else "") + collapsed[start:end] + ("…" if end < len(collapsed) else "")


@router.get("/unified")
async def unified_semantic_search(
    q: str = Query(..., min_length=1, max_length=300),
    sources: Literal["all", "file", "memory", "chat"] = Query(default="all"),
    limit: int = Query(default=12, ge=1, le=30),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Unified Hybrid RAG Omnibox search across Conversations, Library File Contents, and Long-Term Memories."""
    term = q.strip()
    if not term:
        return {"query": "", "files": [], "memories": [], "chats": [], "total": 0}
    if not await unified_search_limiter.allow(str(user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "搜索过于频繁，请稍后再试")

    await detect_pgvector(db)
    target_sources = ["file", "memory", "chat"] if sources == "all" else [sources]
    retriever = UnifiedKnowledgeRetriever(
        session=db,
        embedding_client=embeddings.get_embedding_client(),
        rerank_client=embeddings.get_rerank_client(),
    )

    items, diag = await retriever.search_unified(
        user_id=str(user.id),
        queries=[term],
        sources=target_sources,
        exclude_current_chat=False,
        top_k=limit * (2 if sources == "all" else 1),
        per_source_k=limit,
        expand_neighbors=False,
        enable_corrective=True,
        stage="omnibox",
    )

    files_out: list[dict[str, Any]] = []
    memories_out: list[dict[str, Any]] = []
    chats_out: list[dict[str, Any]] = []
    seen_chat_keys: set[str] = set()
    assistant_label = (user.assistant_name or "").strip() or "Whitz"

    for it in items:
        meta = it.metadata or {}
        if it.source_type == "file":
            files_out.append(
                {
                    "type": "file",
                    "file_id": str(meta.get("file_id") or it.source_id),
                    "filename": str(meta.get("filename") or it.title),
                    "locator": str(meta.get("locator") or it.subtitle),
                    "section_path": str(meta.get("section_path") or ""),
                    "chunk_type": str(meta.get("chunk_type") or "text"),
                    "snippet": it.snippet,
                    "score": round(float(it.score), 4),
                    "confidence": it.confidence,
                    "conversation_id": meta.get("conversation_id"),
                }
            )
        elif it.source_type == "memory":
            memories_out.append(
                {
                    "type": "memory",
                    "entry_id": it.source_id,
                    "title": it.title,
                    "collection": str(meta.get("collection") or "memory"),
                    "collection_name": str(meta.get("collection_name") or meta.get("collection") or "memory"),
                    "tags": list(meta.get("tags") or []),
                    "snippet": it.snippet,
                    "content": it.content,
                    "score": round(float(it.score), 4),
                    "confidence": it.confidence,
                    "timestamp": meta.get("timestamp"),
                }
            )
        else:
            conv_id = str(meta.get("conversation_id") or it.source_id)
            msg_id = meta.get("message_id")
            ckey = f"{conv_id}:{msg_id or it.source_type}"
            if ckey in seen_chat_keys:
                continue
            seen_chat_keys.add(ckey)
            kind = str(meta.get("kind") or "side")
            chats_out.append(
                {
                    "type": "chat",
                    "match_in": "digest" if it.source_type == "chat_digest" else "semantic_turn",
                    "conversation_id": conv_id,
                    "conversation_kind": kind,
                    "conversation_title": assistant_label if kind == "main" else (it.title or "未命名旁聊"),
                    "message_id": msg_id,
                    "snippet": it.snippet,
                    "score": round(float(it.score), 4),
                    "confidence": it.confidence,
                    "created_at": meta.get("timestamp"),
                }
            )

    # Supplement conversation title matches & exact literal message hits (excluding failed/cancelled)
    if "chat" in target_sources and len(chats_out) < limit:
        pattern = f"%{_escape_like(term)}%"
        try:
            title_rows = (
                await db.execute(
                    select(Conversation)
                    .where(
                        Conversation.user_id == user.id,
                        Conversation.title.ilike(pattern, escape="\\"),
                    )
                    .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.updated_at.desc())
                    .limit(max(4, limit // 2))
                )
            ).scalars().all()
            for conv in title_rows:
                ckey = f"{conv.id}:title"
                if ckey in seen_chat_keys:
                    continue
                seen_chat_keys.add(ckey)
                chats_out.append(
                    {
                        "type": "chat",
                        "match_in": "title",
                        "conversation_id": str(conv.id),
                        "conversation_kind": "main" if conv.kind == "main" else "side",
                        "conversation_title": assistant_label if conv.kind == "main" else conv.title,
                        "message_id": None,
                        "role": None,
                        "snippet": conv.title,
                        "score": 0.65,
                        "confidence": "high",
                        "created_at": (conv.last_message_at or conv.updated_at).isoformat()
                        if (conv.last_message_at or conv.updated_at)
                        else None,
                    }
                )
                if len(chats_out) >= limit:
                    break
        except Exception:
            pass

    if "chat" in target_sources and len(chats_out) < limit:
        pattern = f"%{_escape_like(term)}%"
        try:
            msg_rows = (
                await db.execute(
                    select(Message, Conversation.title, Conversation.kind)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .where(
                        Conversation.user_id == user.id,
                        Message.role.in_(("user", "assistant")),
                        Message.status.notin_(("failed", "cancelled")),
                        Message.content.ilike(pattern, escape="\\"),
                    )
                    .order_by(Message.created_at.desc())
                    .limit(limit)
                )
            ).all()
            for msg, c_title, c_kind in msg_rows:
                ckey = f"{msg.conversation_id}:{msg.id}"
                if ckey in seen_chat_keys:
                    continue
                seen_chat_keys.add(ckey)
                chats_out.append(
                    {
                        "type": "chat",
                        "match_in": "message",
                        "conversation_id": str(msg.conversation_id),
                        "conversation_kind": "main" if c_kind == "main" else "side",
                        "conversation_title": assistant_label if c_kind == "main" else c_title,
                        "message_id": str(msg.id),
                        "role": msg.role,
                        "snippet": _build_snippet(msg.content, term),
                        "score": 0.5,
                        "confidence": "medium",
                        "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    }
                )
                if len(chats_out) >= limit:
                    break
        except Exception:
            pass

    return {
        "query": term,
        "files": files_out[:limit],
        "memories": memories_out[:limit],
        "chats": chats_out[:limit],
        "total": len(files_out[:limit]) + len(memories_out[:limit]) + len(chats_out[:limit]),
        "diagnostics": diag.to_dict(),
    }

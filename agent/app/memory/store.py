from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.embeddings import Embeddings

from app.core.models import EmbeddingClient

logger = logging.getLogger("whitz.agent.memory")

MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375


def memory_namespace(agent_namespace: str) -> tuple[str, str, str]:
    ns = (agent_namespace or "").strip()
    if not ns:
        raise ValueError("agent_namespace must be non-empty")
    return ("users", ns, "memories")


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _deterministic_key(target: str, content: str) -> str:
    digest = hashlib.sha256(f"{target}\n{content.strip()}".encode("utf-8")).hexdigest()[:16]
    return f"{target}_{digest}"


def _sanitize_entry(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    return re.sub(r"(?m)^\s*§\s*$", "-", text).strip()


class WhitzEmbeddings(Embeddings):
    """LangChain Embeddings adapter backed by EmbeddingClient."""

    def __init__(self, client: EmbeddingClient | None = None) -> None:
        self.client = client or EmbeddingClient()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = asyncio.run(self.client.embed_texts(texts))
        return vecs or []

    def embed_query(self, text: str) -> list[float]:
        vec = asyncio.run(self.client.embed_query(text))
        return vec or []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = await self.client.embed_texts(texts)
        return vecs or []

    async def aembed_query(self, text: str) -> list[float]:
        vec = await self.client.embed_query(text)
        return vec or []


class MemoryManager:
    """Single-source-of-truth long-term memory manager backed by PostgreSQL ``memory_entries``.

    Eliminates split-brain ghost memories between ``AsyncPostgresStore`` and ``memory_entries``.
    Supports optional ``store`` injection only as a fallback for isolated unit tests.
    """

    def __init__(
        self,
        *,
        store: Any = None,
        pool: Any = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.store = store
        self.pool = pool
        self.embedding_client = embedding_client or EmbeddingClient()

    async def search(
        self,
        *,
        user_id: str,
        agent_namespace: str,
        query: str,
        memory_enabled: bool = True,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if not memory_enabled:
            return []
        cleaned_query = (query or "").strip()
        results: list[dict[str, Any]] = []
        seen_contents: set[str] = set()

        # 1. Primary source of truth: PostgreSQL memory_entries (synced with Settings UI edits/deletes)
        if self.pool is not None:
            try:
                pg_rows = await self._search_pg_entries(
                    user_id=user_id,
                    query=cleaned_query,
                    limit=limit,
                )
                for row in pg_rows:
                    content = str(row.get("content") or "").strip()
                    if not content or content in seen_contents:
                        continue
                    seen_contents.add(content)
                    results.append(row)
                    if len(results) >= limit:
                        break
            except Exception as exc:
                logger.warning("PG memory_entries query failed: %s", exc)

        # 2. Optional test-store fallback only when explicitly injected & namespace is valid
        if self.store is not None and not results and (agent_namespace or "").strip():
            ns = memory_namespace(agent_namespace)
            try:
                if cleaned_query:
                    items = await self.store.asearch(ns, query=cleaned_query, limit=limit)
                else:
                    items = await self.store.asearch(ns, limit=limit)
                for item in items:
                    val = item.value if hasattr(item, "value") else {}
                    content = str(val.get("content") or "").strip()
                    if not content or content in seen_contents:
                        continue
                    seen_contents.add(content)
                    results.append(
                        {
                            "id": str(getattr(item, "key", "")),
                            "target": str(val.get("target") or "memory"),
                            "content": content,
                            "source": str(val.get("source") or "agent"),
                            "score": getattr(item, "score", None),
                        }
                    )
            except Exception as exc:
                logger.warning("Fallback store search failed: %s", exc)

        return results[:limit]

    async def _search_pg_entries(
        self,
        *,
        user_id: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            return []
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return []

        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                if query:
                    q_vec = await self.embedding_client.embed_query(query) if self.embedding_client.is_configured else None
                    like_pat = f"%{_escape_like(query)}%"
                    if q_vec:
                        vec_lit = _vector_literal(q_vec)
                        try:
                            try:
                                await cur.execute("SET hnsw.iterative_scan = relaxed_order")
                            except Exception:
                                pass
                            await cur.execute(
                                """
                                SELECT id, target, content, source,
                                       CASE WHEN embedding IS NOT NULL
                                            THEN 1.0 - (embedding <=> %s::vector)
                                            ELSE NULL END AS score
                                FROM memory_entries
                                WHERE user_id = %s
                                  AND (
                                      content ILIKE %s ESCAPE '\\'
                                      OR (embedding IS NOT NULL AND (embedding <=> %s::vector) < 0.72)
                                  )
                                ORDER BY
                                    CASE WHEN content ILIKE %s ESCAPE '\\' THEN 0 ELSE 1 END,
                                    embedding <=> %s::vector NULLS LAST,
                                    updated_at DESC
                                LIMIT %s
                                """,
                                (vec_lit, user_uuid, like_pat, vec_lit, like_pat, vec_lit, limit),
                            )
                            rows = await cur.fetchall()
                        except Exception:
                            rows = []
                    else:
                        rows = []

                    if not rows:
                        # pg_trgm CJK similarity fallback -> escaped ILIKE fallback
                        try:
                            await cur.execute(
                                """
                                SELECT id, target, content, source, word_similarity(%s, content) AS score
                                FROM memory_entries
                                WHERE user_id = %s
                                  AND (content ILIKE %s ESCAPE '\\' OR word_similarity(%s, content) >= 0.16)
                                ORDER BY word_similarity(%s, content) DESC, updated_at DESC
                                LIMIT %s
                                """,
                                (query, user_uuid, like_pat, query, query, limit),
                            )
                            rows = await cur.fetchall()
                        except Exception:
                            await cur.execute(
                                """
                                SELECT id, target, content, source, NULL AS score
                                FROM memory_entries
                                WHERE user_id = %s AND content ILIKE %s ESCAPE '\\'
                                ORDER BY updated_at DESC
                                LIMIT %s
                                """,
                                (user_uuid, like_pat, limit),
                            )
                            rows = await cur.fetchall()
                else:
                    await cur.execute(
                        """
                        SELECT id, target, content, source, NULL AS score
                        FROM memory_entries
                        WHERE user_id = %s
                        ORDER BY updated_at DESC
                        LIMIT %s
                        """,
                        (user_uuid, limit),
                    )
                    rows = await cur.fetchall()

        return [
            {
                "id": str(r[0]),
                "target": str(r[1]),
                "content": str(r[2]),
                "source": str(r[3]),
                "score": float(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ]

    async def propose(
        self,
        *,
        user_id: str,
        agent_namespace: str,
        conversation_id: str | None,
        target: str,
        action: str,
        content: str,
        old_content: str | None = None,
        memory_enabled: bool = True,
        memory_require_confirm: bool = False,
    ) -> dict[str, Any]:
        if not memory_enabled:
            return {
                "status": "disabled",
                "message": "用户未开启长期记忆功能，未写入或暂存任何记忆。",
            }

        norm_target = "user" if str(target).strip().lower() in ("user", "user.md", "profile") else "memory"
        norm_action = str(action or "add").strip().lower()
        if norm_action not in ("add", "replace", "remove"):
            norm_action = "add"
        cleaned_content = _sanitize_entry(content)
        cleaned_old = _sanitize_entry(old_content or "") or None
        if norm_action != "remove" and not cleaned_content:
            return {"status": "rejected", "message": "记忆内容不能为空。"}

        char_cap = USER_CHAR_LIMIT if norm_target == "user" else MEMORY_CHAR_LIMIT
        if len(cleaned_content) > char_cap:
            cleaned_content = cleaned_content[:char_cap].rstrip()

        if memory_require_confirm:
            proposal_id = await self._stage_pending_proposal(
                user_id=user_id,
                conversation_id=conversation_id,
                target=norm_target,
                action=norm_action,
                content=cleaned_content,
                old_content=cleaned_old,
            )
            return {
                "status": "pending_confirmation",
                "proposal_id": proposal_id,
                "target": norm_target,
                "action": norm_action,
                "content": cleaned_content,
                "message": "已提交记忆提案，等待用户在界面中确认后生效。",
            }

        entry_id = await self._commit_direct(
            user_id=user_id,
            agent_namespace=agent_namespace,
            target=norm_target,
            action=norm_action,
            content=cleaned_content,
            old_content=cleaned_old,
        )
        return {
            "status": "saved",
            "entry_id": entry_id,
            "target": norm_target,
            "action": norm_action,
            "content": cleaned_content,
            "message": "记忆已保存。",
        }

    async def _stage_pending_proposal(
        self,
        *,
        user_id: str,
        conversation_id: str | None,
        target: str,
        action: str,
        content: str,
        old_content: str | None,
    ) -> str:
        proposal_id = str(uuid.uuid4())
        if self.pool is None:
            return proposal_id

        user_uuid = uuid.UUID(str(user_id))
        conv_uuid = uuid.UUID(str(conversation_id)) if conversation_id else None
        now = datetime.now(timezone.utc)
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO memory_pending_proposals
                        (id, user_id, conversation_id, target, action, content, old_content, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                    """,
                    (
                        uuid.UUID(proposal_id),
                        user_uuid,
                        conv_uuid,
                        target,
                        action,
                        content,
                        old_content,
                        now,
                    ),
                )
        return proposal_id

    async def _commit_direct(
        self,
        *,
        user_id: str,
        agent_namespace: str,
        target: str,
        action: str,
        content: str,
        old_content: str | None,
    ) -> str:
        key = _deterministic_key(target, content or old_content or "")
        now = datetime.now(timezone.utc)
        if self.store is not None and (agent_namespace or "").strip():
            ns = memory_namespace(agent_namespace)
            try:
                if action == "remove":
                    old_key = _deterministic_key(target, old_content or content)
                    await self.store.adelete(ns, old_key)
                else:
                    if action == "replace" and old_content:
                        await self.store.adelete(ns, _deterministic_key(target, old_content))
                    await self.store.aput(
                        ns,
                        key,
                        {
                            "target": target,
                            "content": content,
                            "source": "agent",
                            "updated_at": now.isoformat(),
                        },
                    )
            except Exception as exc:
                logger.warning("Fallback store direct write failed: %s", exc)

        entry_id = str(uuid.uuid4())
        if self.pool is not None:
            user_uuid = uuid.UUID(str(user_id))
            vec = (
                await self.embedding_client.embed_query(content)
                if action != "remove" and self.embedding_client.is_configured
                else None
            )
            async with self.pool.connection() as conn:
                async def _apply(cur: Any) -> None:
                    if action == "remove":
                        target_text = old_content or content
                        await cur.execute(
                            "DELETE FROM memory_entries WHERE user_id = %s AND target = %s AND content = %s",
                            (user_uuid, target, target_text),
                        )
                        return
                    if action == "replace" and old_content:
                        await cur.execute(
                            "DELETE FROM memory_entries WHERE user_id = %s AND target = %s AND content = %s",
                            (user_uuid, target, old_content),
                        )
                    # Deduplicate identical content before inserting
                    await cur.execute(
                        "SELECT id FROM memory_entries WHERE user_id = %s AND target = %s AND content = %s LIMIT 1",
                        (user_uuid, target, content),
                    )
                    if await cur.fetchone():
                        return
                    if vec:
                        vec_lit = _vector_literal(vec)
                        await cur.execute(
                            """
                            INSERT INTO memory_entries
                                (id, user_id, target, content, source, embedding, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, 'agent', %s::vector, %s, %s)
                            """,
                            (uuid.UUID(entry_id), user_uuid, target, content, vec_lit, now, now),
                        )
                    else:
                        await cur.execute(
                            """
                            INSERT INTO memory_entries
                                (id, user_id, target, content, source, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, 'agent', %s, %s)
                            """,
                            (uuid.UUID(entry_id), user_uuid, target, content, now, now),
                        )

                # Use explicit transaction when psycopg connection supports it (safe even with autocommit=True)
                if hasattr(conn, "transaction"):
                    async with conn.transaction():
                        async with conn.cursor() as cur:
                            await _apply(cur)
                else:
                    async with conn.cursor() as cur:
                        await _apply(cur)
        return entry_id

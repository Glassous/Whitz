from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from langchain_core.embeddings import Embeddings

from app.core.models import EmbeddingClient, RerankClient

logger = logging.getLogger("whitz.agent.memory")

MEMORY_CHAR_LIMIT = 12000
USER_CHAR_LIMIT = 8000
PROJECTS_CHAR_LIMIT = 16000
DEFAULT_COLLECTION_CHAR_LIMIT = 12000
DEFAULT_COLLECTION_MAX_ENTRIES = 200
MIN_COLLECTION_CHAR_LIMIT = 2000
MAX_COLLECTION_CHAR_LIMIT = 50000
MAX_COLLECTIONS_PER_USER = 50

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
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9_-]+")
_TRGM_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def memory_namespace(agent_namespace: str) -> tuple[str, str, str]:
    ns = (agent_namespace or "").strip()
    if not ns:
        raise ValueError("agent_namespace must be non-empty")
    return ("users", ns, "memories")


def normalize_collection_slug(raw: str | None, *, fallback_name: str | None = None) -> str:
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


def _vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"


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


def _char_trigrams(text: str) -> set[str]:
    compact = " ".join(_TRGM_TOKEN_RE.findall((text or "").lower()))
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[i : i + 3] for i in range(len(compact) - 2)}


def _jaccard_sim(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / float(len(a) + len(b) - inter)


def _rrf_fuse_memories(
    ranked_lists: Sequence[Sequence[dict[str, Any]]],
    *,
    weights: Sequence[float] = (1.3, 0.95, 0.9),
    rrf_k: int = 60,
    top_k: int = 24,
) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    records: dict[str, dict[str, Any]] = {}
    for leg_idx, rows in enumerate(ranked_lists):
        w = float(weights[leg_idx]) if leg_idx < len(weights) else 1.0
        for rank_0, row in enumerate(rows):
            eid = str(row.get("id") or "")
            if not eid:
                continue
            scores[eid] = scores.get(eid, 0.0) + w / (rrf_k + rank_0 + 1)
            if eid not in records:
                records[eid] = dict(row)
    ordered = sorted(scores.keys(), key=lambda eid: scores[eid], reverse=True)[:top_k]
    return [{**records[eid], "score": round(scores[eid], 6)} for eid in ordered]


def _mmr_select_memories(
    candidates: Sequence[dict[str, Any]],
    *,
    limit: int = 8,
    lambda_mult: float = 0.75,
) -> list[dict[str, Any]]:
    if len(candidates) <= 1 or limit <= 0:
        return list(candidates[:limit])

    def _rel(item: dict[str, Any]) -> float:
        if item.get("rerank_score") is not None:
            return float(item["rerank_score"])
        return float(item.get("score") or 0.0)

    max_score = max((_rel(c) for c in candidates), default=1.0) or 1.0
    trigrams = [_char_trigrams(f"{c.get('title') or ''} {c.get('content') or ''}"[:600]) for c in candidates]
    selected: list[int] = []
    remaining = list(range(len(candidates)))

    while remaining and len(selected) < limit:
        best_idx = -1
        best_val = -1e9
        for idx in remaining:
            rel = _rel(candidates[idx]) / max_score if max_score > 0 else 0.0
            redundancy = max((_jaccard_sim(trigrams[idx], trigrams[s]) for s in selected), default=0.0)
            mmr_score = lambda_mult * rel - (1.0 - lambda_mult) * redundancy
            if mmr_score > best_val:
                best_val = mmr_score
                best_idx = idx
        if best_idx < 0:
            best_idx = remaining[0]
        selected.append(best_idx)
        remaining.remove(best_idx)
    return [candidates[i] for i in selected]


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
    """Single-source-of-truth multi-collection long-term memory manager backed by PostgreSQL + Hybrid RAG.

    Supports:
    - Multi-collection organization (`memory_collections` + `memory_entries`)
    - 3-leg Hybrid RAG recall (pgvector HNSW + PostgreSQL FTS + pg_trgm CJK) -> RRF -> Rerank -> MMR
    - Optional `store` injection as a lightweight fallback for isolated unit tests
    """

    def __init__(
        self,
        *,
        store: Any = None,
        pool: Any = None,
        embedding_client: EmbeddingClient | None = None,
        rerank_client: RerankClient | None = None,
    ) -> None:
        self.store = store
        self.pool = pool
        self.embedding_client = embedding_client or EmbeddingClient()
        self.rerank_client = rerank_client

    async def _ensure_default_collections_pg(self, cur: Any, user_uuid: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        for spec in SYSTEM_COLLECTIONS:
            try:
                await cur.execute(
                    """
                    INSERT INTO memory_collections
                        (id, user_id, slug, name, description, kind, enabled, char_limit, max_entries, sort_order, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'system', true, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, slug) DO NOTHING
                    """,
                    (
                        uuid.uuid4(),
                        user_uuid,
                        spec["slug"],
                        spec["name"],
                        spec["description"],
                        spec["char_limit"],
                        spec["max_entries"],
                        spec["sort_order"],
                        now,
                        now,
                    ),
                )
            except Exception as exc:
                logger.debug("ensure_default_collections_pg skipped for %s: %s", spec["slug"], exc)

    async def _resolve_or_create_collection_pg(
        self,
        cur: Any,
        user_uuid: uuid.UUID,
        slug: str,
        *,
        auto_create: bool = True,
        name: str | None = None,
        description: str | None = None,
    ) -> tuple[uuid.UUID | None, str, str, int, int]:
        """Return (collection_id, slug, name, char_limit, max_entries) or fallback when table unavailable."""
        await self._ensure_default_collections_pg(cur, user_uuid)
        try:
            await cur.execute(
                """
                SELECT id, slug, name, char_limit, max_entries
                FROM memory_collections
                WHERE user_id = %s AND slug = %s
                LIMIT 1
                """,
                (user_uuid, slug),
            )
            row = await cur.fetchone()
            if row:
                return row[0], str(row[1]), str(row[2]), int(row[3] or DEFAULT_COLLECTION_CHAR_LIMIT), int(row[4] or DEFAULT_COLLECTION_MAX_ENTRIES)

            if not auto_create:
                return None, slug, name or slug, DEFAULT_COLLECTION_CHAR_LIMIT, DEFAULT_COLLECTION_MAX_ENTRIES

            await cur.execute("SELECT COUNT(*) FROM memory_collections WHERE user_id = %s", (user_uuid,))
            cnt_row = await cur.fetchone()
            existing_count = int(cnt_row[0] or 0) if cnt_row else 0
            if existing_count >= MAX_COLLECTIONS_PER_USER:
                # Fallback to 'memory' collection if user hit max collections cap
                await cur.execute(
                    "SELECT id, slug, name, char_limit, max_entries FROM memory_collections WHERE user_id = %s AND slug = 'memory' LIMIT 1",
                    (user_uuid,),
                )
                fb = await cur.fetchone()
                if fb:
                    return fb[0], str(fb[1]), str(fb[2]), int(fb[3] or MEMORY_CHAR_LIMIT), int(fb[4] or DEFAULT_COLLECTION_MAX_ENTRIES)

            new_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            col_name = (name or slug).strip()[:80] or slug
            col_desc = (description or "").strip()[:300]
            await cur.execute(
                """
                INSERT INTO memory_collections
                    (id, user_id, slug, name, description, kind, enabled, char_limit, max_entries, sort_order, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'custom', true, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, slug) DO NOTHING
                """,
                (
                    new_id,
                    user_uuid,
                    slug,
                    col_name,
                    col_desc,
                    DEFAULT_COLLECTION_CHAR_LIMIT,
                    DEFAULT_COLLECTION_MAX_ENTRIES,
                    100 + existing_count,
                    now,
                    now,
                ),
            )
            await cur.execute(
                "SELECT id, slug, name, char_limit, max_entries FROM memory_collections WHERE user_id = %s AND slug = %s LIMIT 1",
                (user_uuid, slug),
            )
            created = await cur.fetchone()
            if created:
                return created[0], str(created[1]), str(created[2]), int(created[3] or DEFAULT_COLLECTION_CHAR_LIMIT), int(created[4] or DEFAULT_COLLECTION_MAX_ENTRIES)
        except Exception as exc:
            logger.debug("Collection resolution fallback: %s", exc)
        return None, slug, name or slug, DEFAULT_COLLECTION_CHAR_LIMIT, DEFAULT_COLLECTION_MAX_ENTRIES

    async def list_collections(self, *, user_id: str) -> list[dict[str, Any]]:
        if self.pool is None:
            return [
                {
                    "slug": spec["slug"],
                    "name": spec["name"],
                    "description": spec["description"],
                    "kind": "system",
                    "enabled": True,
                    "entry_count": 0,
                    "char_count": 0,
                    "char_limit": spec["char_limit"],
                }
                for spec in SYSTEM_COLLECTIONS
            ]
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return []

        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await self._ensure_default_collections_pg(cur, user_uuid)
                await cur.execute(
                    """
                    SELECT mc.id, mc.slug, mc.name, mc.description, mc.kind, mc.enabled,
                           mc.char_limit, mc.max_entries,
                           COUNT(me.id) AS entry_count,
                           COALESCE(SUM(LENGTH(me.content)), 0) AS char_count
                    FROM memory_collections mc
                    LEFT JOIN memory_entries me
                      ON me.user_id = mc.user_id
                     AND (me.collection_id = mc.id OR (me.collection_id IS NULL AND me.target = mc.slug))
                    WHERE mc.user_id = %s
                    GROUP BY mc.id
                    ORDER BY mc.sort_order ASC, mc.created_at ASC
                    """,
                    (user_uuid,),
                )
                rows = await cur.fetchall()
        return [
            {
                "id": str(r[0]),
                "slug": str(r[1]),
                "name": str(r[2]),
                "description": str(r[3] or ""),
                "kind": str(r[4] or "custom"),
                "enabled": bool(r[5]),
                "char_limit": int(r[6] or DEFAULT_COLLECTION_CHAR_LIMIT),
                "max_entries": int(r[7] or DEFAULT_COLLECTION_MAX_ENTRIES),
                "entry_count": int(r[8] or 0),
                "char_count": int(r[9] or 0),
            }
            for r in rows
        ]

    async def list_entries(
        self,
        *,
        user_id: str,
        agent_namespace: str = "",
        collection: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        norm_col = normalize_collection_slug(collection) if collection else None
        if self.pool is not None:
            try:
                user_uuid = uuid.UUID(str(user_id))
                async with self.pool.connection() as conn:
                    async with conn.cursor() as cur:
                        if norm_col:
                            await cur.execute(
                                """
                                SELECT me.id, me.target, COALESCE(mc.name, me.target), COALESCE(me.title, ''),
                                       me.content, COALESCE(me.tags, '[]'::jsonb), me.source
                                FROM memory_entries me
                                LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                                WHERE me.user_id = %s AND (mc.slug = %s OR me.target = %s)
                                ORDER BY me.updated_at DESC, me.created_at DESC
                                LIMIT %s
                                """,
                                (user_uuid, norm_col, norm_col, limit),
                            )
                        else:
                            await cur.execute(
                                """
                                SELECT me.id, me.target, COALESCE(mc.name, me.target), COALESCE(me.title, ''),
                                       me.content, COALESCE(me.tags, '[]'::jsonb), me.source
                                FROM memory_entries me
                                LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                                WHERE me.user_id = %s
                                ORDER BY me.updated_at DESC, me.created_at DESC
                                LIMIT %s
                                """,
                                (user_uuid, limit),
                            )
                        rows = await cur.fetchall()
                return [
                    {
                        "id": str(r[0]),
                        "collection": str(r[1]),
                        "target": str(r[1]),
                        "collection_name": str(r[2] or r[1]),
                        "title": str(r[3] or ""),
                        "content": str(r[4]),
                        "tags": list(r[5]) if isinstance(r[5], list) else [],
                        "source": str(r[6] or "agent"),
                    }
                    for r in rows
                ]
            except Exception as exc:
                logger.warning("PG list_entries failed: %s", exc)

        if self.store is not None and (agent_namespace or "").strip():
            ns = memory_namespace(agent_namespace)
            items = await self.store.asearch(ns, limit=limit * 2)
            out: list[dict[str, Any]] = []
            for item in items:
                val = item.value if hasattr(item, "value") else {}
                tgt = str(val.get("target") or "memory")
                if norm_col and tgt != norm_col:
                    continue
                out.append(
                    {
                        "id": str(getattr(item, "key", "")),
                        "collection": tgt,
                        "target": tgt,
                        "collection_name": str(val.get("collection_name") or tgt),
                        "title": str(val.get("title") or ""),
                        "content": str(val.get("content") or ""),
                        "tags": list(val.get("tags") or []),
                        "source": str(val.get("source") or "agent"),
                    }
                )
                if len(out) >= limit:
                    break
            return out
        return []

    async def manage_collection(
        self,
        *,
        user_id: str,
        action: str,
        slug: str,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        char_limit: int | None = None,
    ) -> dict[str, Any]:
        op = (action or "").strip().lower()
        if op not in ("create", "update", "delete"):
            return {"status": "rejected", "message": f"不支持的记忆集操作: {action}"}

        norm_slug = normalize_collection_slug(slug, fallback_name=name)
        if self.pool is None:
            return {
                "status": "ok",
                "action": op,
                "slug": norm_slug,
                "name": (name or norm_slug).strip(),
                "message": f"已执行记忆集操作 ({op}: {norm_slug})。",
            }

        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return {"status": "rejected", "message": "无效的用户 ID。"}

        now = datetime.now(timezone.utc)
        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                await self._ensure_default_collections_pg(cur, user_uuid)

                if op == "create":
                    await cur.execute(
                        "SELECT id, name FROM memory_collections WHERE user_id = %s AND slug = %s LIMIT 1",
                        (user_uuid, norm_slug),
                    )
                    existing = await cur.fetchone()
                    if existing:
                        return {
                            "status": "exists",
                            "collection_id": str(existing[0]),
                            "slug": norm_slug,
                            "name": str(existing[1]),
                            "message": f"记忆集 '{norm_slug}' 已存在，可直接写入。",
                        }
                    await cur.execute("SELECT COUNT(*) FROM memory_collections WHERE user_id = %s", (user_uuid,))
                    cnt_row = await cur.fetchone()
                    cnt = int(cnt_row[0] or 0) if cnt_row else 0
                    if cnt >= MAX_COLLECTIONS_PER_USER:
                        return {"status": "rejected", "message": f"记忆集数量已达上限（最多 {MAX_COLLECTIONS_PER_USER} 个）。"}
                    col_id = uuid.uuid4()
                    col_name = (name or norm_slug).strip()[:80]
                    col_desc = (description or "").strip()[:300]
                    bounded_limit = max(
                        MIN_COLLECTION_CHAR_LIMIT,
                        min(int(char_limit or DEFAULT_COLLECTION_CHAR_LIMIT), MAX_COLLECTION_CHAR_LIMIT),
                    )
                    await cur.execute(
                        """
                        INSERT INTO memory_collections
                            (id, user_id, slug, name, description, kind, enabled, char_limit, max_entries, sort_order, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, 'custom', %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            col_id,
                            user_uuid,
                            norm_slug,
                            col_name,
                            col_desc,
                            True if enabled is None else bool(enabled),
                            bounded_limit,
                            DEFAULT_COLLECTION_MAX_ENTRIES,
                            100 + cnt,
                            now,
                            now,
                        ),
                    )
                    return {
                        "status": "created",
                        "collection_id": str(col_id),
                        "slug": norm_slug,
                        "name": col_name,
                        "description": col_desc,
                        "message": f"已创建记忆集「{col_name}」({norm_slug})。",
                    }

                if op == "update":
                    await cur.execute(
                        "SELECT id, name, description, enabled, char_limit FROM memory_collections WHERE user_id = %s AND slug = %s LIMIT 1",
                        (user_uuid, norm_slug),
                    )
                    existing = await cur.fetchone()
                    if not existing:
                        return {"status": "not_found", "message": f"记忆集 '{norm_slug}' 不存在。"}
                    next_name = (name.strip()[:80] if name and name.strip() else str(existing[1]))
                    next_desc = (description.strip()[:300] if description is not None else str(existing[2] or ""))
                    next_enabled = bool(enabled) if enabled is not None else bool(existing[3])
                    next_limit = (
                        max(MIN_COLLECTION_CHAR_LIMIT, min(int(char_limit), MAX_COLLECTION_CHAR_LIMIT))
                        if char_limit is not None
                        else int(existing[4] or DEFAULT_COLLECTION_CHAR_LIMIT)
                    )
                    await cur.execute(
                        """
                        UPDATE memory_collections
                        SET name = %s, description = %s, enabled = %s, char_limit = %s, updated_at = %s
                        WHERE id = %s
                        """,
                        (next_name, next_desc, next_enabled, next_limit, now, existing[0]),
                    )
                    return {
                        "status": "updated",
                        "collection_id": str(existing[0]),
                        "slug": norm_slug,
                        "name": next_name,
                        "description": next_desc,
                        "enabled": next_enabled,
                        "message": f"已更新记忆集「{next_name}」({norm_slug})。",
                    }

                # op == "delete"
                await cur.execute(
                    "SELECT id, kind, name FROM memory_collections WHERE user_id = %s AND slug = %s LIMIT 1",
                    (user_uuid, norm_slug),
                )
                existing = await cur.fetchone()
                if not existing:
                    return {"status": "not_found", "message": f"记忆集 '{norm_slug}' 不存在。"}
                if str(existing[1]) == "system" or norm_slug in _SYSTEM_BY_SLUG:
                    return {"status": "rejected", "message": f"系统预置记忆集 '{norm_slug}' 不可删除。"}
                await cur.execute("DELETE FROM memory_collections WHERE id = %s", (existing[0],))
                return {
                    "status": "deleted",
                    "slug": norm_slug,
                    "message": f"已删除记忆集「{existing[2]}」({norm_slug})。",
                }

    async def search(
        self,
        *,
        user_id: str,
        agent_namespace: str,
        query: str,
        memory_enabled: bool = True,
        collection: str | None = None,
        tags: list[str] | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        if not memory_enabled:
            return []
        cleaned_query = (query or "").strip()
        norm_col = normalize_collection_slug(collection) if collection else None
        norm_tags = [t.lower() for t in _sanitize_tags(tags)]
        results: list[dict[str, Any]] = []
        seen_contents: set[str] = set()

        # 1. Primary source of truth: PostgreSQL memory_entries + Hybrid RAG
        if self.pool is not None:
            try:
                pg_rows = await self._search_pg_entries(
                    user_id=user_id,
                    query=cleaned_query,
                    collection=norm_col,
                    limit=limit,
                )
                for row in pg_rows:
                    content = str(row.get("content") or "").strip()
                    if not content or content in seen_contents:
                        continue
                    if norm_tags:
                        row_tags = {str(t).lower() for t in (row.get("tags") or [])}
                        if not row_tags.intersection(norm_tags):
                            continue
                    seen_contents.add(content)
                    results.append(row)
                    if len(results) >= limit:
                        break
            except Exception as exc:
                logger.warning("PG memory_entries hybrid search failed: %s", exc)

        # 2. Optional test-store fallback when explicitly injected & namespace is valid
        if self.store is not None and not results and (agent_namespace or "").strip():
            ns = memory_namespace(agent_namespace)
            try:
                if cleaned_query:
                    items = await self.store.asearch(ns, query=cleaned_query, limit=limit * 2)
                else:
                    items = await self.store.asearch(ns, limit=limit * 2)
                for item in items:
                    val = item.value if hasattr(item, "value") else {}
                    tgt = str(val.get("target") or "memory")
                    if norm_col and tgt != norm_col:
                        continue
                    content = str(val.get("content") or "").strip()
                    if not content or content in seen_contents:
                        continue
                    if norm_tags:
                        row_tags = {str(t).lower() for t in (val.get("tags") or [])}
                        if not row_tags.intersection(norm_tags):
                            continue
                    seen_contents.add(content)
                    results.append(
                        {
                            "id": str(getattr(item, "key", "")),
                            "collection": tgt,
                            "target": tgt,
                            "collection_name": str(val.get("collection_name") or tgt),
                            "title": str(val.get("title") or ""),
                            "content": content,
                            "tags": list(val.get("tags") or []),
                            "source": str(val.get("source") or "agent"),
                            "score": getattr(item, "score", None),
                        }
                    )
                    if len(results) >= limit:
                        break
            except Exception as exc:
                logger.warning("Fallback store search failed: %s", exc)

        return results[:limit]

    async def _search_pg_entries(
        self,
        *,
        user_id: str,
        query: str,
        collection: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            return []
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return []

        pool_limit = max(limit * 3, 24)
        col_sql = (
            "AND (mc.slug = %s OR (me.collection_id IS NULL AND me.target = %s))"
            if collection
            else "AND (mc.enabled IS NULL OR mc.enabled = true)"
        )
        col_params: tuple[Any, ...] = (collection, collection) if collection else ()

        def _row_to_dict(r: Any) -> dict[str, Any]:
            slug = str(r[1] or "memory")
            return {
                "id": str(r[0]),
                "collection": slug,
                "target": slug,
                "collection_name": str(r[2] or slug),
                "title": str(r[3] or ""),
                "content": str(r[4] or ""),
                "tags": list(r[5]) if isinstance(r[5], list) else [],
                "source": str(r[6] or "agent"),
                "score": float(r[7]) if len(r) > 7 and r[7] is not None else None,
            }

        async with self.pool.connection() as conn:
            async with conn.cursor() as cur:
                if not query:
                    await cur.execute(
                        f"""
                        SELECT me.id, me.target, COALESCE(mc.name, me.target), COALESCE(me.title, ''),
                               me.content, COALESCE(me.tags, '[]'::jsonb), me.source, NULL AS score
                        FROM memory_entries me
                        LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                        WHERE me.user_id = %s
                          {col_sql}
                        ORDER BY me.updated_at DESC
                        LIMIT %s
                        """,
                        (user_uuid, *col_params, limit),
                    )
                    rows = await cur.fetchall()
                    return [_row_to_dict(r) for r in rows]

                like_pat = f"%{_escape_like(query)}%"
                vec_rows: list[dict[str, Any]] = []
                fts_rows: list[dict[str, Any]] = []
                trgm_rows: list[dict[str, Any]] = []

                # Leg 1: pgvector HNSW (filtered by current embedding_model tag to prevent cross-model score corruption)
                q_vec = await self.embedding_client.embed_query(query) if self.embedding_client.is_configured else None
                if q_vec:
                    vec_lit = _vector_literal(q_vec)
                    m_tag = getattr(self.embedding_client, "model_tag", "") or ""
                    model_filter_sql = "AND (me.embedding_model IS NULL OR me.embedding_model = %s)" if m_tag else ""
                    model_params = (m_tag,) if m_tag else ()
                    try:
                        await cur.execute(
                            f"""
                            SELECT me.id, me.target, COALESCE(mc.name, me.target), COALESCE(me.title, ''),
                                   me.content, COALESCE(me.tags, '[]'::jsonb), me.source,
                                   1.0 - (me.embedding <=> %s::vector) AS score
                            FROM memory_entries me
                            LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                            WHERE me.user_id = %s
                              {col_sql}
                              AND me.embedding IS NOT NULL
                              {model_filter_sql}
                              AND (me.embedding <=> %s::vector) < 0.72
                            ORDER BY me.embedding <=> %s::vector ASC, me.updated_at DESC
                            LIMIT %s
                            """,
                            (vec_lit, user_uuid, *col_params, *model_params, vec_lit, vec_lit, pool_limit),
                        )
                        vec_rows = [_row_to_dict(r) for r in await cur.fetchall()]
                    except Exception as exc:
                        logger.debug("Memory vector leg skipped: %s", exc)

                # Leg 2: PostgreSQL FTS (search_tsv)
                try:
                    await cur.execute(
                        f"""
                        SELECT me.id, me.target, COALESCE(mc.name, me.target), COALESCE(me.title, ''),
                               me.content, COALESCE(me.tags, '[]'::jsonb), me.source,
                               ts_rank_cd(me.search_tsv, plainto_tsquery('simple', %s)) AS score
                        FROM memory_entries me
                        LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                        WHERE me.user_id = %s
                          {col_sql}
                          AND me.search_tsv @@ plainto_tsquery('simple', %s)
                        ORDER BY score DESC, me.updated_at DESC
                        LIMIT %s
                        """,
                        (query, user_uuid, *col_params, query, pool_limit),
                    )
                    fts_rows = [_row_to_dict(r) for r in await cur.fetchall()]
                except Exception as exc:
                    logger.debug("Memory FTS leg skipped: %s", exc)

                # Leg 3: pg_trgm CJK similarity + ILIKE fallback
                try:
                    await cur.execute(
                        f"""
                        SELECT me.id, me.target, COALESCE(mc.name, me.target), COALESCE(me.title, ''),
                               me.content, COALESCE(me.tags, '[]'::jsonb), me.source,
                               word_similarity(%s, COALESCE(me.title, '') || ' ' || me.content) AS score
                        FROM memory_entries me
                        LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                        WHERE me.user_id = %s
                          {col_sql}
                          AND (
                              me.content ILIKE %s ESCAPE '\\'
                              OR me.title ILIKE %s ESCAPE '\\'
                              OR word_similarity(%s, COALESCE(me.title, '') || ' ' || me.content) >= 0.14
                          )
                        ORDER BY
                            CASE WHEN me.title ILIKE %s ESCAPE '\\' OR me.content ILIKE %s ESCAPE '\\' THEN 0 ELSE 1 END,
                            score DESC,
                            me.updated_at DESC
                        LIMIT %s
                        """,
                        (query, user_uuid, *col_params, like_pat, like_pat, query, like_pat, like_pat, pool_limit),
                    )
                    trgm_rows = [_row_to_dict(r) for r in await cur.fetchall()]
                except Exception:
                    try:
                        await cur.execute(
                            f"""
                            SELECT me.id, me.target, COALESCE(mc.name, me.target), COALESCE(me.title, ''),
                                   me.content, COALESCE(me.tags, '[]'::jsonb), me.source, NULL AS score
                            FROM memory_entries me
                            LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                            WHERE me.user_id = %s
                              {col_sql}
                              AND (me.content ILIKE %s ESCAPE '\\' OR me.title ILIKE %s ESCAPE '\\')
                            ORDER BY me.updated_at DESC
                            LIMIT %s
                            """,
                            (user_uuid, *col_params, like_pat, like_pat, pool_limit),
                        )
                        trgm_rows = [_row_to_dict(r) for r in await cur.fetchall()]
                    except Exception as exc:
                        logger.debug("Memory ILIKE leg skipped: %s", exc)

        fused = _rrf_fuse_memories([vec_rows, fts_rows, trgm_rows], top_k=max(limit * 3, 20))
        if not fused:
            return []

        # Optional Rerank stage
        if self.rerank_client is not None and self.rerank_client.is_configured and len(fused) > 1:
            try:
                docs = [
                    f"[{item.get('collection_name') or item.get('collection')}] {item.get('title') or ''} {item.get('content') or ''}".strip()
                    for item in fused
                ]
                reranked = await self.rerank_client.rerank(query, docs, top_n=min(len(fused), max(limit * 2, 12)))
                if reranked:
                    reordered: list[dict[str, Any]] = []
                    for idx, score in reranked:
                        if 0 <= idx < len(fused):
                            item = dict(fused[idx])
                            item["rerank_score"] = round(float(score), 6)
                            reordered.append(item)
                    if reordered:
                        fused = reordered
            except Exception as exc:
                logger.debug("Memory rerank skipped: %s", exc)

        selected = _mmr_select_memories(fused, limit=limit)
        # Best-effort lifecycle access tracking for L3 relevance/recency governance
        if selected and self.pool is not None:
            hit_ids: list[uuid.UUID] = []
            for s in selected:
                try:
                    hit_ids.append(uuid.UUID(str(s.get("id") or "")))
                except ValueError:
                    pass
            if hit_ids:
                try:
                    async with self.pool.connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                UPDATE memory_entries
                                SET access_count = COALESCE(access_count, 0) + 1,
                                    last_accessed_at = %s
                                WHERE id = ANY(%s)
                                """,
                                (datetime.now(timezone.utc), hit_ids),
                            )
                except Exception:
                    pass
        return selected

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
        title: str = "",
        tags: list[str] | None = None,
        collection_name: str | None = None,
        collection_description: str | None = None,
        is_pinned: bool = False,
        priority: int = 2,
        memory_enabled: bool = True,
        memory_require_confirm: bool = False,
    ) -> dict[str, Any]:
        if not memory_enabled:
            return {
                "status": "disabled",
                "message": "用户未开启长期记忆功能，未写入或暂存任何记忆。",
            }

        norm_target = normalize_collection_slug(target, fallback_name=collection_name)
        norm_action = str(action or "add").strip().lower()
        if norm_action not in ("add", "replace", "remove"):
            norm_action = "add"
        cleaned_content = _sanitize_entry(content)
        cleaned_old = _sanitize_entry(old_content or "") or None
        cleaned_title = _sanitize_title(title)
        cleaned_tags = _sanitize_tags(tags)
        if norm_action != "remove" and not cleaned_content:
            return {"status": "rejected", "message": "记忆内容不能为空。"}

        if len(cleaned_content) > 4000:
            cleaned_content = cleaned_content[:4000].rstrip()

        if memory_require_confirm:
            proposal_id = await self._stage_pending_proposal(
                user_id=user_id,
                conversation_id=conversation_id,
                target=norm_target,
                action=norm_action,
                title=cleaned_title,
                tags=cleaned_tags,
                content=cleaned_content,
                old_content=cleaned_old,
            )
            return {
                "status": "pending_confirmation",
                "proposal_id": proposal_id,
                "collection": norm_target,
                "target": norm_target,
                "action": norm_action,
                "title": cleaned_title,
                "tags": cleaned_tags,
                "content": cleaned_content,
                "message": "已提交记忆提案，等待用户在界面中确认后生效。",
            }

        entry_id, resolved_col_name = await self._commit_direct(
            user_id=user_id,
            agent_namespace=agent_namespace,
            target=norm_target,
            action=norm_action,
            title=cleaned_title,
            tags=cleaned_tags,
            content=cleaned_content,
            old_content=cleaned_old,
            collection_name=collection_name,
            collection_description=collection_description,
            is_pinned=is_pinned,
            priority=priority,
        )
        return {
            "status": "saved",
            "entry_id": entry_id,
            "collection": norm_target,
            "collection_name": resolved_col_name,
            "target": norm_target,
            "action": norm_action,
            "title": cleaned_title,
            "tags": cleaned_tags,
            "content": cleaned_content,
            "message": f"记忆已保存到「{resolved_col_name}」({norm_target})。",
        }

    async def _stage_pending_proposal(
        self,
        *,
        user_id: str,
        conversation_id: str | None,
        target: str,
        action: str,
        title: str,
        tags: list[str],
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
                        (id, user_id, conversation_id, target, title, tags, action, content, old_content, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, 'pending', %s)
                    """,
                    (
                        uuid.UUID(proposal_id),
                        user_uuid,
                        conv_uuid,
                        target,
                        title,
                        json.dumps(tags, ensure_ascii=False),
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
        title: str,
        tags: list[str],
        content: str,
        old_content: str | None,
        collection_name: str | None = None,
        collection_description: str | None = None,
        is_pinned: bool = False,
        priority: int = 2,
    ) -> tuple[str, str]:
        key = _deterministic_key(target, content or old_content or "")
        now = datetime.now(timezone.utc)
        resolved_col_name = (collection_name or _SYSTEM_BY_SLUG.get(target, {}).get("name") or target).strip()

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
                            "collection_name": resolved_col_name,
                            "title": title,
                            "tags": tags,
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
            embed_input = f"[{resolved_col_name}] {title} {' '.join(f'#{t}' for t in tags)}\n{content}".strip()
            vec = (
                await self.embedding_client.embed_query(embed_input)
                if action != "remove" and self.embedding_client.is_configured
                else None
            )
            tsv_text = " ".join(p for p in (title, " ".join(tags), content) if p).strip()
            tags_json = json.dumps(tags, ensure_ascii=False)

            async with self.pool.connection() as conn:
                async def _apply(cur: Any) -> str:
                    col_id, norm_slug, col_name, char_limit, max_entries = await self._resolve_or_create_collection_pg(
                        cur,
                        user_uuid,
                        target,
                        auto_create=(action != "remove"),
                        name=collection_name,
                        description=collection_description,
                    )
                    if action == "remove":
                        target_text = old_content or content
                        await cur.execute(
                            "DELETE FROM memory_entries WHERE user_id = %s AND target = %s AND content = %s",
                            (user_uuid, norm_slug, target_text),
                        )
                        return col_name
                    effective_pinned = bool(is_pinned)
                    effective_priority = max(1, min(3, int(priority or 2)))
                    if action == "replace" and old_content:
                        # Update matched entry in-place (preserving row ID and avoiding dangling supersedes_id)
                        await cur.execute(
                            "SELECT id, COALESCE(is_pinned, false) FROM memory_entries WHERE user_id = %s AND target = %s AND content = %s LIMIT 1",
                            (user_uuid, norm_slug, old_content),
                        )
                        old_row = await cur.fetchone()
                        if old_row:
                            old_id = old_row[0]
                            effective_pinned = effective_pinned or bool(old_row[1])
                            m_tag = getattr(self.embedding_client, "model_tag", "") or None
                            if vec:
                                await cur.execute(
                                    """
                                    UPDATE memory_entries
                                    SET title = %s, content = %s, tags = %s::jsonb,
                                        search_tsv = to_tsvector('simple', %s),
                                        embedding = %s::vector, embedding_model = %s,
                                        is_pinned = %s, priority = %s, updated_at = %s
                                    WHERE id = %s
                                    """,
                                    (title, content, tags_json, tsv_text, _vector_literal(vec), m_tag, effective_pinned, effective_priority, now, old_id),
                                )
                            else:
                                await cur.execute(
                                    """
                                    UPDATE memory_entries
                                    SET title = %s, content = %s, tags = %s::jsonb,
                                        search_tsv = to_tsvector('simple', %s),
                                        is_pinned = %s, priority = %s, updated_at = %s
                                    WHERE id = %s
                                    """,
                                    (title, content, tags_json, tsv_text, effective_pinned, effective_priority, now, old_id),
                                )
                            return col_name
                    # Enforce collection & global quota parity with server memory_service
                    await cur.execute(
                        "SELECT COUNT(*), COALESCE(SUM(char_length(content)), 0) FROM memory_entries WHERE user_id = %s AND collection_id = %s",
                        (user_uuid, col_id),
                    )
                    col_stat = await cur.fetchone()
                    if col_stat:
                        cur_cnt, cur_chars = int(col_stat[0] or 0), int(col_stat[1] or 0)
                        if max_entries and cur_cnt >= int(max_entries):
                            return col_name
                        if char_limit and (cur_chars + len(content)) > int(char_limit):
                            return col_name
                    await cur.execute(
                        "SELECT COALESCE(SUM(char_length(content)), 0) FROM memory_entries WHERE user_id = %s",
                        (user_uuid,),
                    )
                    total_stat = await cur.fetchone()
                    if total_stat and (int(total_stat[0] or 0) + len(content)) > 200_000:
                        return col_name
                    supersedes_uuid: uuid.UUID | None = None
                    # Deduplicate identical content before inserting
                    await cur.execute(
                        "SELECT id FROM memory_entries WHERE user_id = %s AND target = %s AND content = %s LIMIT 1",
                        (user_uuid, norm_slug, content),
                    )
                    if await cur.fetchone():
                        return col_name
                    if vec:
                        vec_lit = _vector_literal(vec)
                        m_tag = getattr(self.embedding_client, "model_tag", "") or None
                        try:
                            await cur.execute(
                                """
                                INSERT INTO memory_entries
                                    (id, user_id, collection_id, target, title, content, tags, source, search_tsv, embedding, embedding_model, is_pinned, priority, supersedes_id, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 'agent', to_tsvector('simple', %s), %s::vector, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    uuid.UUID(entry_id),
                                    user_uuid,
                                    col_id,
                                    norm_slug,
                                    title,
                                    content,
                                    tags_json,
                                    tsv_text,
                                    vec_lit,
                                    m_tag,
                                    effective_pinned,
                                    effective_priority,
                                    supersedes_uuid,
                                    now,
                                    now,
                                ),
                            )
                        except Exception:
                            await cur.execute(
                                """
                                INSERT INTO memory_entries
                                    (id, user_id, collection_id, target, title, content, tags, source, search_tsv, embedding, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 'agent', to_tsvector('simple', %s), %s::vector, %s, %s)
                                """,
                                (
                                    uuid.UUID(entry_id),
                                    user_uuid,
                                    col_id,
                                    norm_slug,
                                    title,
                                    content,
                                    tags_json,
                                    tsv_text,
                                    vec_lit,
                                    now,
                                    now,
                                ),
                            )
                    else:
                        try:
                            await cur.execute(
                                """
                                INSERT INTO memory_entries
                                    (id, user_id, collection_id, target, title, content, tags, source, search_tsv, is_pinned, priority, supersedes_id, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 'agent', to_tsvector('simple', %s), %s, %s, %s, %s, %s)
                                """,
                                (
                                    uuid.UUID(entry_id),
                                    user_uuid,
                                    col_id,
                                    norm_slug,
                                    title,
                                    content,
                                    tags_json,
                                    tsv_text,
                                    effective_pinned,
                                    effective_priority,
                                    supersedes_uuid,
                                    now,
                                    now,
                                ),
                            )
                        except Exception:
                            await cur.execute(
                                """
                                INSERT INTO memory_entries
                                    (id, user_id, collection_id, target, title, content, tags, source, search_tsv, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 'agent', to_tsvector('simple', %s), %s, %s)
                                """,
                                (
                                    uuid.UUID(entry_id),
                                    user_uuid,
                                    col_id,
                                    norm_slug,
                                    title,
                                    content,
                                    tags_json,
                                    tsv_text,
                                    now,
                                    now,
                                ),
                            )
                    if effective_pinned:
                        # Keep L0 pinned count <= 10 by demoting oldest-accessed excess entries
                        try:
                            await cur.execute(
                                """
                                UPDATE memory_entries
                                SET is_pinned = false
                                WHERE id IN (
                                    SELECT id FROM memory_entries
                                    WHERE user_id = %s AND is_pinned = true AND id <> %s
                                    ORDER BY priority ASC, last_accessed_at DESC NULLS LAST, updated_at DESC
                                    OFFSET 9
                                )
                                """,
                                (user_uuid, uuid.UUID(entry_id)),
                            )
                        except Exception:
                            pass
                    return col_name

                if hasattr(conn, "transaction"):
                    async with conn.transaction():
                        async with conn.cursor() as cur:
                            resolved_col_name = await _apply(cur)
                else:
                    async with conn.cursor() as cur:
                        resolved_col_name = await _apply(cur)
        return entry_id, resolved_col_name

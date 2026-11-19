from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.models import EmbeddingClient

logger = logging.getLogger("whitz.agent.rag")


@dataclass
class RetrievedChunk:
    chunk_id: str
    file_id: str
    filename: str
    conversation_id: str | None
    is_global: bool
    chunk_index: int
    locator: str
    content: str
    rrf_score: float
    vec_rank: int | None = None
    fts_rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "file_id": self.file_id,
            "filename": self.filename,
            "conversation_id": self.conversation_id,
            "is_global": self.is_global,
            "chunk_index": self.chunk_index,
            "locator": self.locator,
            "content": self.content,
            "rrf_score": round(self.rrf_score, 6),
            "vec_rank": self.vec_rank,
            "fts_rank": self.fts_rank,
        }


def _vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"


def rrf_fuse(
    ranked_lists: Sequence[Sequence[dict[str, Any]]],
    *,
    rrf_k: int = 60,
    top_k: int = 8,
) -> list[RetrievedChunk]:
    """Combine multiple ranked candidate lists using Reciprocal Rank Fusion (RRF)."""
    scores: dict[str, float] = {}
    records: dict[str, dict[str, Any]] = {}
    ranks_by_leg: dict[str, dict[int, int]] = {}

    for leg_idx, rows in enumerate(ranked_lists):
        for rank_0, row in enumerate(rows):
            cid = str(row["chunk_id"])
            rank_1 = rank_0 + 1
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank_1)
            if cid not in records:
                records[cid] = row
            ranks_by_leg.setdefault(cid, {})[leg_idx] = rank_1

    ordered_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)[:top_k]
    fused: list[RetrievedChunk] = []
    for cid in ordered_ids:
        rec = records[cid]
        leg_ranks = ranks_by_leg.get(cid, {})
        fused.append(
            RetrievedChunk(
                chunk_id=cid,
                file_id=str(rec["file_id"]),
                filename=str(rec.get("filename") or ""),
                conversation_id=str(rec["conversation_id"]) if rec.get("conversation_id") else None,
                is_global=bool(rec.get("is_global")),
                chunk_index=int(rec.get("chunk_index") or 0),
                locator=str(rec.get("locator") or ""),
                content=str(rec.get("content") or ""),
                rrf_score=scores[cid],
                vec_rank=leg_ranks.get(0),
                fts_rank=leg_ranks.get(1),
            )
        )
    return fused


class HybridRetriever:
    """Hybrid RAG over PG ``file_chunks`` using pgvector cosine (<=>) + tsvector FTS + RRF."""

    def __init__(
        self,
        *,
        pool: Any = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.pool = pool
        self.embedding_client = embedding_client or EmbeddingClient()

    async def search(
        self,
        *,
        user_id: str,
        conversation_id: str,
        query: str,
        file_id: str | None = None,
        top_k: int = 8,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        cleaned_query = (query or "").strip()
        if not cleaned_query or self.pool is None:
            return []

        user_uuid = uuid.UUID(str(user_id))
        conv_uuid = uuid.UUID(str(conversation_id))
        file_uuid = uuid.UUID(str(file_id)) if file_id else None
        candidate_k = max(top_k * 3, 20)

        vector_rows = await self._vector_search(
            user_uuid=user_uuid,
            conv_uuid=conv_uuid,
            file_uuid=file_uuid,
            query=cleaned_query,
            limit=candidate_k,
        )
        fts_rows = await self._fts_search(
            user_uuid=user_uuid,
            conv_uuid=conv_uuid,
            file_uuid=file_uuid,
            query=cleaned_query,
            limit=candidate_k,
        )
        if not fts_rows:
            fts_rows = await self._ilike_fallback(
                user_uuid=user_uuid,
                conv_uuid=conv_uuid,
                file_uuid=file_uuid,
                query=cleaned_query,
                limit=candidate_k,
            )

        fused = rrf_fuse([vector_rows, fts_rows], rrf_k=rrf_k, top_k=top_k)
        return [chunk.to_dict() for chunk in fused]

    async def _vector_search(
        self,
        *,
        user_uuid: uuid.UUID,
        conv_uuid: uuid.UUID,
        file_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            return []
        try:
            q_vec = await self.embedding_client.embed_query(query)
            vec_lit = _vector_literal(q_vec)
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content
                FROM file_chunks fc
                LEFT JOIN conversation_files cf ON cf.id = fc.file_id
                WHERE fc.user_id = %s
                  AND fc.embedding IS NOT NULL
                  AND (fc.conversation_id = %s OR fc.is_global = TRUE)
            """
            params: list[Any] = [user_uuid, conv_uuid]
            if file_uuid is not None:
                sql += " AND fc.file_id = %s"
                params.append(file_uuid)
            sql += " ORDER BY fc.embedding <=> %s::vector ASC LIMIT %s"
            params.extend([vec_lit, limit])

            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, tuple(params))
                    rows = await cur.fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            logger.debug("Vector search unavailable or skipped: %s", exc)
            return []

    async def _fts_search(
        self,
        *,
        user_uuid: uuid.UUID,
        conv_uuid: uuid.UUID,
        file_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            return []
        try:
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content
                FROM file_chunks fc
                LEFT JOIN conversation_files cf ON cf.id = fc.file_id
                WHERE fc.user_id = %s
                  AND (fc.conversation_id = %s OR fc.is_global = TRUE)
                  AND fc.search_tsv @@ plainto_tsquery('simple', %s)
            """
            params: list[Any] = [user_uuid, conv_uuid, query]
            if file_uuid is not None:
                sql += " AND fc.file_id = %s"
                params.append(file_uuid)
            sql += " ORDER BY ts_rank_cd(fc.search_tsv, plainto_tsquery('simple', %s)) DESC LIMIT %s"
            params.extend([query, limit])

            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, tuple(params))
                    rows = await cur.fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            logger.debug("FTS search failed: %s", exc)
            return []

    async def _ilike_fallback(
        self,
        *,
        user_uuid: uuid.UUID,
        conv_uuid: uuid.UUID,
        file_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            return []
        try:
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content
                FROM file_chunks fc
                LEFT JOIN conversation_files cf ON cf.id = fc.file_id
                WHERE fc.user_id = %s
                  AND (fc.conversation_id = %s OR fc.is_global = TRUE)
                  AND fc.content ILIKE %s
            """
            params: list[Any] = [user_uuid, conv_uuid, f"%{query}%"]
            if file_uuid is not None:
                sql += " AND fc.file_id = %s"
                params.append(file_uuid)
            sql += " ORDER BY fc.chunk_index ASC LIMIT %s"
            params.append(limit)

            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, tuple(params))
                    rows = await cur.fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            logger.debug("ILIKE fallback failed: %s", exc)
            return []

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "chunk_id": str(row[0]),
            "file_id": str(row[1]),
            "conversation_id": str(row[2]) if row[2] is not None else None,
            "is_global": bool(row[3]),
            "filename": str(row[4] or ""),
            "chunk_index": int(row[5] or 0),
            "locator": str(row[6] or ""),
            "content": str(row[7] or ""),
        }

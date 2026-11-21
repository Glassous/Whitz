from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.models import EmbeddingClient, RerankClient

logger = logging.getLogger("whitz.agent.rag")

_TRGM_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


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
    trgm_rank: int | None = None
    rerank_score: float | None = None
    context_header: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
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
            "trgm_rank": self.trgm_rank,
        }
        if self.context_header:
            out["context_header"] = self.context_header
        if self.rerank_score is not None:
            out["rerank_score"] = round(self.rerank_score, 6)
        return out


def _vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


def rrf_fuse(
    ranked_lists: Sequence[Sequence[dict[str, Any]]],
    *,
    rrf_k: int = 60,
    top_k: int = 8,
    weights: Sequence[float] | None = None,
) -> list[RetrievedChunk]:
    """Combine multiple ranked candidate lists using weighted Reciprocal Rank Fusion (RRF)."""
    scores: dict[str, float] = {}
    records: dict[str, dict[str, Any]] = {}
    ranks_by_leg: dict[str, dict[int, int]] = {}

    for leg_idx, rows in enumerate(ranked_lists):
        w = float(weights[leg_idx]) if weights and leg_idx < len(weights) else 1.0
        for rank_0, row in enumerate(rows):
            cid = str(row["chunk_id"])
            rank_1 = rank_0 + 1
            scores[cid] = scores.get(cid, 0.0) + w / (rrf_k + rank_1)
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
                is_global=bool(rec.get("is_global", True)),
                chunk_index=int(rec.get("chunk_index") or 0),
                locator=str(rec.get("locator") or ""),
                content=str(rec.get("content") or ""),
                rrf_score=scores[cid],
                vec_rank=leg_ranks.get(0),
                fts_rank=leg_ranks.get(1),
                trgm_rank=leg_ranks.get(2),
                context_header=str(rec.get("context_header") or ""),
            )
        )
    return fused


def mmr_select(
    candidates: Sequence[RetrievedChunk],
    *,
    top_k: int = 8,
    lambda_mult: float = 0.72,
    max_per_file: int = 4,
) -> list[RetrievedChunk]:
    """Maximal Marginal Relevance diversity selection preventing redundant adjacent chunks."""
    if len(candidates) <= 1 or top_k <= 0:
        return list(candidates[:top_k])

    max_score = max((c.rerank_score if c.rerank_score is not None else c.rrf_score) for c in candidates) or 1.0
    trigrams = [_char_trigrams(c.content[:800]) for c in candidates]
    selected: list[int] = []
    remaining = list(range(len(candidates)))
    per_file_count: dict[str, int] = {}

    while remaining and len(selected) < top_k:
        best_idx = -1
        best_val = -1e9
        for idx in remaining:
            cand = candidates[idx]
            if per_file_count.get(cand.file_id, 0) >= max_per_file and len(remaining) > (top_k - len(selected)):
                continue
            raw_rel = cand.rerank_score if cand.rerank_score is not None else cand.rrf_score
            rel = raw_rel / max_score if max_score > 0 else 0.0
            redundancy = max((_jaccard_sim(trigrams[idx], trigrams[s]) for s in selected), default=0.0)
            mmr_score = lambda_mult * rel - (1.0 - lambda_mult) * redundancy
            if mmr_score > best_val:
                best_val = mmr_score
                best_idx = idx
        if best_idx < 0:
            best_idx = remaining[0]
        selected.append(best_idx)
        remaining.remove(best_idx)
        fid = candidates[best_idx].file_id
        per_file_count[fid] = per_file_count.get(fid, 0) + 1

    return [candidates[i] for i in selected]


class HybridRetriever:
    """Industrial 3-way Hybrid RAG over PG ``file_chunks``:
    1. pgvector HNSW cosine (<=>) with ``hnsw.iterative_scan`` multi-tenant recall fix
    2. PostgreSQL full-text search (``search_tsv``)
    3. ``pg_trgm`` CJK trigram similarity (with escaped ILIKE fallback)
    Followed by RRF fusion -> Stage-2 Cross-Encoder Reranker -> MMR diversity selection.
    """

    def __init__(
        self,
        *,
        pool: Any = None,
        embedding_client: EmbeddingClient | None = None,
        rerank_client: RerankClient | None = None,
    ) -> None:
        self.pool = pool
        self.embedding_client = embedding_client or EmbeddingClient()
        self.rerank_client = rerank_client or RerankClient()

    async def search(
        self,
        *,
        user_id: str,
        conversation_id: str = "",
        query: str,
        file_id: str | None = None,
        top_k: int = 8,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        cleaned_query = (query or "").strip()
        if not cleaned_query or self.pool is None:
            return []

        try:
            user_uuid = uuid.UUID(str(user_id))
            file_uuid = uuid.UUID(str(file_id)) if file_id else None
        except ValueError:
            return []

        candidate_k = max(top_k * 3, 24)
        vec_task = self._vector_search(user_uuid=user_uuid, file_uuid=file_uuid, query=cleaned_query, limit=candidate_k)
        fts_task = self._fts_search(user_uuid=user_uuid, file_uuid=file_uuid, query=cleaned_query, limit=candidate_k)
        trgm_task = self._trgm_search(user_uuid=user_uuid, file_uuid=file_uuid, query=cleaned_query, limit=candidate_k)

        vector_rows, fts_rows, trgm_rows = await asyncio.gather(vec_task, fts_task, trgm_task)
        if not vector_rows and not fts_rows and not trgm_rows:
            trgm_rows = await self._ilike_fallback(
                user_uuid=user_uuid,
                file_uuid=file_uuid,
                query=cleaned_query,
                limit=candidate_k,
            )

        # Stage-1: Weighted RRF fusion (give vector + trgm slightly stronger weight for CJK+semantic balance)
        pool_k = max(top_k * 3, 20)
        fused = rrf_fuse(
            [vector_rows, fts_rows, trgm_rows],
            rrf_k=rrf_k,
            top_k=pool_k,
            weights=(1.2, 1.0, 1.0),
        )
        if not fused:
            return []

        # Stage-2: Optional Cross-Encoder Rerank (qwen3.7-text-rerank / Jina / BGE)
        if self.rerank_client.is_configured and len(fused) > 1:
            docs = [
                f"{c.context_header}\n{c.content}" if c.context_header else f"[{c.filename} {c.locator}]\n{c.content}"
                for c in fused
            ]
            reranked = await self.rerank_client.rerank(cleaned_query, docs, top_n=min(len(fused), max(top_k * 2, 12)))
            if reranked:
                reordered: list[RetrievedChunk] = []
                for idx, score in reranked:
                    # Drop clearly irrelevant noise when cross-encoder is confident it's unrelated
                    if score < 0.01 and len(reordered) >= 2:
                        continue
                    item = fused[idx]
                    item.rerank_score = score
                    reordered.append(item)
                if reordered:
                    fused = reordered

        # Stage-3: MMR Diversity selection
        diverse = mmr_select(fused, top_k=top_k, lambda_mult=0.75, max_per_file=max(3, top_k // 2 + 1))
        return [chunk.to_dict() for chunk in diverse]

    async def _vector_search(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.pool is None or not self.embedding_client.is_configured:
            return []
        try:
            q_vec = await self.embedding_client.embed_query(query)
            if not q_vec:
                return []
            vec_lit = _vector_literal(q_vec)
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = %s
                  AND fc.embedding IS NOT NULL
                  AND (fc.embedding <=> %s::vector) < 0.85
            """
            params: list[Any] = [user_uuid, vec_lit]
            if file_uuid is not None:
                sql += " AND fc.file_id = %s"
                params.append(file_uuid)
            sql += " ORDER BY fc.embedding <=> %s::vector ASC LIMIT %s"
            params.extend([vec_lit, limit])

            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    # Enable pgvector >= 0.8 iterative scan to prevent multi-tenant HNSW filter recall drop
                    try:
                        await cur.execute("SET hnsw.iterative_scan = relaxed_order")
                    except Exception:
                        pass
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
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = %s
                  AND fc.search_tsv @@ plainto_tsquery('simple', %s)
            """
            params: list[Any] = [user_uuid, query]
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

    async def _trgm_search(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """CJK-friendly trigram similarity search backed by pg_trgm GIN index."""
        if self.pool is None or len(query) < 2:
            return []
        try:
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = %s
                  AND word_similarity(%s, fc.content) >= 0.16
            """
            params: list[Any] = [user_uuid, query]
            if file_uuid is not None:
                sql += " AND fc.file_id = %s"
                params.append(file_uuid)
            sql += " ORDER BY word_similarity(%s, fc.content) DESC LIMIT %s"
            params.extend([query, limit])

            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, tuple(params))
                    rows = await cur.fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            logger.debug("pg_trgm search unavailable: %s", exc)
            return []

    async def _ilike_fallback(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.pool is None:
            return []
        try:
            pattern = f"%{_escape_like(query)}%"
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = %s
                  AND fc.content ILIKE %s ESCAPE '\\'
            """
            params: list[Any] = [user_uuid, pattern]
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
            "context_header": str(row[8] or "") if len(row) > 8 else "",
        }

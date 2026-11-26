from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from whitz_rag.embeddings import (
    EmbeddingClient,
    RerankClient,
    char_trigrams,
    escape_like,
    jaccard_sim,
    vector_literal,
)
from whitz_rag.types import ConfidenceLevel, EvidenceItem, RagDiagnostics, SourceType

logger = logging.getLogger("whitz.rag.retriever")

_NAMED_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")
_KEYWORD_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}")


def _to_psycopg_positional(sql: str, params: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """Convert SQLAlchemy-style `:param` placeholders to psycopg3 `%s` positional args without touching `::type` casts."""
    values: list[Any] = []

    def _repl(match: re.Match[str]) -> str:
        values.append(params[match.group(1)])
        return "%s"

    return _NAMED_PARAM_RE.sub(_repl, sql), tuple(values)


class DbAdapter:
    """Dual-driver async SQL adapter supporting both psycopg3 AsyncConnectionPool (Agent) and SQLAlchemy AsyncSession (Server)."""

    _iterative_scan_supported: bool | None = None

    def __init__(self, *, pool: Any = None, session: Any = None) -> None:
        self.pool = pool
        self.session = session

    @property
    def is_available(self) -> bool:
        return self.pool is not None or self.session is not None

    @property
    def supports_parallel(self) -> bool:
        # psycopg3 pools allow concurrent queries across connections; single SQLAlchemy AsyncSession must serialize.
        return self.pool is not None

    @staticmethod
    def _trgm_threshold_sql(threshold: float) -> str:
        val = max(0.05, min(0.95, float(threshold)))
        return f"SET LOCAL pg_trgm.word_similarity_threshold = {val:.2f}"

    async def fetch_all(
        self,
        sql: str,
        params: dict[str, Any],
        *,
        set_iterative_scan: bool = False,
        trgm_threshold: float | None = None,
    ) -> list[tuple[Any, ...]]:
        if self.pool is not None:
            pg_sql, pg_params = _to_psycopg_positional(sql, params)
            need_tx = bool(trgm_threshold is not None or (set_iterative_scan and DbAdapter._iterative_scan_supported is not False))
            async with self.pool.connection() as conn:
                if need_tx and hasattr(conn, "transaction"):
                    async with conn.transaction():
                        async with conn.cursor() as cur:
                            if set_iterative_scan and DbAdapter._iterative_scan_supported is not False:
                                try:
                                    await cur.execute("SAVEPOINT whitz_iter_scan")
                                    await cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
                                    await cur.execute("RELEASE SAVEPOINT whitz_iter_scan")
                                    DbAdapter._iterative_scan_supported = True
                                except Exception:
                                    DbAdapter._iterative_scan_supported = False
                                    try:
                                        await cur.execute("ROLLBACK TO SAVEPOINT whitz_iter_scan")
                                        await cur.execute("RELEASE SAVEPOINT whitz_iter_scan")
                                    except Exception:
                                        pass
                            if trgm_threshold is not None:
                                await cur.execute(self._trgm_threshold_sql(trgm_threshold))
                            await cur.execute(pg_sql, pg_params)
                            rows = await cur.fetchall()
                else:
                    async with conn.cursor() as cur:
                        if trgm_threshold is not None:
                            try:
                                await cur.execute(self._trgm_threshold_sql(trgm_threshold))
                            except Exception:
                                pass
                        await cur.execute(pg_sql, pg_params)
                        rows = await cur.fetchall()
            return [tuple(r) for r in rows]

        if self.session is not None:
            from sqlalchemy import text

            async with self.session.begin_nested():
                if set_iterative_scan and DbAdapter._iterative_scan_supported is not False:
                    try:
                        async with self.session.begin_nested():
                            await self.session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
                            DbAdapter._iterative_scan_supported = True
                    except Exception:
                        DbAdapter._iterative_scan_supported = False
                if trgm_threshold is not None:
                    await self.session.execute(text(self._trgm_threshold_sql(trgm_threshold)))
                res = await self.session.execute(text(sql), params)
                rows = res.fetchall()
            return [tuple(r) for r in rows]

        return []

    async def run_legs(self, coros: Sequence[Any]) -> list[Any]:
        if self.supports_parallel:
            return list(await asyncio.gather(*coros))
        results: list[Any] = []
        for coro in coros:
            results.append(await coro)
        return results


def _clip_snippet(text: str, query: str = "", limit: int = 280) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    q = (query or "").strip().lower()
    if q:
        idx = cleaned.lower().find(q)
        if idx >= 0:
            start = max(0, idx - 80)
            end = min(len(cleaned), idx + len(q) + (limit - 80))
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(cleaned) else ""
            return f"{prefix}{cleaned[start:end]}{suffix}"
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _grade_confidence(
    *,
    rerank_score: float | None,
    rrf_score: float,
    vec_rank: int | None,
    fts_rank: int | None,
    trgm_rank: int | None,
) -> ConfidenceLevel:
    if rerank_score is not None:
        if rerank_score >= 0.45:
            return "high"
        if rerank_score >= 0.15:
            return "medium"
        return "low"
    leg_hits = sum(1 for r in (vec_rank, fts_rank, trgm_rank) if r is not None)
    if leg_hits >= 2 or rrf_score >= 0.028:
        return "high"
    if rrf_score >= 0.015:
        return "medium"
    return "low"


def rrf_fuse_rows(
    ranked_lists: Sequence[Sequence[dict[str, Any]]],
    *,
    rrf_k: int = 60,
    top_k: int = 24,
    weights: Sequence[float] | None = None,
    id_field: str = "chunk_id",
) -> list[dict[str, Any]]:
    """Combine multiple ranked candidate lists using weighted Reciprocal Rank Fusion (RRF)."""
    scores: dict[str, float] = {}
    records: dict[str, dict[str, Any]] = {}
    ranks_by_leg: dict[str, dict[int, int]] = {}

    for leg_idx, rows in enumerate(ranked_lists):
        w = float(weights[leg_idx]) if weights and leg_idx < len(weights) else 1.0
        for rank_0, row in enumerate(rows):
            cid = str(row.get(id_field) or "")
            if not cid:
                continue
            rank_1 = rank_0 + 1
            boost = float(row.get("_boost", 1.0))
            scores[cid] = scores.get(cid, 0.0) + (w * boost) / (rrf_k + rank_1)
            if cid not in records:
                records[cid] = dict(row)
            ranks_by_leg.setdefault(cid, {})[leg_idx] = rank_1

    ordered_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)[:top_k]
    out: list[dict[str, Any]] = []
    for cid in ordered_ids:
        rec = dict(records[cid])
        leg_ranks = ranks_by_leg.get(cid, {})
        rec["rrf_score"] = scores[cid]
        rec["vec_rank"] = leg_ranks.get(0)
        rec["fts_rank"] = leg_ranks.get(1)
        rec["trgm_rank"] = leg_ranks.get(2)
        out.append(rec)
    return out


def mmr_select_evidence(
    candidates: Sequence[EvidenceItem],
    *,
    top_k: int = 8,
    lambda_mult: float = 0.75,
    max_per_source: int = 4,
) -> list[EvidenceItem]:
    """Maximal Marginal Relevance diversity selection preventing redundant adjacent chunks."""
    if len(candidates) <= 1 or top_k <= 0:
        return list(candidates[:top_k])

    max_score = max((c.rerank_score if c.rerank_score is not None else c.score) for c in candidates) or 1.0
    trigrams = [char_trigrams(f"{c.title} {c.content[:800]}") for c in candidates]
    selected: list[int] = []
    remaining = list(range(len(candidates)))
    per_source_count: dict[str, int] = {}

    while remaining and len(selected) < top_k:
        best_idx = -1
        best_val = -1e9
        for idx in remaining:
            cand = candidates[idx]
            src_key = f"{cand.source_type}:{cand.source_id}"
            if per_source_count.get(src_key, 0) >= max_per_source and len(remaining) > (top_k - len(selected)):
                continue
            raw_rel = cand.rerank_score if cand.rerank_score is not None else cand.score
            rel = raw_rel / max_score if max_score > 0 else 0.0
            redundancy = max((jaccard_sim(trigrams[idx], trigrams[s]) for s in selected), default=0.0)
            mmr_score = lambda_mult * rel - (1.0 - lambda_mult) * redundancy
            if mmr_score > best_val:
                best_val = mmr_score
                best_idx = idx
        if best_idx < 0:
            best_idx = remaining[0]
        selected.append(best_idx)
        remaining.remove(best_idx)
        skey = f"{candidates[best_idx].source_type}:{candidates[best_idx].source_id}"
        per_source_count[skey] = per_source_count.get(skey, 0) + 1

    return [candidates[i] for i in selected]


def _extract_simplified_query(query: str) -> str:
    """Extract key terms for corrective fallback when full-sentence retrieval misses."""
    tokens = _KEYWORD_RE.findall((query or "").strip())
    if not tokens:
        return ""
    # Prefer longer, content-bearing tokens
    unique = list(dict.fromkeys(sorted(tokens, key=len, reverse=True)))
    return " ".join(unique[:4])


def _age_decay_boost(ts: Any) -> float:
    if ts is None:
        return 1.0
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, datetime):
            dt = ts
        else:
            return 1.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
        return 1.0 + 0.18 / (1.0 + age_days / 14.0)
    except Exception:
        return 1.0


class UnifiedKnowledgeRetriever:
    """Single-source-of-truth multi-source Hybrid RAG engine across:
    1. `file_chunks` (workspace & library documents + multimodal image captions)
    2. `memory_entries` (multi-collection long-term memory)
    3. `conversation_digests` + `message_chunks` (cross-chat episodic memory)

    Pipeline:
    3-leg parallel recall (pgvector HNSW iterative_scan + FTS + pg_trgm / ILIKE)
    -> Scope & Recency weighted RRF
    -> Stage-2 Cross-Encoder Rerank + Confidence Grading
    -> Parent / Sibling Window Expansion (for file chunks)
    -> Stage-3 MMR Diversity Selection
    -> Optional Corrective Retry on low-confidence / empty hits
    """

    def __init__(
        self,
        *,
        db: DbAdapter | None = None,
        pool: Any = None,
        session: Any = None,
        embedding_client: EmbeddingClient | None = None,
        rerank_client: RerankClient | None = None,
    ) -> None:
        self.db = db or DbAdapter(pool=pool, session=session)
        self.embedding_client = embedding_client or EmbeddingClient()
        self.rerank_client = rerank_client or RerankClient()

    async def _embed_query_once(self, query: str) -> str | None:
        if not self.embedding_client.is_configured or not (query or "").strip():
            return None
        try:
            vec = await self.embedding_client.embed_query(query[:1000])
            return vector_literal(vec) if vec else None
        except Exception as exc:
            logger.debug("Query embedding skipped: %s", exc)
            return None

    async def list_indexing_files(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuids: Sequence[uuid.UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """Detect files still indexing or failed so diagnostics can guide Agent self-healing."""
        if not self.db.is_available:
            return []
        try:
            sql = """
                SELECT id, filename, index_status, indexed_chunks
                FROM conversation_files
                WHERE user_id = :uid
                  AND status = 'ready'
                  AND index_status IN ('indexing', 'failed', 'partial')
            """
            params: dict[str, Any] = {"uid": user_uuid}
            if file_uuids:
                sql += " AND id = ANY(:fids)"
                params["fids"] = list(file_uuids)
            sql += " ORDER BY updated_at DESC LIMIT 8"
            rows = await self.db.fetch_all(sql, params)
            return [
                {
                    "file_id": str(r[0]),
                    "filename": str(r[1] or ""),
                    "index_status": str(r[2] or ""),
                    "indexed_chunks": int(r[3] or 0),
                }
                for r in rows
            ]
        except Exception:
            return []

    async def _list_linked_file_ids(
        self,
        *,
        user_uuid: uuid.UUID,
        conv_uuid: uuid.UUID | None,
    ) -> set[str]:
        if conv_uuid is None or not self.db.is_available:
            return set()
        try:
            rows = await self.db.fetch_all(
                """
                SELECT file_id
                FROM conversation_file_links
                WHERE conversation_id = :cid AND user_id = :uid
                """,
                {"cid": conv_uuid, "uid": user_uuid},
            )
            return {str(r[0]) for r in rows if r and r[0] is not None}
        except Exception:
            return set()

    # ------------------------------------------------------------------
    # Source 1: Files (`file_chunks` + Parent/Sibling Window Expansion)
    # ------------------------------------------------------------------
    async def search_files(
        self,
        *,
        user_id: str,
        query: str,
        conversation_id: str = "",
        attached_file_ids: Sequence[str] | None = None,
        file_id: str | None = None,
        file_ids: Sequence[str] | None = None,
        top_k: int = 8,
        rrf_k: int = 60,
        expand_neighbors: bool = True,
        apply_rerank: bool = True,
        apply_mmr: bool = True,
        q_vec_lit: str | None = None,
    ) -> list[EvidenceItem]:
        cleaned = (query or "").strip()
        if not cleaned or not self.db.is_available:
            return []
        try:
            user_uuid = uuid.UUID(str(user_id))
            conv_uuid = uuid.UUID(str(conversation_id)) if conversation_id else None
        except ValueError:
            return []

        target_file_uuids: list[uuid.UUID] = []
        for raw_fid in ([file_id] if file_id else []) + list(file_ids or []):
            try:
                if raw_fid:
                    target_file_uuids.append(uuid.UUID(str(raw_fid)))
            except ValueError:
                pass
        attached_set: set[str] = {str(fid) for fid in (attached_file_ids or []) if fid}

        if q_vec_lit is None:
            q_vec_lit = await self._embed_query_once(cleaned)

        candidate_k = max(top_k * 3, 24)
        model_tag = self.embedding_client.model_tag

        vec_rows, fts_rows, trgm_rows, linked_set = await self.db.run_legs(
            [
                self._file_vector_leg(
                    user_uuid=user_uuid,
                    file_uuids=target_file_uuids,
                    q_vec_lit=q_vec_lit,
                    model_tag=model_tag,
                    limit=candidate_k,
                ),
                self._file_fts_leg(
                    user_uuid=user_uuid,
                    file_uuids=target_file_uuids,
                    query=cleaned,
                    limit=candidate_k,
                ),
                self._file_trgm_leg(
                    user_uuid=user_uuid,
                    file_uuids=target_file_uuids,
                    query=cleaned,
                    limit=candidate_k,
                ),
                self._list_linked_file_ids(user_uuid=user_uuid, conv_uuid=conv_uuid),
            ]
        )

        if not vec_rows and not fts_rows and not trgm_rows:
            trgm_rows = await self._file_ilike_fallback(
                user_uuid=user_uuid,
                file_uuids=target_file_uuids,
                query=cleaned,
                limit=candidate_k,
            )

        # Apply scope boost: explicitly attached files (1.45x) > current conversation/linked files (1.2x) > library (1.0x)
        def _apply_scope_boost(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            for r in rows:
                fid = str(r.get("file_id") or "")
                cid = str(r.get("conversation_id") or "")
                if fid in attached_set:
                    r["_boost"] = 1.45
                elif (conv_uuid is not None and cid == str(conv_uuid)) or (fid in linked_set):
                    r["_boost"] = 1.20
                else:
                    r["_boost"] = 1.0
            return rows

        fused_rows = rrf_fuse_rows(
            [_apply_scope_boost(vec_rows), _apply_scope_boost(fts_rows), _apply_scope_boost(trgm_rows)],
            rrf_k=rrf_k,
            top_k=max(top_k * 3, 20),
            weights=(1.25, 1.0, 1.0),
        )
        if not fused_rows:
            return []

        items = [self._file_row_to_evidence(r, query=cleaned) for r in fused_rows]

        if apply_rerank and self.rerank_client.is_configured and len(items) > 1:
            items = await self._rerank_evidence(cleaned, items, top_n=min(len(items), max(top_k * 2, 12)))

        if apply_mmr:
            selected = mmr_select_evidence(items, top_k=top_k, lambda_mult=0.75, max_per_source=max(3, top_k // 2 + 1))
        else:
            selected = items[:top_k]

        if expand_neighbors and selected:
            await self._expand_file_neighbors(user_uuid=user_uuid, items=selected)

        return selected

    async def _file_vector_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuids: list[uuid.UUID],
        q_vec_lit: str | None,
        model_tag: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not q_vec_lit:
            return []
        try:
            # Allow rows with matching embedding_model or legacy NULL embedding_model
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header,
                       COALESCE(fc.section_path, '') AS section_path,
                       COALESCE(fc.chunk_type, 'text') AS chunk_type,
                       fc.chunk_meta
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = :uid
                  AND fc.embedding IS NOT NULL
                  AND (fc.embedding <=> CAST(:qvec AS vector)) < 0.85
            """
            params: dict[str, Any] = {"uid": user_uuid, "qvec": q_vec_lit, "lim": limit}
            if model_tag:
                sql += " AND (fc.embedding_model IS NULL OR fc.embedding_model = :mtag)"
                params["mtag"] = model_tag
            if file_uuids:
                if len(file_uuids) == 1:
                    sql += " AND fc.file_id = :fid"
                    params["fid"] = file_uuids[0]
                else:
                    sql += " AND fc.file_id = ANY(:fids)"
                    params["fids"] = file_uuids
            sql += " ORDER BY fc.embedding <=> CAST(:qvec AS vector) ASC LIMIT :lim"
            rows = await self.db.fetch_all(sql, params, set_iterative_scan=True)
            return [self._parse_file_row(r) for r in rows]
        except Exception as exc:
            # Graceful fallback if migration 0020 columns haven't been applied yet
            if "section_path" in str(exc) or "embedding_model" in str(exc) or "chunk_meta" in str(exc):
                return await self._file_vector_leg_legacy(
                    user_uuid=user_uuid, file_uuids=file_uuids, q_vec_lit=q_vec_lit, limit=limit
                )
            logger.debug("File vector leg skipped: %s", exc)
            return []

    async def _file_vector_leg_legacy(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuids: list[uuid.UUID],
        q_vec_lit: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = :uid
                  AND fc.embedding IS NOT NULL
                  AND (fc.embedding <=> CAST(:qvec AS vector)) < 0.85
            """
            params: dict[str, Any] = {"uid": user_uuid, "qvec": q_vec_lit, "lim": limit}
            if file_uuids:
                sql += " AND fc.file_id = ANY(:fids)"
                params["fids"] = file_uuids
            sql += " ORDER BY fc.embedding <=> CAST(:qvec AS vector) ASC LIMIT :lim"
            rows = await self.db.fetch_all(sql, params, set_iterative_scan=True)
            return [self._parse_file_row(r) for r in rows]
        except Exception:
            return []

    async def _file_fts_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuids: list[uuid.UUID],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header,
                       COALESCE(fc.section_path, '') AS section_path,
                       COALESCE(fc.chunk_type, 'text') AS chunk_type,
                       fc.chunk_meta
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = :uid
                  AND fc.search_tsv @@ plainto_tsquery('simple', :q)
            """
            params: dict[str, Any] = {"uid": user_uuid, "q": query, "lim": limit}
            if file_uuids:
                if len(file_uuids) == 1:
                    sql += " AND fc.file_id = :fid"
                    params["fid"] = file_uuids[0]
                else:
                    sql += " AND fc.file_id = ANY(:fids)"
                    params["fids"] = file_uuids
            sql += " ORDER BY ts_rank_cd(fc.search_tsv, plainto_tsquery('simple', :q)) DESC LIMIT :lim"
            rows = await self.db.fetch_all(sql, params)
            return [self._parse_file_row(r) for r in rows]
        except Exception as exc:
            if "section_path" in str(exc) or "chunk_meta" in str(exc):
                try:
                    sql = """
                        SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                               COALESCE(cf.filename, '') AS filename,
                               fc.chunk_index, fc.locator, fc.content,
                               COALESCE(fc.context_header, '') AS context_header
                        FROM file_chunks fc
                        INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                        WHERE fc.user_id = :uid
                          AND fc.search_tsv @@ plainto_tsquery('simple', :q)
                    """
                    params = {"uid": user_uuid, "q": query, "lim": limit}
                    if file_uuids:
                        sql += " AND fc.file_id = ANY(:fids)"
                        params["fids"] = file_uuids
                    sql += " ORDER BY ts_rank_cd(fc.search_tsv, plainto_tsquery('simple', :q)) DESC LIMIT :lim"
                    return [self._parse_file_row(r) for r in await self.db.fetch_all(sql, params)]
                except Exception:
                    return []
            logger.debug("File FTS leg skipped: %s", exc)
            return []

    async def _file_trgm_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuids: list[uuid.UUID],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if len(query) < 2:
            return []
        try:
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header,
                       COALESCE(fc.section_path, '') AS section_path,
                       COALESCE(fc.chunk_type, 'text') AS chunk_type,
                       fc.chunk_meta
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = :uid
                  AND :q <% fc.content
            """
            params: dict[str, Any] = {"uid": user_uuid, "q": query, "lim": limit}
            if file_uuids:
                if len(file_uuids) == 1:
                    sql += " AND fc.file_id = :fid"
                    params["fid"] = file_uuids[0]
                else:
                    sql += " AND fc.file_id = ANY(:fids)"
                    params["fids"] = file_uuids
            sql += " ORDER BY word_similarity(:q, fc.content) DESC LIMIT :lim"
            rows = await self.db.fetch_all(sql, params, trgm_threshold=0.16)
            return [self._parse_file_row(r) for r in rows]
        except Exception as exc:
            if "section_path" in str(exc) or "chunk_meta" in str(exc):
                try:
                    sql = """
                        SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                               COALESCE(cf.filename, '') AS filename,
                               fc.chunk_index, fc.locator, fc.content,
                               COALESCE(fc.context_header, '') AS context_header
                        FROM file_chunks fc
                        INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                        WHERE fc.user_id = :uid
                          AND :q <% fc.content
                    """
                    params = {"uid": user_uuid, "q": query, "lim": limit}
                    if file_uuids:
                        sql += " AND fc.file_id = ANY(:fids)"
                        params["fids"] = file_uuids
                    sql += " ORDER BY word_similarity(:q, fc.content) DESC LIMIT :lim"
                    return [self._parse_file_row(r) for r in await self.db.fetch_all(sql, params, trgm_threshold=0.16)]
                except Exception:
                    return []
            logger.debug("File pg_trgm leg skipped: %s", exc)
            return []

    async def _file_ilike_fallback(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuids: list[uuid.UUID],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            pattern = f"%{escape_like(query)}%"
            sql = """
                SELECT fc.id, fc.file_id, fc.conversation_id, fc.is_global,
                       COALESCE(cf.filename, '') AS filename,
                       fc.chunk_index, fc.locator, fc.content,
                       COALESCE(fc.context_header, '') AS context_header
                FROM file_chunks fc
                INNER JOIN conversation_files cf ON cf.id = fc.file_id AND cf.status = 'ready'
                WHERE fc.user_id = :uid
                  AND (fc.content ILIKE :pat ESCAPE '\\' OR COALESCE(fc.context_header, '') ILIKE :pat ESCAPE '\\')
            """
            params: dict[str, Any] = {"uid": user_uuid, "pat": pattern, "lim": limit}
            if file_uuids:
                if len(file_uuids) == 1:
                    sql += " AND fc.file_id = :fid"
                    params["fid"] = file_uuids[0]
                else:
                    sql += " AND fc.file_id = ANY(:fids)"
                    params["fids"] = file_uuids
            sql += " ORDER BY fc.chunk_index ASC LIMIT :lim"
            rows = await self.db.fetch_all(sql, params)
            return [self._parse_file_row(r) for r in rows]
        except Exception as exc:
            logger.debug("File ILIKE fallback skipped: %s", exc)
            return []

    async def _expand_file_neighbors(
        self,
        *,
        user_uuid: uuid.UUID,
        items: list[EvidenceItem],
        max_expanded_chars: int = 1800,
    ) -> None:
        """Parent/sibling window expansion: fetch k-1 & k+1 chunks for top file hits in one batch."""
        targets: list[tuple[EvidenceItem, uuid.UUID, int]] = []
        for item in items:
            if item.source_type != "file":
                continue
            ctype = str(item.metadata.get("chunk_type") or "text")
            if ctype in ("image_caption", "summary"):
                continue
            try:
                fid = uuid.UUID(str(item.source_id))
                cidx = int(item.metadata.get("chunk_index", -1))
                if cidx >= 0:
                    targets.append((item, fid, cidx))
            except (ValueError, TypeError):
                continue

        if not targets:
            return

        # Fetch all neighbor chunks across files in a single batched query (eliminates N+1)
        all_fids: list[uuid.UUID] = []
        seen_fids: set[uuid.UUID] = set()
        all_idxs: set[int] = set()
        wanted_pairs: set[tuple[str, int]] = set()
        for _, fid, cidx in targets:
            if fid not in seen_fids:
                seen_fids.add(fid)
                all_fids.append(fid)
            if cidx > 0:
                all_idxs.add(cidx - 1)
                wanted_pairs.add((str(fid), cidx - 1))
            all_idxs.add(cidx + 1)
            wanted_pairs.add((str(fid), cidx + 1))

        neighbor_map: dict[tuple[str, int], tuple[str, str]] = {}
        try:
            rows = await self.db.fetch_all(
                """
                SELECT file_id, chunk_index, content, COALESCE(section_path, '')
                FROM file_chunks
                WHERE user_id = :uid AND file_id = ANY(:fids) AND chunk_index = ANY(:idxs)
                """,
                {"uid": user_uuid, "fids": all_fids, "idxs": sorted(all_idxs)},
            )
            for r in rows:
                pair = (str(r[0]), int(r[1]))
                if pair in wanted_pairs:
                    neighbor_map[pair] = (str(r[2] or ""), str(r[3] or ""))
        except Exception:
            try:
                rows = await self.db.fetch_all(
                    """
                    SELECT file_id, chunk_index, content
                    FROM file_chunks
                    WHERE user_id = :uid AND file_id = ANY(:fids) AND chunk_index = ANY(:idxs)
                    """,
                    {"uid": user_uuid, "fids": all_fids, "idxs": sorted(all_idxs)},
                )
                for r in rows:
                    pair = (str(r[0]), int(r[1]))
                    if pair in wanted_pairs:
                        neighbor_map[pair] = (str(r[2] or ""), "")
            except Exception:
                return

        for item, fid, cidx in targets:
            cur_section = str(item.metadata.get("section_path") or "")
            parts = [item.content]
            total_len = len(item.content)
            expanded = False

            prev_pair = neighbor_map.get((str(fid), cidx - 1))
            if prev_pair and (not cur_section or not prev_pair[1] or prev_pair[1] == cur_section):
                prev_txt = prev_pair[0]
                if prev_txt and total_len + len(prev_txt) <= max_expanded_chars:
                    parts.insert(0, prev_txt)
                    total_len += len(prev_txt)
                    expanded = True

            next_pair = neighbor_map.get((str(fid), cidx + 1))
            if next_pair and (not cur_section or not next_pair[1] or next_pair[1] == cur_section):
                next_txt = next_pair[0]
                if next_txt and total_len + len(next_txt) <= max_expanded_chars:
                    parts.append(next_txt)
                    total_len += len(next_txt)
                    expanded = True

            if expanded:
                item.content = "\n".join(parts)
                item.expanded = True

    @staticmethod
    def _parse_file_row(row: tuple[Any, ...]) -> dict[str, Any]:
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
            "section_path": str(row[9] or "") if len(row) > 9 else "",
            "chunk_type": str(row[10] or "text") if len(row) > 10 else "text",
            "chunk_meta": row[11] if len(row) > 11 and isinstance(row[11], dict) else {},
        }

    @staticmethod
    def _file_row_to_evidence(rec: dict[str, Any], *, query: str = "") -> EvidenceItem:
        sec = str(rec.get("section_path") or "").strip()
        loc = str(rec.get("locator") or "").strip()
        subtitle = " · ".join(p for p in (sec, loc) if p) or f"片段 #{int(rec.get('chunk_index') or 0) + 1}"
        rrf = float(rec.get("rrf_score") or 0.0)
        return EvidenceItem(
            citation_id="",
            source_type="file",
            source_id=str(rec["file_id"]),
            chunk_id=str(rec["chunk_id"]),
            title=str(rec.get("filename") or "未命名文件"),
            subtitle=subtitle,
            content=str(rec.get("content") or ""),
            snippet=_clip_snippet(str(rec.get("content") or ""), query=query),
            score=rrf,
            rrf_score=rrf,
            vec_rank=rec.get("vec_rank"),
            fts_rank=rec.get("fts_rank"),
            trgm_rank=rec.get("trgm_rank"),
            confidence=_grade_confidence(
                rerank_score=None,
                rrf_score=rrf,
                vec_rank=rec.get("vec_rank"),
                fts_rank=rec.get("fts_rank"),
                trgm_rank=rec.get("trgm_rank"),
            ),
            metadata={
                "file_id": str(rec["file_id"]),
                "filename": str(rec.get("filename") or ""),
                "conversation_id": rec.get("conversation_id"),
                "is_global": bool(rec.get("is_global", True)),
                "chunk_index": int(rec.get("chunk_index") or 0),
                "locator": loc,
                "section_path": sec,
                "context_header": str(rec.get("context_header") or ""),
                "chunk_type": str(rec.get("chunk_type") or "text"),
                "chunk_meta": rec.get("chunk_meta") or {},
            },
        )

    # ------------------------------------------------------------------
    # Source 2: Long-Term Memories (`memory_entries`)
    # ------------------------------------------------------------------
    async def search_memories(
        self,
        *,
        user_id: str,
        query: str,
        collection: str | None = None,
        tags: Sequence[str] | None = None,
        top_k: int = 8,
        rrf_k: int = 60,
        apply_rerank: bool = True,
        apply_mmr: bool = True,
        q_vec_lit: str | None = None,
    ) -> list[EvidenceItem]:
        cleaned = (query or "").strip()
        if not self.db.is_available:
            return []
        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            return []

        norm_col = (collection or "").strip().lower() or None
        norm_tags = {str(t).strip().lower() for t in (tags or []) if str(t).strip()}

        col_sql = (
            "AND (mc.slug = :col OR (me.collection_id IS NULL AND me.target = :col))"
            if norm_col
            else "AND (mc.enabled IS NULL OR mc.enabled = true)"
        )
        base_params: dict[str, Any] = {"uid": user_uuid}
        if norm_col:
            base_params["col"] = norm_col

        if not cleaned:
            try:
                rows = await self.db.fetch_all(
                    f"""
                    SELECT me.id, me.collection_id, me.target, COALESCE(mc.name, me.target),
                           COALESCE(me.title, ''), me.content, COALESCE(me.tags, '[]'::jsonb), me.source, me.updated_at
                    FROM memory_entries me
                    LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                    WHERE me.user_id = :uid {col_sql}
                    ORDER BY me.updated_at DESC
                    LIMIT :lim
                    """,
                    {**base_params, "lim": top_k},
                )
                return [self._memory_row_to_evidence(self._parse_memory_row(r)) for r in rows]
            except Exception as exc:
                logger.debug("Empty-query memory fetch skipped: %s", exc)
                return []

        if q_vec_lit is None:
            q_vec_lit = await self._embed_query_once(cleaned)

        pool_limit = max(top_k * 3, 24)
        model_tag = self.embedding_client.model_tag
        vec_rows, fts_rows, trgm_rows = await self.db.run_legs(
            [
                self._memory_vector_leg(
                    base_params=base_params,
                    col_sql=col_sql,
                    q_vec_lit=q_vec_lit,
                    model_tag=model_tag,
                    limit=pool_limit,
                ),
                self._memory_fts_leg(base_params=base_params, col_sql=col_sql, query=cleaned, limit=pool_limit),
                self._memory_trgm_leg(base_params=base_params, col_sql=col_sql, query=cleaned, limit=pool_limit),
            ]
        )

        fused = rrf_fuse_rows(
            [vec_rows, fts_rows, trgm_rows],
            rrf_k=rrf_k,
            top_k=max(top_k * 3, 20),
            weights=(1.3, 0.95, 0.9),
            id_field="id",
        )
        if not fused:
            return []

        items: list[EvidenceItem] = []
        for rec in fused:
            if norm_tags:
                rtags = {str(t).lower() for t in (rec.get("tags") or [])}
                if not rtags.intersection(norm_tags):
                    continue
            items.append(self._memory_row_to_evidence(rec, query=cleaned))

        if not items:
            return []

        if apply_rerank and self.rerank_client.is_configured and len(items) > 1:
            items = await self._rerank_evidence(cleaned, items, top_n=min(len(items), max(top_k * 2, 12)))

        if apply_mmr:
            return mmr_select_evidence(items, top_k=top_k, lambda_mult=0.75, max_per_source=top_k)
        return items[:top_k]

    async def _memory_vector_leg(
        self,
        *,
        base_params: dict[str, Any],
        col_sql: str,
        q_vec_lit: str | None,
        model_tag: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not q_vec_lit:
            return []
        try:
            m_clause = "AND (me.embedding_model IS NULL OR me.embedding_model = :mtag)" if model_tag else ""
            params = {**base_params, "qvec": q_vec_lit, "lim": limit}
            if model_tag:
                params["mtag"] = model_tag
            sql = f"""
                SELECT me.id, me.collection_id, me.target, COALESCE(mc.name, me.target),
                       COALESCE(me.title, ''), me.content, COALESCE(me.tags, '[]'::jsonb), me.source, me.updated_at
                FROM memory_entries me
                LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                WHERE me.user_id = :uid
                  {col_sql}
                  AND me.embedding IS NOT NULL
                  {m_clause}
                  AND (me.embedding <=> CAST(:qvec AS vector)) < 0.72
                ORDER BY me.embedding <=> CAST(:qvec AS vector) ASC, me.updated_at DESC
                LIMIT :lim
            """
            rows = await self.db.fetch_all(sql, params, set_iterative_scan=True)
            return [self._parse_memory_row(r) for r in rows]
        except Exception as exc:
            if "embedding_model" in str(exc):
                try:
                    sql = f"""
                        SELECT me.id, me.collection_id, me.target, COALESCE(mc.name, me.target),
                               COALESCE(me.title, ''), me.content, COALESCE(me.tags, '[]'::jsonb), me.source, me.updated_at
                        FROM memory_entries me
                        LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                        WHERE me.user_id = :uid
                          {col_sql}
                          AND me.embedding IS NOT NULL
                          AND (me.embedding <=> CAST(:qvec AS vector)) < 0.72
                        ORDER BY me.embedding <=> CAST(:qvec AS vector) ASC, me.updated_at DESC
                        LIMIT :lim
                    """
                    rows = await self.db.fetch_all(
                        sql, {**base_params, "qvec": q_vec_lit, "lim": limit}, set_iterative_scan=True
                    )
                    return [self._parse_memory_row(r) for r in rows]
                except Exception:
                    return []
            logger.debug("Memory vector leg skipped: %s", exc)
            return []

    async def _memory_fts_leg(
        self,
        *,
        base_params: dict[str, Any],
        col_sql: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            sql = f"""
                SELECT me.id, me.collection_id, me.target, COALESCE(mc.name, me.target),
                       COALESCE(me.title, ''), me.content, COALESCE(me.tags, '[]'::jsonb), me.source, me.updated_at
                FROM memory_entries me
                LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                WHERE me.user_id = :uid
                  {col_sql}
                  AND me.search_tsv @@ plainto_tsquery('simple', :q)
                ORDER BY ts_rank_cd(me.search_tsv, plainto_tsquery('simple', :q)) DESC, me.updated_at DESC
                LIMIT :lim
            """
            rows = await self.db.fetch_all(sql, {**base_params, "q": query, "lim": limit})
            return [self._parse_memory_row(r) for r in rows]
        except Exception as exc:
            logger.debug("Memory FTS leg skipped: %s", exc)
            return []

    async def _memory_trgm_leg(
        self,
        *,
        base_params: dict[str, Any],
        col_sql: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        like_pat = f"%{escape_like(query)}%"
        try:
            sql = f"""
                SELECT me.id, me.collection_id, me.target, COALESCE(mc.name, me.target),
                       COALESCE(me.title, ''), me.content, COALESCE(me.tags, '[]'::jsonb), me.source, me.updated_at
                FROM memory_entries me
                LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                WHERE me.user_id = :uid
                  {col_sql}
                  AND (
                      me.content ILIKE :pat ESCAPE '\\'
                      OR me.title ILIKE :pat ESCAPE '\\'
                      OR :q <% me.content
                      OR :q <% COALESCE(me.title, '')
                  )
                ORDER BY
                    CASE WHEN me.title ILIKE :pat ESCAPE '\\' OR me.content ILIKE :pat ESCAPE '\\' THEN 0 ELSE 1 END,
                    word_similarity(:q, COALESCE(me.title, '') || ' ' || me.content) DESC,
                    me.updated_at DESC
                LIMIT :lim
            """
            rows = await self.db.fetch_all(
                sql,
                {**base_params, "q": query, "pat": like_pat, "lim": limit},
                trgm_threshold=0.14,
            )
            return [self._parse_memory_row(r) for r in rows]
        except Exception:
            try:
                sql = f"""
                    SELECT me.id, me.collection_id, me.target, COALESCE(mc.name, me.target),
                           COALESCE(me.title, ''), me.content, COALESCE(me.tags, '[]'::jsonb), me.source, me.updated_at
                    FROM memory_entries me
                    LEFT JOIN memory_collections mc ON mc.id = me.collection_id
                    WHERE me.user_id = :uid
                      {col_sql}
                      AND (me.content ILIKE :pat ESCAPE '\\' OR me.title ILIKE :pat ESCAPE '\\')
                    ORDER BY me.updated_at DESC
                    LIMIT :lim
                """
                rows = await self.db.fetch_all(sql, {**base_params, "pat": like_pat, "lim": limit})
                return [self._parse_memory_row(r) for r in rows]
            except Exception as exc:
                logger.debug("Memory ILIKE leg skipped: %s", exc)
                return []

    @staticmethod
    def _parse_memory_row(row: tuple[Any, ...]) -> dict[str, Any]:
        slug = str(row[2] or "memory")
        return {
            "id": str(row[0]),
            "collection_id": str(row[1]) if row[1] is not None else None,
            "target": slug,
            "collection": slug,
            "collection_name": str(row[3] or slug),
            "title": str(row[4] or ""),
            "content": str(row[5] or ""),
            "tags": list(row[6]) if isinstance(row[6], list) else [],
            "source": str(row[7] or "agent"),
            "updated_at": row[8].isoformat() if len(row) > 8 and hasattr(row[8], "isoformat") else None,
            "_boost": 1.12 if slug == "user" else 1.0,
        }

    @staticmethod
    def _memory_row_to_evidence(rec: dict[str, Any], *, query: str = "") -> EvidenceItem:
        col_name = str(rec.get("collection_name") or rec.get("collection") or "memory")
        title = str(rec.get("title") or "").strip() or col_name
        tags = list(rec.get("tags") or [])
        tag_str = " ".join(f"#{t}" for t in tags[:4])
        subtitle = f"记忆集：{col_name}" + (f" · {tag_str}" if tag_str else "")
        rrf = float(rec.get("rrf_score") or 0.0)
        return EvidenceItem(
            citation_id="",
            source_type="memory",
            source_id=str(rec["id"]),
            chunk_id=str(rec["id"]),
            title=title,
            subtitle=subtitle,
            content=str(rec.get("content") or ""),
            snippet=_clip_snippet(str(rec.get("content") or ""), query=query),
            score=rrf,
            rrf_score=rrf,
            vec_rank=rec.get("vec_rank"),
            fts_rank=rec.get("fts_rank"),
            trgm_rank=rec.get("trgm_rank"),
            confidence=_grade_confidence(
                rerank_score=None,
                rrf_score=rrf,
                vec_rank=rec.get("vec_rank"),
                fts_rank=rec.get("fts_rank"),
                trgm_rank=rec.get("trgm_rank"),
            ),
            metadata={
                "entry_id": str(rec["id"]),
                "collection_id": rec.get("collection_id"),
                "collection": str(rec.get("collection") or "memory"),
                "collection_name": col_name,
                "tags": tags,
                "source": str(rec.get("source") or "agent"),
                "timestamp": rec.get("updated_at"),
            },
        )

    # ------------------------------------------------------------------
    # Source 3: Cross-Chat History (`conversation_digests` + `message_chunks`)
    # Strict separate HNSW / FTS / trgm legs (no OR destroying HNSW!)
    # ------------------------------------------------------------------
    async def search_chats(
        self,
        *,
        user_id: str,
        query: str,
        scope: str = "all",
        exclude_conversation_id: str | None = None,
        top_k: int = 6,
        rrf_k: int = 60,
        apply_rerank: bool = True,
        apply_mmr: bool = True,
        q_vec_lit: str | None = None,
    ) -> list[EvidenceItem]:
        cleaned = (query or "").strip()
        if not cleaned or not self.db.is_available:
            return []
        try:
            user_uuid = uuid.UUID(str(user_id))
            excl_uuid = uuid.UUID(str(exclude_conversation_id)) if exclude_conversation_id else None
        except ValueError:
            return []

        norm_scope = (scope or "all").strip().lower()
        if norm_scope not in ("all", "side", "main"):
            norm_scope = "all"

        if q_vec_lit is None:
            q_vec_lit = await self._embed_query_once(cleaned)

        cand_k = max(top_k * 3, 18)
        model_tag = self.embedding_client.model_tag

        legs: list[Any] = [
            self._episode_vector_leg(
                user_uuid=user_uuid,
                scope=norm_scope,
                q_vec_lit=q_vec_lit,
                model_tag=model_tag,
                limit=cand_k,
            ),
            self._episode_fts_leg(user_uuid=user_uuid, scope=norm_scope, query=cleaned, limit=cand_k),
            self._episode_trgm_leg(user_uuid=user_uuid, scope=norm_scope, query=cleaned, limit=cand_k),
            self._turn_vector_leg(
                user_uuid=user_uuid,
                scope=norm_scope,
                excl_uuid=excl_uuid,
                q_vec_lit=q_vec_lit,
                model_tag=model_tag,
                limit=cand_k,
            ),
            self._turn_fts_leg(
                user_uuid=user_uuid, scope=norm_scope, excl_uuid=excl_uuid, query=cleaned, limit=cand_k
            ),
            self._turn_trgm_leg(
                user_uuid=user_uuid, scope=norm_scope, excl_uuid=excl_uuid, query=cleaned, limit=cand_k
            ),
        ]
        include_digests = norm_scope in ("all", "side")
        if include_digests:
            legs.extend(
                [
                    self._digest_vector_leg(
                        user_uuid=user_uuid,
                        excl_uuid=excl_uuid,
                        q_vec_lit=q_vec_lit,
                        model_tag=model_tag,
                        limit=cand_k,
                    ),
                    self._digest_fts_leg(user_uuid=user_uuid, excl_uuid=excl_uuid, query=cleaned, limit=cand_k),
                    self._digest_trgm_leg(user_uuid=user_uuid, excl_uuid=excl_uuid, query=cleaned, limit=cand_k),
                ]
            )

        leg_outputs = await self.db.run_legs(legs)
        episode_fused = rrf_fuse_rows(
            leg_outputs[:3], rrf_k=rrf_k, top_k=max(top_k * 2, 12), weights=(1.35, 1.05, 1.05), id_field="chunk_id"
        )
        turn_fused = rrf_fuse_rows(
            leg_outputs[3:6], rrf_k=rrf_k, top_k=max(top_k * 2, 12), weights=(1.2, 0.9, 0.95), id_field="chunk_id"
        )
        digest_fused = (
            rrf_fuse_rows(
                leg_outputs[6:9], rrf_k=rrf_k, top_k=max(top_k * 2, 10), weights=(1.2, 0.95, 1.0), id_field="chunk_id"
            )
            if include_digests
            else []
        )

        items: list[EvidenceItem] = []
        for rec in episode_fused:
            items.append(self._episode_row_to_evidence(rec, query=cleaned))
        for rec in digest_fused:
            items.append(self._digest_row_to_evidence(rec, query=cleaned))
        for rec in turn_fused:
            items.append(self._turn_row_to_evidence(rec, query=cleaned))

        items.sort(key=lambda x: x.score, reverse=True)
        if not items:
            return []

        if apply_rerank and self.rerank_client.is_configured and len(items) > 1:
            items = await self._rerank_evidence(cleaned, items, top_n=min(len(items), max(top_k * 2, 10)))

        if apply_mmr:
            return mmr_select_evidence(items, top_k=top_k, lambda_mult=0.75, max_per_source=2)
        return items[:top_k]

    async def _episode_vector_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        scope: str,
        q_vec_lit: str | None,
        model_tag: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not q_vec_lit:
            return []
        try:
            sql = """
                SELECT e.id, e.conversation_id, e.conversation_kind, e.episode_index,
                       e.topic, e.summary, e.key_facts, e.entities, e.start_msg_id, e.ended_at
                FROM conversation_episodes e
                WHERE e.user_id = :uid
                  AND e.embedding IS NOT NULL
                  AND (e.embedding <=> CAST(:qvec AS vector)) < 0.78
            """
            params: dict[str, Any] = {"uid": user_uuid, "qvec": q_vec_lit, "lim": limit}
            if model_tag:
                sql += " AND (e.embedding_model IS NULL OR e.embedding_model = :mtag)"
                params["mtag"] = model_tag
            if scope in ("side", "main"):
                sql += " AND e.conversation_kind = :kind"
                params["kind"] = scope
            sql += " ORDER BY e.embedding <=> CAST(:qvec AS vector) ASC LIMIT :lim"
            return [self._parse_episode_row(r) for r in await self.db.fetch_all(sql, params, set_iterative_scan=True)]
        except Exception as exc:
            logger.debug("Episode vector leg skipped: %s", exc)
            return []

    async def _episode_fts_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        scope: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            sql = """
                SELECT e.id, e.conversation_id, e.conversation_kind, e.episode_index,
                       e.topic, e.summary, e.key_facts, e.entities, e.start_msg_id, e.ended_at
                FROM conversation_episodes e
                WHERE e.user_id = :uid
                  AND e.search_tsv @@ plainto_tsquery('simple', :q)
            """
            params: dict[str, Any] = {"uid": user_uuid, "q": query, "lim": limit}
            if scope in ("side", "main"):
                sql += " AND e.conversation_kind = :kind"
                params["kind"] = scope
            sql += " ORDER BY ts_rank_cd(e.search_tsv, plainto_tsquery('simple', :q)) DESC, e.ended_at DESC NULLS LAST LIMIT :lim"
            return [self._parse_episode_row(r) for r in await self.db.fetch_all(sql, params)]
        except Exception as exc:
            logger.debug("Episode FTS leg skipped: %s", exc)
            return []

    async def _episode_trgm_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        scope: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if len(query) < 2:
            return []
        try:
            sql = """
                SELECT e.id, e.conversation_id, e.conversation_kind, e.episode_index,
                       e.topic, e.summary, e.key_facts, e.entities, e.start_msg_id, e.ended_at
                FROM conversation_episodes e
                WHERE e.user_id = :uid
                  AND (:q <% COALESCE(e.summary, '') OR :q <% COALESCE(e.topic, ''))
            """
            params: dict[str, Any] = {"uid": user_uuid, "q": query, "lim": limit}
            if scope in ("side", "main"):
                sql += " AND e.conversation_kind = :kind"
                params["kind"] = scope
            sql += " ORDER BY word_similarity(:q, COALESCE(e.topic, '') || ' ' || COALESCE(e.summary, '')) DESC, e.ended_at DESC NULLS LAST LIMIT :lim"
            return [self._parse_episode_row(r) for r in await self.db.fetch_all(sql, params, trgm_threshold=0.16)]
        except Exception as exc:
            logger.debug("Episode trgm leg skipped: %s", exc)
            return []

    @staticmethod
    def _parse_episode_row(row: tuple[Any, ...]) -> dict[str, Any]:
        ts = row[9] if len(row) > 9 else None
        facts = row[6] if len(row) > 6 and isinstance(row[6], list) else []
        entities = row[7] if len(row) > 7 and isinstance(row[7], list) else []
        summary = str(row[5] or "")
        body = summary
        if facts:
            body += "\n要点：" + "；".join(str(f) for f in facts[:5] if str(f).strip())
        if entities:
            body += "\n关键实体：" + "、".join(str(e) for e in entities[:8] if str(e).strip())
        return {
            "chunk_id": f"episode:{row[0]}",
            "raw_id": str(row[0]),
            "conversation_id": str(row[1]),
            "kind": str(row[2] or "main"),
            "episode_index": int(row[3] or 1),
            "title": str(row[4] or "历史情景归档"),
            "summary": summary,
            "key_facts": facts,
            "entities": entities,
            "content": body,
            "message_id": str(row[8]) if len(row) > 8 and row[8] is not None else None,
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else None,
            "_boost": _age_decay_boost(ts) * 1.12,
        }

    @staticmethod
    def _episode_row_to_evidence(rec: dict[str, Any], *, query: str = "") -> EvidenceItem:
        kind_label = "主聊" if rec.get("kind") == "main" else "旁聊"
        ts_short = str(rec.get("timestamp") or "")[:10]
        ep_idx = int(rec.get("episode_index") or 1)
        subtitle = f"{kind_label}归档片段 #{ep_idx}" + (f" · {ts_short}" if ts_short else "")
        rrf = float(rec.get("rrf_score") or 0.0)
        return EvidenceItem(
            citation_id="",
            source_type="chat_turn",
            source_id=str(rec["conversation_id"]),
            chunk_id=str(rec["chunk_id"]),
            title=str(rec.get("title") or f"{kind_label}归档 #{ep_idx}"),
            subtitle=subtitle,
            content=str(rec.get("content") or ""),
            snippet=_clip_snippet(str(rec.get("summary") or rec.get("content") or ""), query=query),
            score=rrf,
            rrf_score=rrf,
            vec_rank=rec.get("vec_rank"),
            fts_rank=rec.get("fts_rank"),
            trgm_rank=rec.get("trgm_rank"),
            confidence=_grade_confidence(
                rerank_score=None,
                rrf_score=rrf,
                vec_rank=rec.get("vec_rank"),
                fts_rank=rec.get("fts_rank"),
                trgm_rank=rec.get("trgm_rank"),
            ),
            metadata={
                "episode_id": str(rec.get("raw_id") or ""),
                "conversation_id": str(rec["conversation_id"]),
                "conversation_title": str(rec.get("title") or ""),
                "kind": str(rec.get("kind") or "main"),
                "message_id": rec.get("message_id"),
                "key_facts": rec.get("key_facts") or [],
                "entities": rec.get("entities") or [],
                "timestamp": rec.get("timestamp"),
            },
        )

    async def _turn_vector_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        scope: str,
        excl_uuid: uuid.UUID | None,
        q_vec_lit: str | None,
        model_tag: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not q_vec_lit:
            return []
        try:
            sql = """
                SELECT mc.id, mc.conversation_id, mc.conversation_kind,
                       COALESCE(c.title, '') AS title, mc.context_header, mc.content,
                       mc.start_msg_id, mc.created_at
                FROM message_chunks mc
                INNER JOIN conversations c ON c.id = mc.conversation_id
                WHERE mc.user_id = :uid
                  AND mc.embedding IS NOT NULL
                  AND (mc.embedding <=> CAST(:qvec AS vector)) < 0.75
            """
            params: dict[str, Any] = {"uid": user_uuid, "qvec": q_vec_lit, "lim": limit}
            if model_tag:
                sql += " AND (mc.embedding_model IS NULL OR mc.embedding_model = :mtag)"
                params["mtag"] = model_tag
            if scope in ("side", "main"):
                sql += " AND mc.conversation_kind = :kind"
                params["kind"] = scope
            if excl_uuid is not None:
                sql += " AND mc.conversation_id <> :excl"
                params["excl"] = excl_uuid
            sql += " ORDER BY mc.embedding <=> CAST(:qvec AS vector) ASC LIMIT :lim"
            rows = await self.db.fetch_all(sql, params, set_iterative_scan=True)
            return [self._parse_turn_row(r) for r in rows]
        except Exception as exc:
            if "embedding_model" in str(exc):
                return await self._turn_vector_leg(
                    user_uuid=user_uuid,
                    scope=scope,
                    excl_uuid=excl_uuid,
                    q_vec_lit=q_vec_lit,
                    model_tag="",
                    limit=limit,
                )
            logger.debug("Turn vector leg skipped: %s", exc)
            return []

    async def _turn_fts_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        scope: str,
        excl_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            sql = """
                SELECT mc.id, mc.conversation_id, mc.conversation_kind,
                       COALESCE(c.title, '') AS title, mc.context_header, mc.content,
                       mc.start_msg_id, mc.created_at
                FROM message_chunks mc
                INNER JOIN conversations c ON c.id = mc.conversation_id
                WHERE mc.user_id = :uid
                  AND mc.search_tsv @@ plainto_tsquery('simple', :q)
            """
            params: dict[str, Any] = {"uid": user_uuid, "q": query, "lim": limit}
            if scope in ("side", "main"):
                sql += " AND mc.conversation_kind = :kind"
                params["kind"] = scope
            if excl_uuid is not None:
                sql += " AND mc.conversation_id <> :excl"
                params["excl"] = excl_uuid
            sql += " ORDER BY ts_rank_cd(mc.search_tsv, plainto_tsquery('simple', :q)) DESC, mc.created_at DESC LIMIT :lim"
            return [self._parse_turn_row(r) for r in await self.db.fetch_all(sql, params)]
        except Exception as exc:
            logger.debug("Turn FTS leg skipped: %s", exc)
            return []

    async def _turn_trgm_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        scope: str,
        excl_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if len(query) < 2:
            return []
        try:
            sql = """
                SELECT mc.id, mc.conversation_id, mc.conversation_kind,
                       COALESCE(c.title, '') AS title, mc.context_header, mc.content,
                       mc.start_msg_id, mc.created_at
                FROM message_chunks mc
                INNER JOIN conversations c ON c.id = mc.conversation_id
                WHERE mc.user_id = :uid
                  AND :q <% mc.content
            """
            params: dict[str, Any] = {"uid": user_uuid, "q": query, "lim": limit}
            if scope in ("side", "main"):
                sql += " AND mc.conversation_kind = :kind"
                params["kind"] = scope
            if excl_uuid is not None:
                sql += " AND mc.conversation_id <> :excl"
                params["excl"] = excl_uuid
            sql += " ORDER BY word_similarity(:q, mc.content) DESC, mc.created_at DESC LIMIT :lim"
            return [self._parse_turn_row(r) for r in await self.db.fetch_all(sql, params, trgm_threshold=0.16)]
        except Exception as exc:
            logger.debug("Turn trgm leg skipped: %s", exc)
            return []

    async def _digest_vector_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        excl_uuid: uuid.UUID | None,
        q_vec_lit: str | None,
        model_tag: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not q_vec_lit:
            return []
        try:
            sql = """
                SELECT d.id, d.conversation_id, d.title, d.summary, d.key_facts, d.last_message_at
                FROM conversation_digests d
                WHERE d.user_id = :uid
                  AND d.embedding IS NOT NULL
                  AND (d.embedding <=> CAST(:qvec AS vector)) < 0.78
            """
            params: dict[str, Any] = {"uid": user_uuid, "qvec": q_vec_lit, "lim": limit}
            if model_tag:
                sql += " AND (d.embedding_model IS NULL OR d.embedding_model = :mtag)"
                params["mtag"] = model_tag
            if excl_uuid is not None:
                sql += " AND d.conversation_id <> :excl"
                params["excl"] = excl_uuid
            sql += " ORDER BY d.embedding <=> CAST(:qvec AS vector) ASC LIMIT :lim"
            return [self._parse_digest_row(r) for r in await self.db.fetch_all(sql, params, set_iterative_scan=True)]
        except Exception as exc:
            if "embedding_model" in str(exc):
                return await self._digest_vector_leg(
                    user_uuid=user_uuid, excl_uuid=excl_uuid, q_vec_lit=q_vec_lit, model_tag="", limit=limit
                )
            logger.debug("Digest vector leg skipped: %s", exc)
            return []

    async def _digest_fts_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        excl_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            sql = """
                SELECT d.id, d.conversation_id, d.title, d.summary, d.key_facts, d.last_message_at
                FROM conversation_digests d
                WHERE d.user_id = :uid
                  AND d.search_tsv @@ plainto_tsquery('simple', :q)
            """
            params: dict[str, Any] = {"uid": user_uuid, "q": query, "lim": limit}
            if excl_uuid is not None:
                sql += " AND d.conversation_id <> :excl"
                params["excl"] = excl_uuid
            sql += " ORDER BY ts_rank_cd(d.search_tsv, plainto_tsquery('simple', :q)) DESC LIMIT :lim"
            return [self._parse_digest_row(r) for r in await self.db.fetch_all(sql, params)]
        except Exception as exc:
            logger.debug("Digest FTS leg skipped: %s", exc)
            return []

    async def _digest_trgm_leg(
        self,
        *,
        user_uuid: uuid.UUID,
        excl_uuid: uuid.UUID | None,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if len(query) < 2:
            return []
        like_pat = f"%{escape_like(query)}%"
        try:
            sql = """
                SELECT d.id, d.conversation_id, d.title, d.summary, d.key_facts, d.last_message_at
                FROM conversation_digests d
                WHERE d.user_id = :uid
                  AND (
                      d.title ILIKE :pat ESCAPE '\\'
                      OR d.summary ILIKE :pat ESCAPE '\\'
                      OR :q <% d.summary
                  )
            """
            params: dict[str, Any] = {"uid": user_uuid, "q": query, "pat": like_pat, "lim": limit}
            if excl_uuid is not None:
                sql += " AND d.conversation_id <> :excl"
                params["excl"] = excl_uuid
            sql += " ORDER BY word_similarity(:q, d.summary) DESC, d.last_message_at DESC NULLS LAST LIMIT :lim"
            return [self._parse_digest_row(r) for r in await self.db.fetch_all(sql, params, trgm_threshold=0.16)]
        except Exception:
            try:
                sql = """
                    SELECT d.id, d.conversation_id, d.title, d.summary, d.key_facts, d.last_message_at
                    FROM conversation_digests d
                    WHERE d.user_id = :uid
                      AND (d.title ILIKE :pat ESCAPE '\\' OR d.summary ILIKE :pat ESCAPE '\\')
                """
                params = {"uid": user_uuid, "pat": like_pat, "lim": limit}
                if excl_uuid is not None:
                    sql += " AND d.conversation_id <> :excl"
                    params["excl"] = excl_uuid
                sql += " ORDER BY d.last_message_at DESC NULLS LAST LIMIT :lim"
                return [self._parse_digest_row(r) for r in await self.db.fetch_all(sql, params)]
            except Exception:
                return []

    @staticmethod
    def _parse_turn_row(row: tuple[Any, ...]) -> dict[str, Any]:
        ts = row[7] if len(row) > 7 else None
        return {
            "chunk_id": f"turn:{row[0]}",
            "raw_id": str(row[0]),
            "conversation_id": str(row[1]),
            "kind": str(row[2] or "side"),
            "title": str(row[3] or ""),
            "context_header": str(row[4] or ""),
            "content": str(row[5] or ""),
            "message_id": str(row[6]) if len(row) > 6 and row[6] is not None else None,
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else None,
            "_boost": _age_decay_boost(ts),
        }

    @staticmethod
    def _parse_digest_row(row: tuple[Any, ...]) -> dict[str, Any]:
        ts = row[5] if len(row) > 5 else None
        facts = row[4] if isinstance(row[4], list) else []
        summary = str(row[3] or "")
        body = summary
        if facts:
            body += "\n要点：" + "；".join(str(f) for f in facts[:5] if str(f).strip())
        return {
            "chunk_id": f"digest:{row[1]}",
            "raw_id": str(row[0]),
            "conversation_id": str(row[1]),
            "kind": "side",
            "title": str(row[2] or "未命名旁聊"),
            "summary": summary,
            "key_facts": facts,
            "content": body,
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else None,
            "_boost": _age_decay_boost(ts),
        }

    @staticmethod
    def _turn_row_to_evidence(rec: dict[str, Any], *, query: str = "") -> EvidenceItem:
        kind_label = "主聊" if rec.get("kind") == "main" else "旁聊"
        ts_short = str(rec.get("timestamp") or "")[:10]
        subtitle = f"{kind_label}对话片段" + (f" · {ts_short}" if ts_short else "")
        rrf = float(rec.get("rrf_score") or 0.0)
        return EvidenceItem(
            citation_id="",
            source_type="chat_turn",
            source_id=str(rec["conversation_id"]),
            chunk_id=str(rec["chunk_id"]),
            title=str(rec.get("title") or kind_label),
            subtitle=subtitle,
            content=str(rec.get("content") or ""),
            snippet=_clip_snippet(str(rec.get("content") or ""), query=query),
            score=rrf,
            rrf_score=rrf,
            vec_rank=rec.get("vec_rank"),
            fts_rank=rec.get("fts_rank"),
            trgm_rank=rec.get("trgm_rank"),
            confidence=_grade_confidence(
                rerank_score=None,
                rrf_score=rrf,
                vec_rank=rec.get("vec_rank"),
                fts_rank=rec.get("fts_rank"),
                trgm_rank=rec.get("trgm_rank"),
            ),
            metadata={
                "conversation_id": str(rec["conversation_id"]),
                "conversation_title": str(rec.get("title") or ""),
                "kind": str(rec.get("kind") or "side"),
                "message_id": rec.get("message_id"),
                "context_header": str(rec.get("context_header") or ""),
                "timestamp": rec.get("timestamp"),
            },
        )

    @staticmethod
    def _digest_row_to_evidence(rec: dict[str, Any], *, query: str = "") -> EvidenceItem:
        ts_short = str(rec.get("timestamp") or "")[:10]
        subtitle = "历史旁聊摘要" + (f" · {ts_short}" if ts_short else "")
        rrf = float(rec.get("rrf_score") or 0.0)
        return EvidenceItem(
            citation_id="",
            source_type="chat_digest",
            source_id=str(rec["conversation_id"]),
            chunk_id=str(rec["chunk_id"]),
            title=str(rec.get("title") or "未命名旁聊"),
            subtitle=subtitle,
            content=str(rec.get("content") or ""),
            snippet=_clip_snippet(str(rec.get("summary") or rec.get("content") or ""), query=query),
            score=rrf,
            rrf_score=rrf,
            vec_rank=rec.get("vec_rank"),
            fts_rank=rec.get("fts_rank"),
            trgm_rank=rec.get("trgm_rank"),
            confidence=_grade_confidence(
                rerank_score=None,
                rrf_score=rrf,
                vec_rank=rec.get("vec_rank"),
                fts_rank=rec.get("fts_rank"),
                trgm_rank=rec.get("trgm_rank"),
            ),
            metadata={
                "conversation_id": str(rec["conversation_id"]),
                "conversation_title": str(rec.get("title") or ""),
                "kind": "side",
                "key_facts": rec.get("key_facts") or [],
                "timestamp": rec.get("timestamp"),
            },
        )

    # ------------------------------------------------------------------
    # Unified Rerank & Multi-Source Orchestration + Corrective Retry
    # ------------------------------------------------------------------
    async def _rerank_evidence(
        self,
        query: str,
        items: list[EvidenceItem],
        *,
        top_n: int,
    ) -> list[EvidenceItem]:
        if not self.rerank_client.is_configured or len(items) <= 1:
            return items
        docs = [f"[{it.source_type} | {it.title} | {it.subtitle}]\n{it.content}" for it in items]
        reranked = await self.rerank_client.rerank(query, docs, top_n=min(len(items), top_n))
        if not reranked:
            return items
        reordered: list[EvidenceItem] = []
        for idx, score in reranked:
            if score < 0.01 and len(reordered) >= 2:
                continue
            item = items[idx]
            item.rerank_score = float(score)
            item.score = float(score)
            item.confidence = _grade_confidence(
                rerank_score=float(score),
                rrf_score=item.rrf_score,
                vec_rank=item.vec_rank,
                fts_rank=item.fts_rank,
                trgm_rank=item.trgm_rank,
            )
            reordered.append(item)
        return reordered if reordered else items

    async def _document_summary_fallback(
        self,
        *,
        user_uuid: uuid.UUID,
        file_uuids: Sequence[uuid.UUID] | None,
        limit: int = 3,
    ) -> list[EvidenceItem]:
        """Fallback to document-level summaries when chunk-level retrieval misses."""
        try:
            sql = """
                SELECT id, filename, summary, category, indexed_chunks
                FROM conversation_files
                WHERE user_id = :uid AND status = 'ready' AND COALESCE(summary, '') <> ''
            """
            params: dict[str, Any] = {"uid": user_uuid, "lim": limit}
            if file_uuids:
                sql += " AND id = ANY(:fids)"
                params["fids"] = list(file_uuids)
            sql += " ORDER BY updated_at DESC LIMIT :lim"
            rows = await self.db.fetch_all(sql, params)
            out: list[EvidenceItem] = []
            for r in rows:
                summary_text = str(r[2] or "").strip()
                if not summary_text:
                    continue
                out.append(
                    EvidenceItem(
                        citation_id="",
                        source_type="file",
                        source_id=str(r[0]),
                        chunk_id=f"summary:{r[0]}",
                        title=str(r[1] or ""),
                        subtitle="文档摘要",
                        content=summary_text,
                        snippet=_clip_snippet(summary_text, limit=240),
                        score=0.012,
                        rrf_score=0.012,
                        confidence="low",
                        metadata={
                            "file_id": str(r[0]),
                            "filename": str(r[1] or ""),
                            "locator": "文档摘要",
                            "chunk_type": "summary",
                            "indexed_chunks": int(r[4] or 0),
                        },
                    )
                )
            return out
        except Exception:
            return []

    async def search_unified(
        self,
        *,
        user_id: str,
        queries: Sequence[str],
        sources: Sequence[str] = ("file", "memory", "chat"),
        conversation_id: str = "",
        attached_file_ids: Sequence[str] | None = None,
        file_id: str | None = None,
        file_ids: Sequence[str] | None = None,
        collection: str | None = None,
        exclude_current_chat: bool = True,
        top_k: int = 8,
        per_source_k: int = 6,
        expand_neighbors: bool = True,
        enable_corrective: bool = True,
        citation_start_index: int = 1,
        stage: str = "prefetch",
    ) -> tuple[list[EvidenceItem], RagDiagnostics]:
        t0 = time.monotonic()
        clean_queries = [q.strip() for q in queries if (q or "").strip()]
        norm_sources = [s.strip().lower() for s in sources if s.strip().lower() in ("file", "memory", "chat")]
        diag = RagDiagnostics(stage=stage, rewritten_queries=clean_queries, sources_searched=norm_sources)

        if not clean_queries or not norm_sources or not self.db.is_available:
            diag.skipped_reason = "empty_query_or_no_sources"
            return [], diag

        try:
            user_uuid = uuid.UUID(str(user_id))
        except ValueError:
            diag.skipped_reason = "invalid_user_id"
            return [], diag

        primary_query = clean_queries[0]

        async def _run_pass(q_list: list[str]) -> list[EvidenceItem]:
            merged: dict[str, EvidenceItem] = {}
            for q in q_list[:3]:
                q_vec_lit = await self._embed_query_once(q)
                tasks: list[Any] = []
                if "file" in norm_sources:
                    tasks.append(
                        self.search_files(
                            user_id=user_id,
                            query=q,
                            conversation_id=conversation_id,
                            attached_file_ids=attached_file_ids,
                            file_id=file_id,
                            file_ids=file_ids,
                            top_k=per_source_k,
                            expand_neighbors=False,
                            apply_rerank=False,
                            apply_mmr=False,
                            q_vec_lit=q_vec_lit,
                        )
                    )
                if "memory" in norm_sources:
                    tasks.append(
                        self.search_memories(
                            user_id=user_id,
                            query=q,
                            collection=collection,
                            top_k=per_source_k,
                            apply_rerank=False,
                            apply_mmr=False,
                            q_vec_lit=q_vec_lit,
                        )
                    )
                if "chat" in norm_sources:
                    tasks.append(
                        self.search_chats(
                            user_id=user_id,
                            query=q,
                            scope="all",
                            exclude_conversation_id=conversation_id if exclude_current_chat else None,
                            top_k=per_source_k,
                            apply_rerank=False,
                            apply_mmr=False,
                            q_vec_lit=q_vec_lit,
                        )
                    )
                batches = await self.db.run_legs(tasks)
                for batch in batches:
                    for item in batch:
                        key = item.dedup_key()
                        existing = merged.get(key)
                        if existing is None or item.score > existing.score:
                            merged[key] = item
            return sorted(merged.values(), key=lambda it: it.score, reverse=True)

        candidates = await _run_pass(clean_queries)

        # Stage-2: Unified Cross-Source Rerank
        if self.rerank_client.is_configured and len(candidates) > 1:
            candidates = await self._rerank_evidence(
                primary_query,
                candidates,
                top_n=min(len(candidates), max(top_k * 2, 14)),
            )

        # Corrective RAG: if empty or all candidates are low confidence, retry with simplified keywords / doc summary
        has_strong = any(c.confidence in ("high", "medium") for c in candidates)
        if enable_corrective and not has_strong:
            simplified = _extract_simplified_query(primary_query)
            if simplified and simplified.lower() != primary_query.lower():
                diag.corrective_retries += 1
                retry_cands = await _run_pass([simplified])
                if self.rerank_client.is_configured and len(retry_cands) > 1:
                    retry_cands = await self._rerank_evidence(
                        primary_query, retry_cands, top_n=min(len(retry_cands), max(top_k * 2, 12))
                    )
                existing_keys = {c.dedup_key() for c in candidates}
                for rc in retry_cands:
                    if rc.dedup_key() not in existing_keys:
                        candidates.append(rc)
                        existing_keys.add(rc.dedup_key())
                candidates.sort(key=lambda it: it.score, reverse=True)

            if not candidates and "file" in norm_sources:
                target_fids: list[uuid.UUID] = []
                for rf in ([file_id] if file_id else []) + list(file_ids or []) + list(attached_file_ids or []):
                    try:
                        if rf:
                            target_fids.append(uuid.UUID(str(rf)))
                    except ValueError:
                        pass
                diag.corrective_retries += 1
                candidates.extend(
                    await self._document_summary_fallback(
                        user_uuid=user_uuid, file_uuids=target_fids or None, limit=3
                    )
                )

        selected = mmr_select_evidence(
            candidates,
            top_k=top_k,
            lambda_mult=0.75,
            max_per_source=max(3, top_k // 2 + 1),
        )

        if expand_neighbors and any(it.source_type == "file" for it in selected):
            await self._expand_file_neighbors(user_uuid=user_uuid, items=selected)

        # Assign stable citation IDs S{n}
        hits_by_source: dict[str, int] = {}
        for offset, item in enumerate(selected):
            item.citation_id = f"S{citation_start_index + offset}"
            hits_by_source[item.source_type] = hits_by_source.get(item.source_type, 0) + 1

        if "file" in norm_sources:
            att_uuids: list[uuid.UUID] = []
            for rf in ([file_id] if file_id else []) + list(file_ids or []) + list(attached_file_ids or []):
                try:
                    if rf:
                        att_uuids.append(uuid.UUID(str(rf)))
                except ValueError:
                    pass
            diag.indexing_files = await self.list_indexing_files(
                user_uuid=user_uuid, file_uuids=att_uuids or None
            )

        diag.hits_by_source = hits_by_source
        diag.top_score = selected[0].score if selected else 0.0
        diag.latency_ms = (time.monotonic() - t0) * 1000.0
        return selected, diag

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

from whitz_rag import (
    EvidenceItem,
    UnifiedKnowledgeRetriever,
    char_trigrams,
    jaccard_sim,
    rrf_fuse_rows,
)

from app.core.models import EmbeddingClient, RerankClient

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
    trgm_rank: int | None = None
    rerank_score: float | None = None
    context_header: str = ""
    section_path: str = ""
    chunk_type: str = "text"
    expanded: bool = False
    citation_id: str = ""
    confidence: str = "medium"

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
            "confidence": self.confidence,
            "expanded": self.expanded,
        }
        if self.citation_id:
            out["citation_id"] = self.citation_id
        if self.context_header:
            out["context_header"] = self.context_header
        if self.section_path:
            out["section_path"] = self.section_path
        if self.chunk_type and self.chunk_type != "text":
            out["chunk_type"] = self.chunk_type
        if self.rerank_score is not None:
            out["rerank_score"] = round(self.rerank_score, 6)
        return out


def rrf_fuse(
    ranked_lists: Sequence[Sequence[dict[str, Any]]],
    *,
    rrf_k: int = 60,
    top_k: int = 8,
    weights: Sequence[float] | None = None,
) -> list[RetrievedChunk]:
    """Backward-compatible wrapper around shared `rrf_fuse_rows` returning `RetrievedChunk` objects."""
    rows = rrf_fuse_rows(ranked_lists, rrf_k=rrf_k, top_k=top_k, weights=weights, id_field="chunk_id")
    return [
        RetrievedChunk(
            chunk_id=str(rec["chunk_id"]),
            file_id=str(rec["file_id"]),
            filename=str(rec.get("filename") or ""),
            conversation_id=str(rec["conversation_id"]) if rec.get("conversation_id") else None,
            is_global=bool(rec.get("is_global", True)),
            chunk_index=int(rec.get("chunk_index") or 0),
            locator=str(rec.get("locator") or ""),
            content=str(rec.get("content") or ""),
            rrf_score=float(rec.get("rrf_score") or 0.0),
            vec_rank=rec.get("vec_rank"),
            fts_rank=rec.get("fts_rank"),
            trgm_rank=rec.get("trgm_rank"),
            context_header=str(rec.get("context_header") or ""),
            section_path=str(rec.get("section_path") or ""),
            chunk_type=str(rec.get("chunk_type") or "text"),
        )
        for rec in rows
    ]


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
    trigrams = [char_trigrams(c.content[:800]) for c in candidates]
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
            redundancy = max((jaccard_sim(trigrams[idx], trigrams[s]) for s in selected), default=0.0)
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


def _evidence_to_chunk_dict(ev: EvidenceItem) -> dict[str, Any]:
    meta = ev.metadata or {}
    return RetrievedChunk(
        chunk_id=ev.chunk_id,
        file_id=str(meta.get("file_id") or ev.source_id),
        filename=str(meta.get("filename") or ev.title),
        conversation_id=meta.get("conversation_id"),
        is_global=bool(meta.get("is_global", True)),
        chunk_index=int(meta.get("chunk_index") or 0),
        locator=str(meta.get("locator") or ev.subtitle),
        content=ev.content,
        rrf_score=ev.rrf_score,
        vec_rank=ev.vec_rank,
        fts_rank=ev.fts_rank,
        trgm_rank=ev.trgm_rank,
        rerank_score=ev.rerank_score,
        context_header=str(meta.get("context_header") or ""),
        section_path=str(meta.get("section_path") or ""),
        chunk_type=str(meta.get("chunk_type") or "text"),
        expanded=ev.expanded,
        citation_id=ev.citation_id,
        confidence=ev.confidence,
    ).to_dict()


class HybridRetriever:
    """Agent-side facade over the shared ``UnifiedKnowledgeRetriever``."""

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
        self.engine = UnifiedKnowledgeRetriever(
            pool=pool,
            embedding_client=self.embedding_client,
            rerank_client=self.rerank_client,
        )

    async def search(
        self,
        *,
        user_id: str,
        conversation_id: str = "",
        query: str,
        file_id: str | None = None,
        attached_file_ids: Sequence[str] | None = None,
        top_k: int = 8,
        rrf_k: int = 60,
        expand_neighbors: bool = True,
    ) -> list[dict[str, Any]]:
        items = await self.engine.search_files(
            user_id=user_id,
            query=query,
            conversation_id=conversation_id,
            attached_file_ids=attached_file_ids,
            file_id=file_id,
            top_k=top_k,
            rrf_k=rrf_k,
            expand_neighbors=expand_neighbors,
        )
        return [_evidence_to_chunk_dict(it) for it in items]

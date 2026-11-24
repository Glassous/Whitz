from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceType = Literal["file", "memory", "chat_digest", "chat_turn"]
ConfidenceLevel = Literal["high", "medium", "low"]
RagMode = Literal["auto", "files_only", "off"]


@dataclass
class RagScope:
    """User/turn-level RAG retrieval control."""

    mode: RagMode = "auto"
    file_ids: list[str] = field(default_factory=list)
    include_memory: bool = True
    include_chats: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "RagScope":
        if not isinstance(raw, dict):
            return cls()
        mode_raw = str(raw.get("mode") or "auto").strip().lower()
        mode: RagMode = mode_raw if mode_raw in ("auto", "files_only", "off") else "auto"  # type: ignore[assignment]
        raw_fids = raw.get("file_ids") or []
        file_ids = [str(f).strip() for f in raw_fids if str(f).strip()] if isinstance(raw_fids, list) else []
        include_memory = True if raw.get("include_memory") is None else bool(raw.get("include_memory"))
        include_chats = True if raw.get("include_chats") is None else bool(raw.get("include_chats"))
        if mode == "files_only":
            include_memory = False
            include_chats = False
        elif mode == "off":
            include_memory = False
            include_chats = False
        return cls(
            mode=mode,
            file_ids=file_ids,
            include_memory=include_memory,
            include_chats=include_chats,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "file_ids": list(self.file_ids),
            "include_memory": self.include_memory,
            "include_chats": self.include_chats,
        }


@dataclass
class EvidenceItem:
    """Unified evidence item across files, long-term memories, and cross-chat history."""

    citation_id: str
    source_type: SourceType
    source_id: str
    chunk_id: str
    title: str
    subtitle: str
    content: str
    snippet: str
    score: float
    confidence: ConfidenceLevel = "medium"
    rerank_score: float | None = None
    rrf_score: float = 0.0
    vec_rank: int | None = None
    fts_rank: int | None = None
    trgm_rank: int | None = None
    expanded: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def dedup_key(self) -> str:
        return f"{self.source_type}:{self.chunk_id or self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "citation_id": self.citation_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "content": self.content,
            "snippet": self.snippet,
            "score": round(float(self.score), 6),
            "rrf_score": round(float(self.rrf_score), 6),
            "confidence": self.confidence,
            "expanded": self.expanded,
            "metadata": dict(self.metadata),
        }
        if self.rerank_score is not None:
            out["rerank_score"] = round(float(self.rerank_score), 6)
        if self.vec_rank is not None:
            out["vec_rank"] = self.vec_rank
        if self.fts_rank is not None:
            out["fts_rank"] = self.fts_rank
        if self.trgm_rank is not None:
            out["trgm_rank"] = self.trgm_rank
        return out

    def to_citation_dict(self) -> dict[str, Any]:
        """Compact citation payload persisted in message tool_payload and streamed to frontend."""
        return {
            "citation_id": self.citation_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "snippet": self.snippet[:320],
            "score": round(float(self.score), 4),
            "confidence": self.confidence,
            "metadata": {
                k: v
                for k, v in self.metadata.items()
                if k
                in (
                    "file_id",
                    "filename",
                    "locator",
                    "section_path",
                    "chunk_index",
                    "chunk_type",
                    "chunk_meta",
                    "conversation_id",
                    "conversation_title",
                    "collection",
                    "collection_name",
                    "message_id",
                    "tags",
                    "timestamp",
                )
            },
        }


@dataclass
class RagDiagnostics:
    """Telemetry and diagnostic context for a retrieval run."""

    stage: str = "prefetch"
    rewritten_queries: list[str] = field(default_factory=list)
    sources_searched: list[str] = field(default_factory=list)
    hits_by_source: dict[str, int] = field(default_factory=dict)
    top_score: float = 0.0
    latency_ms: float = 0.0
    corrective_retries: int = 0
    indexing_files: list[dict[str, Any]] = field(default_factory=list)
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "rewritten_queries": list(self.rewritten_queries),
            "sources_searched": list(self.sources_searched),
            "hits_by_source": dict(self.hits_by_source),
            "top_score": round(float(self.top_score), 4),
            "latency_ms": round(float(self.latency_ms), 1),
            "corrective_retries": int(self.corrective_retries),
            "indexing_files": list(self.indexing_files),
            "skipped_reason": self.skipped_reason,
        }

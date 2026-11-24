from __future__ import annotations

from typing import Any, Sequence

from whitz_rag.types import EvidenceItem


class CitationRegistry:
    """Per-run deduplicated citation registry shared across `rag_prefetch`, tools, and subgraphs."""

    def __init__(self) -> None:
        self._by_key: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

    def register(self, items: Sequence[EvidenceItem]) -> list[dict[str, Any]]:
        """Register EvidenceItems, mutating their `citation_id` to a stable `S{n}` and returning new/updated dicts."""
        registered: list[dict[str, Any]] = []
        for item in items:
            key = item.dedup_key()
            existing = self._by_key.get(key)
            if existing is not None:
                item.citation_id = str(existing["citation_id"])
                if item.score > float(existing.get("score") or 0.0):
                    updated = item.to_citation_dict()
                    updated["citation_id"] = item.citation_id
                    self._by_key[key] = updated
                    existing = updated
                registered.append(existing)
            else:
                cid = f"S{len(self._order) + 1}"
                item.citation_id = cid
                cite_dict = item.to_citation_dict()
                cite_dict["citation_id"] = cid
                self._by_key[key] = cite_dict
                self._order.append(key)
                registered.append(cite_dict)
        return registered

    def all_citations(self) -> list[dict[str, Any]]:
        return [self._by_key[k] for k in self._order if k in self._by_key]

    @property
    def next_index(self) -> int:
        return len(self._order) + 1


def emit_rag_context_event(
    *,
    stage: str,
    citations: list[dict[str, Any]],
    diagnostics: dict[str, Any] | None = None,
) -> None:
    """Emit a live `rag.context` custom event through LangGraph stream writer."""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer(
            {
                "type": "rag.context",
                "stage": stage,
                "citations": citations,
                "diagnostics": diagnostics or {},
            }
        )
    except Exception:
        pass

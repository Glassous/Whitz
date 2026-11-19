from __future__ import annotations

import logging
import math
from typing import Sequence

import httpx

from app.core.config import get_settings

logger = logging.getLogger("whitz.embeddings")


def fit_embedding(vec: Sequence[float], dim: int = 1536) -> list[float]:
    values = [float(x) for x in vec[:dim]]
    if len(values) < dim:
        values.extend([0.0] * (dim - len(values)))
    norm = math.sqrt(sum(v * v for v in values))
    if norm > 0.0:
        return [v / norm for v in values]
    return values


def _embeddings_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if cleaned.endswith("/embeddings"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/embeddings"
    return f"{cleaned}/v1/embeddings"


def is_embedding_configured() -> bool:
    s = get_settings()
    base = (s.embedding_base_url or s.llm_base_url or "").strip()
    model = (s.embedding_model or "").strip()
    return bool(base and model)


async def embed_texts(texts: Sequence[str]) -> list[list[float]] | None:
    """Return L2-normalized embeddings if remote embedding model is configured, else None."""
    items = [str(t or "") for t in texts]
    if not items or not is_embedding_configured():
        return None
    s = get_settings()
    base = (s.embedding_base_url or s.llm_base_url or "").strip()
    api_key = (s.embedding_api_key or s.llm_api_key or "").strip()
    model = (s.embedding_model or "").strip()
    dim = max(1, int(s.embedding_dimensions or 1536))
    url = _embeddings_url(base)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(s.embedding_timeout_seconds),
            trust_env=False,
        ) as client:
            resp = await client.post(url, headers=headers, json={"model": model, "input": items})
            resp.raise_for_status()
            payload = resp.json()
        data = payload.get("data") or []
        ordered = sorted(data, key=lambda row: int(row.get("index", 0)))
        if len(ordered) != len(items):
            return None
        return [fit_embedding(row["embedding"], dim=dim) for row in ordered]
    except Exception as exc:
        logger.warning("Embedding request failed (%s); storing chunks without vector", exc)
        return None

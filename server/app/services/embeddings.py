from __future__ import annotations

import logging
from typing import Sequence

from whitz_rag.embeddings import (
    EmbeddingClient,
    RerankClient,
    aclose_shared_rag_clients,
    fit_embedding,
)

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger("whitz.embeddings")


async def aclose_embedding_client() -> None:
    await aclose_shared_rag_clients()


def is_embedding_configured() -> bool:
    s = get_settings()
    base = (s.embedding_base_url or "").strip()
    model = (s.embedding_model or "").strip()
    return bool(base and model)


def current_embedding_model_tag() -> str:
    s = get_settings()
    model = (s.embedding_model or "").strip()
    dim = max(1, int(s.embedding_dimensions or 1536))
    return f"{model}@{dim}" if model else ""


def get_embedding_client() -> EmbeddingClient:
    s = get_settings()
    redis = None
    try:
        redis = get_redis()
    except Exception:
        redis = None
    return EmbeddingClient.from_settings(s, redis_client=redis)


def get_rerank_client() -> RerankClient:
    s = get_settings()
    redis = None
    try:
        redis = get_redis()
    except Exception:
        redis = None
    return RerankClient.from_settings(s, redis_client=redis)


async def embed_texts(texts: Sequence[str]) -> list[list[float]] | None:
    """Return L2-normalized embeddings using shared EmbeddingClient (dimensions negotiation, retry, Redis cache)."""
    if not texts or not is_embedding_configured():
        return None
    client = get_embedding_client()
    return await client.embed_texts(texts)


__all__ = [
    "EmbeddingClient",
    "RerankClient",
    "aclose_embedding_client",
    "current_embedding_model_tag",
    "embed_texts",
    "fit_embedding",
    "get_embedding_client",
    "get_rerank_client",
    "is_embedding_configured",
]

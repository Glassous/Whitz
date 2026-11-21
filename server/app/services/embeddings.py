from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from typing import Sequence

import httpx

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger("whitz.embeddings")

_SHARED_EMB_CLIENT: httpx.AsyncClient | None = None


def _get_emb_client(timeout_seconds: float) -> httpx.AsyncClient:
    global _SHARED_EMB_CLIENT
    if _SHARED_EMB_CLIENT is None or _SHARED_EMB_CLIENT.is_closed:
        _SHARED_EMB_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=12, keepalive_expiry=30.0),
            trust_env=False,
        )
    return _SHARED_EMB_CLIENT


async def aclose_embedding_client() -> None:
    global _SHARED_EMB_CLIENT
    if _SHARED_EMB_CLIENT is not None and not _SHARED_EMB_CLIENT.is_closed:
        try:
            await _SHARED_EMB_CLIENT.aclose()
        except Exception:
            pass
    _SHARED_EMB_CLIENT = None


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


def _cache_key(model: str, dim: int, text: str) -> str:
    digest = hashlib.sha256(f"{model}|{dim}|{text}".encode("utf-8")).hexdigest()[:32]
    return f"emb:cache:{digest}"


def is_embedding_configured() -> bool:
    s = get_settings()
    base = (s.embedding_base_url or "").strip()
    model = (s.embedding_model or "").strip()
    return bool(base and model)


async def _post_batch(
    url: str,
    headers: dict[str, str],
    model: str,
    batch: list[str],
    dim: int,
    timeout_seconds: float,
) -> list[list[float]] | None:
    client = _get_emb_client(timeout_seconds)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = await client.post(
                url,
                headers=headers,
                json={"model": model, "input": batch},
                timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            )
            if resp.status_code == 400 and len(batch) > 1 and "batch" in resp.text.lower():
                mid = len(batch) // 2
                left = await _post_batch(url, headers, model, batch[:mid], dim, timeout_seconds)
                right = await _post_batch(url, headers, model, batch[mid:], dim, timeout_seconds)
                if left is None or right is None:
                    return None
                return left + right
            if resp.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("transient", request=resp.request, response=resp)
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data") or []
            ordered = sorted(data, key=lambda row: int(row.get("index", 0)))
            if len(ordered) != len(batch):
                return None
            return [fit_embedding(row["embedding"], dim=dim) for row in ordered]
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(0.4 * (2**attempt))
    logger.warning("Embedding batch request failed after retries (%s); storing without vector", last_exc)
    return None


async def embed_texts(texts: Sequence[str]) -> list[list[float]] | None:
    """Return L2-normalized embeddings using micro-batching, retry, and Redis caching."""
    items = [str(t or "").strip() for t in texts]
    if not items or not is_embedding_configured():
        return None
    s = get_settings()
    base = (s.embedding_base_url or "").strip()
    api_key = (s.embedding_api_key or "").strip()
    model = (s.embedding_model or "").strip()
    dim = max(1, int(s.embedding_dimensions or 1536))
    batch_size = max(1, min(int(s.embedding_batch_size or 10), 64))
    cache_ttl = max(60, int(s.embedding_cache_ttl_seconds or 86400))

    results: list[list[float] | None] = [None] * len(items)
    cache_keys = [_cache_key(model, dim, t) for t in items]
    missing_indices: list[int] = []

    redis = None
    try:
        redis = get_redis()
    except Exception:
        redis = None

    if redis is not None:
        try:
            if hasattr(redis, "mget"):
                cached = await redis.mget(cache_keys)
            else:
                cached = [await redis.get(k) for k in cache_keys]
            for idx, raw in enumerate(cached or []):
                if raw:
                    vec = json.loads(raw)
                    if isinstance(vec, list) and len(vec) == dim:
                        results[idx] = vec
                        continue
                missing_indices.append(idx)
        except Exception:
            missing_indices = list(range(len(items)))
    else:
        missing_indices = list(range(len(items)))

    if missing_indices:
        url = _embeddings_url(base)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for start in range(0, len(missing_indices), batch_size):
            sub_idxs = missing_indices[start : start + batch_size]
            sub_texts = [items[i] or " " for i in sub_idxs]
            vecs = await _post_batch(url, headers, model, sub_texts, dim, s.embedding_timeout_seconds)
            if vecs is None:
                return None
            for i, vec in zip(sub_idxs, vecs):
                results[i] = vec
                if redis is not None:
                    try:
                        await redis.set(cache_keys[i], json.dumps(vec, separators=(",", ":")), ex=cache_ttl)
                    except Exception:
                        pass

    if any(v is None for v in results):
        return None
    return [v for v in results if v is not None]

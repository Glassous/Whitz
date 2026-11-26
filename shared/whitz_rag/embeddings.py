from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from typing import Any, Sequence

import httpx

logger = logging.getLogger("whitz.rag.embeddings")

_TRGM_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")
_SHARED_RAG_CLIENT: httpx.AsyncClient | None = None
# Cache endpoints that reject the OpenAI `dimensions` parameter so we never waste retries.
_UNSUPPORTED_DIMENSIONS_ENDPOINTS: set[tuple[str, str]] = set()


def _get_shared_client(timeout_seconds: float = 30.0) -> httpx.AsyncClient:
    global _SHARED_RAG_CLIENT
    if _SHARED_RAG_CLIENT is None or _SHARED_RAG_CLIENT.is_closed:
        _SHARED_RAG_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=20, keepalive_expiry=30.0),
            trust_env=False,
        )
    return _SHARED_RAG_CLIENT


async def aclose_shared_rag_clients() -> None:
    global _SHARED_RAG_CLIENT
    if _SHARED_RAG_CLIENT is not None and not _SHARED_RAG_CLIENT.is_closed:
        try:
            await _SHARED_RAG_CLIENT.aclose()
        except Exception:
            pass
    _SHARED_RAG_CLIENT = None


def fit_embedding(vec: Sequence[float], dim: int = 1536) -> list[float]:
    """Pad or truncate an embedding vector to ``dim`` and L2-normalize it."""
    if dim <= 0:
        raise ValueError("embedding dimension must be positive")
    values = [float(x) for x in vec[:dim]]
    if len(values) < dim:
        values.extend([0.0] * (dim - len(values)))
    norm = math.sqrt(sum(v * v for v in values))
    if norm > 0.0:
        return [v / norm for v in values]
    return values


def vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def char_trigrams(text: str) -> set[str]:
    compact = " ".join(_TRGM_TOKEN_RE.findall((text or "").lower()))
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[i : i + 3] for i in range(len(compact) - 2)}


def jaccard_sim(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / float(len(a) + len(b) - inter)


def _normalize_embeddings_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if cleaned.endswith("/embeddings"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/embeddings"
    return f"{cleaned}/v1/embeddings"


def _embedding_cache_key(model: str, dim: int, text: str) -> str:
    digest = hashlib.sha256(f"{model}|{dim}|{text}".encode("utf-8")).hexdigest()[:32]
    return f"emb:cache:{digest}"


def _is_dimensions_unsupported_error(status_code: int, body_text: str) -> bool:
    if status_code not in (400, 422):
        return False
    low = (body_text or "").lower()
    return "dimension" in low and any(
        k in low for k in ("unsupported", "invalid", "unknown", "not allowed", "not support", "extra", "unexpected", "must be")
    )


class EmbeddingClient:
    """Unified OpenAI-compatible /v1/embeddings client shared by Server & Agent.

    Features:
    - Automatic `dimensions` negotiation with endpoint-level fallback cache
    - Micro-batching with automatic 400 batch-size halving & exponential backoff retry
    - Redis batch `mget` + pipeline cache
    - Strict single-space policy: returns ``None`` when unconfigured or on failure
    """

    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        dimensions: int = 1536,
        batch_size: int = 10,
        cache_ttl_seconds: int = 86400,
        timeout_seconds: float = 30.0,
        redis_client: Any = None,
    ) -> None:
        self._base_url = (base_url or "").strip()
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._dimensions = max(1, int(dimensions or 1536))
        self._batch_size = max(1, min(int(batch_size or 10), 64))
        self._cache_ttl = max(60, int(cache_ttl_seconds or 86400))
        self._timeout = max(3.0, float(timeout_seconds or 30.0))
        self.redis = redis_client

    @classmethod
    def from_settings(cls, settings: Any, *, redis_client: Any = None) -> "EmbeddingClient":
        return cls(
            base_url=str(getattr(settings, "embedding_base_url", "") or ""),
            api_key=str(getattr(settings, "embedding_api_key", "") or ""),
            model=str(getattr(settings, "embedding_model", "") or ""),
            dimensions=int(getattr(settings, "embedding_dimensions", 1536) or 1536),
            batch_size=int(getattr(settings, "embedding_batch_size", 10) or 10),
            cache_ttl_seconds=int(getattr(settings, "embedding_cache_ttl_seconds", 86400) or 86400),
            timeout_seconds=float(getattr(settings, "embedding_timeout_seconds", 30.0) or 30.0),
            redis_client=redis_client,
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def model_tag(self) -> str:
        return f"{self._model}@{self._dimensions}" if self._model else ""

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._model)

    def _get_http_client(self) -> httpx.AsyncClient:
        return _get_shared_client(self._timeout)

    async def _post_batch(
        self,
        url: str,
        headers: dict[str, str],
        batch: list[str],
        dim: int,
    ) -> list[list[float]] | None:
        client = self._get_http_client()
        ep_key = (url, self._model)
        send_dimensions = ep_key not in _UNSUPPORTED_DIMENSIONS_ENDPOINTS
        last_exc: Exception | None = None

        for attempt in range(3):
            try:
                body: dict[str, Any] = {"model": self._model, "input": batch}
                if send_dimensions:
                    body["dimensions"] = dim
                resp = await client.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=httpx.Timeout(self._timeout, connect=10.0),
                )
                if send_dimensions and _is_dimensions_unsupported_error(resp.status_code, resp.text):
                    _UNSUPPORTED_DIMENSIONS_ENDPOINTS.add(ep_key)
                    send_dimensions = False
                    resp = await client.post(
                        url,
                        headers=headers,
                        json={"model": self._model, "input": batch},
                        timeout=httpx.Timeout(self._timeout, connect=10.0),
                    )
                if resp.status_code == 400 and len(batch) > 1 and "batch" in resp.text.lower():
                    mid = len(batch) // 2
                    left = await self._post_batch(url, headers, batch[:mid], dim)
                    right = await self._post_batch(url, headers, batch[mid:], dim)
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
                    raise ValueError(f"unexpected embedding count {len(ordered)} != {len(batch)}")
                return [fit_embedding(row["embedding"], dim=dim) for row in ordered]
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(0.4 * (2**attempt))
        logger.warning("Remote embedding batch failed after retries (%s)", last_exc)
        return None

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]] | None:
        items = [str(t or "").strip() for t in texts]
        if not items:
            return []
        if not self.is_configured:
            return None

        dim = self._dimensions
        results: list[list[float] | None] = [None] * len(items)
        missing_indices: list[int] = []
        cache_keys = [_embedding_cache_key(self._model, dim, t) for t in items]

        if self.redis is not None:
            try:
                if hasattr(self.redis, "mget"):
                    cached_vals = await self.redis.mget(cache_keys)
                else:
                    cached_vals = [await self.redis.get(k) for k in cache_keys]
                for idx, raw in enumerate(cached_vals or []):
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
            url = _normalize_embeddings_url(self._base_url)
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            bs = self._batch_size
            ttl = self._cache_ttl
            batches = [
                missing_indices[start : start + bs]
                for start in range(0, len(missing_indices), bs)
            ]
            sem = asyncio.Semaphore(4)

            async def _fetch_batch(sub_idxs: list[int]) -> tuple[list[int], list[list[float]] | None]:
                sub_texts = [items[i] or " " for i in sub_idxs]
                async with sem:
                    vecs = await self._post_batch(url, headers, sub_texts, dim)
                return sub_idxs, vecs

            if len(batches) == 1:
                batch_results = [await _fetch_batch(batches[0])]
            else:
                batch_results = list(await asyncio.gather(*(_fetch_batch(b) for b in batches)))

            pipe = (
                self.redis.pipeline(transaction=False)
                if (self.redis is not None and hasattr(self.redis, "pipeline"))
                else None
            )
            for sub_idxs, vecs in batch_results:
                if vecs is None:
                    return None
                for i, vec in zip(sub_idxs, vecs):
                    results[i] = vec
                    if pipe is not None:
                        pipe.set(cache_keys[i], json.dumps(vec, separators=(",", ":")), ex=ttl)
                    elif self.redis is not None:
                        try:
                            await self.redis.set(cache_keys[i], json.dumps(vec, separators=(",", ":")), ex=ttl)
                        except Exception:
                            pass
            if pipe is not None:
                try:
                    await pipe.execute()
                except Exception:
                    pass

        if any(v is None for v in results):
            return None
        return [v for v in results if v is not None]

    async def embed_query(self, text: str) -> list[float] | None:
        vectors = await self.embed_texts([text])
        if not vectors:
            return None
        return vectors[0]


class RerankClient:
    """Dual-protocol Stage-2 Reranker client supporting DashScope native & OpenAI/Jina/SiliconFlow APIs."""

    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        top_n: int = 8,
        timeout_seconds: float = 15.0,
        redis_client: Any = None,
    ) -> None:
        self._base_url = (base_url or "").strip()
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._top_n = max(1, int(top_n or 8))
        self._timeout = max(3.0, float(timeout_seconds or 15.0))
        self.redis = redis_client

    @classmethod
    def from_settings(cls, settings: Any, *, redis_client: Any = None) -> "RerankClient":
        return cls(
            base_url=str(getattr(settings, "rerank_base_url", "") or ""),
            api_key=str(getattr(settings, "rerank_api_key", "") or ""),
            model=str(getattr(settings, "rerank_model", "") or ""),
            top_n=int(getattr(settings, "rerank_top_n", 8) or 8),
            timeout_seconds=float(getattr(settings, "rerank_timeout_seconds", 15.0) or 15.0),
            redis_client=redis_client,
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._model)

    @staticmethod
    def _is_dashscope_native(url: str) -> bool:
        low = url.lower()
        return "/services/rerank/" in low or ("aliyuncs.com" in low and "/compatible-mode/" not in low)

    @staticmethod
    def _normalize_url(base_url: str) -> str:
        cleaned = base_url.strip().rstrip("/")
        if "/rerank" in cleaned.lower():
            return cleaned
        if cleaned.endswith("/v1"):
            return f"{cleaned}/rerank"
        return f"{cleaned}/v1/rerank"

    def _get_http_client(self) -> httpx.AsyncClient:
        return _get_shared_client(self._timeout)

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int | None = None,
    ) -> list[tuple[int, float]] | None:
        docs = [str(d or "")[:2000] for d in documents]
        if not self.is_configured or not (query or "").strip() or not docs:
            return None

        limit = max(1, min(int(top_n or self._top_n or 8), len(docs)))
        url = self._normalize_url(self._base_url)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        is_ds = self._is_dashscope_native(url)
        if is_ds:
            body: dict[str, Any] = {
                "model": self._model,
                "input": {"query": query.strip()[:1000], "documents": docs},
                "parameters": {"top_n": limit, "return_documents": False},
            }
        else:
            body = {
                "model": self._model,
                "query": query.strip()[:1000],
                "documents": docs,
                "top_n": limit,
                "return_documents": False,
            }

        client = self._get_http_client()
        try:
            resp = await client.post(
                url,
                headers=headers,
                json=body,
                timeout=httpx.Timeout(self._timeout, connect=8.0),
            )
            resp.raise_for_status()
            payload = resp.json()
            raw_results = (
                (payload.get("output") or {}).get("results")
                if is_ds and isinstance(payload.get("output"), dict)
                else payload.get("results")
            ) or []
            scored: list[tuple[int, float]] = []
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                idx = int(item.get("index", -1))
                score = float(item.get("relevance_score", item.get("score", 0.0)))
                if 0 <= idx < len(docs):
                    scored.append((idx, score))
            scored.sort(key=lambda pair: pair[1], reverse=True)
            return scored[:limit] if scored else None
        except Exception as exc:
            logger.warning("Rerank API call failed (%s); falling back to RRF+MMR ordering", exc)
            return None

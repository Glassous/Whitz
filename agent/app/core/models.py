from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import AgentSettings, get_settings

logger = logging.getLogger("whitz.agent.models")


class WhitzChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass preserving vendor reasoning_content / reasoning deltas."""

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ):
        gen_chunk = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if gen_chunk is not None:
            choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
            if choices and isinstance(choices[0], dict):
                delta = choices[0].get("delta") or {}
                if isinstance(delta, dict):
                    rc = delta.get("reasoning_content") or delta.get("reasoning")
                    if isinstance(rc, str) and rc:
                        gen_chunk.message.additional_kwargs["reasoning_content"] = rc
        return gen_chunk


VALID_ROUTES = ("auto", "default", "fast", "reasoning", "vision")
_TRIVIAL_GREETINGS = frozenset({"hi", "hello", "hey", "你好", "您好", "在吗", "谢谢", "感谢", "ok", "好的", "嗯"})
_UNSUPPORTED_THINKING_MODELS: set[tuple[str, str]] = set()
_COMPLEX_REASONING_RE = re.compile(
    r"(架构|设计方案|深入分析|对比分析|源码|排障|调试|为什么.*失败|推导|证明|算法|复杂度|"
    r"重构|性能优化|数据库设计|sql|系统设计|权衡|trade[- ]?off|benchmark|debug|refactor|"
    r"architecture|step[- ]by[- ]step|数学|方程|微积分|概率)",
    re.IGNORECASE,
)

# Shared process-level async HTTP clients (reused across LLM / Embedding / Rerank calls)
_SHARED_API_CLIENT: httpx.AsyncClient | None = None
_SHARED_LLM_CLIENT: httpx.AsyncClient | None = None


def _get_shared_api_client() -> httpx.AsyncClient:
    global _SHARED_API_CLIENT
    if _SHARED_API_CLIENT is None or _SHARED_API_CLIENT.is_closed:
        _SHARED_API_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=20, keepalive_expiry=30.0),
            trust_env=False,
        )
    return _SHARED_API_CLIENT


def _get_shared_llm_client(timeout_seconds: float = 120.0) -> httpx.AsyncClient:
    global _SHARED_LLM_CLIENT
    if _SHARED_LLM_CLIENT is None or _SHARED_LLM_CLIENT.is_closed:
        _SHARED_LLM_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=15.0),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=24, keepalive_expiry=45.0),
            trust_env=False,
        )
    return _SHARED_LLM_CLIENT


async def aclose_shared_http_clients() -> None:
    global _SHARED_API_CLIENT, _SHARED_LLM_CLIENT
    for client in (_SHARED_API_CLIENT, _SHARED_LLM_CLIENT):
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception:
                pass
    _SHARED_API_CLIENT = None
    _SHARED_LLM_CLIENT = None


@dataclass(frozen=True)
class ModelEndpoint:
    route: str
    base_url: str
    api_key: str
    model: str
    supports_vision: bool = False


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


def deterministic_embedding(text: str, dim: int = 1536) -> list[float]:
    """Produce a deterministic L2-normalized embedding when no remote embedding API is configured."""
    vec = [0.0] * dim
    cleaned = (text or "").strip().lower()
    if not cleaned:
        vec[0] = 1.0
        return vec
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", cleaned)
    features: list[str] = list(tokens)
    for tok in tokens:
        if len(tok) >= 3:
            for i in range(len(tok) - 2):
                features.append(tok[i : i + 3])
    if not features:
        features = [cleaned]
    for feat in features:
        digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=16).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0) * 0.5
        vec[idx] += sign * weight
    return fit_embedding(vec, dim=dim)


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


class EmbeddingClient:
    """OpenAI-compatible /v1/embeddings client with micro-batching, retry, Redis cache, and lossless L2 zero-padding.

    Never fabricates hash vectors when unconfigured or on failure — returns ``None`` so pgvector
    stays strictly single-space and retrievers degrade cleanly to ``pg_trgm`` + FTS.
    """

    def __init__(self, settings: AgentSettings | None = None, redis_client: Any = None) -> None:
        self.settings = settings or get_settings()
        self.redis = redis_client

    @property
    def base_url(self) -> str:
        return (self.settings.embedding_base_url or "").strip()

    @property
    def api_key(self) -> str:
        return (self.settings.embedding_api_key or "").strip()

    @property
    def model(self) -> str:
        return (self.settings.embedding_model or "").strip()

    @property
    def dimensions(self) -> int:
        return max(1, int(self.settings.embedding_dimensions or 1536))

    @property
    def batch_size(self) -> int:
        return max(1, min(int(self.settings.embedding_batch_size or 10), 64))

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.model)

    async def _post_batch(
        self,
        url: str,
        headers: dict[str, str],
        batch: list[str],
        dim: int,
    ) -> list[list[float]] | None:
        """Send a single batch with exponential backoff retry and automatic batch-size halving on 400."""
        client = _get_shared_api_client()
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await client.post(
                    url,
                    headers=headers,
                    json={"model": self.model, "input": batch},
                    timeout=httpx.Timeout(self.settings.embedding_timeout_seconds, connect=10.0),
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

        dim = self.dimensions
        results: list[list[float] | None] = [None] * len(items)
        missing_indices: list[int] = []
        cache_keys: list[str] = [_embedding_cache_key(self.model, dim, t) for t in items]

        # 1. Check Redis embedding cache
        if self.redis is not None:
            try:
                cached_vals = await self.redis.mget(cache_keys)
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

        # 2. Fetch uncached texts in micro-batches
        if missing_indices:
            url = _normalize_embeddings_url(self.base_url)
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            bs = self.batch_size
            ttl = max(60, int(self.settings.embedding_cache_ttl_seconds or 86400))
            for start in range(0, len(missing_indices), bs):
                sub_idxs = missing_indices[start : start + bs]
                sub_texts = [items[i] or " " for i in sub_idxs]
                vecs = await self._post_batch(url, headers, sub_texts, dim)
                if vecs is None:
                    return None
                pipe = self.redis.pipeline(transaction=False) if self.redis is not None else None
                for i, vec in zip(sub_idxs, vecs):
                    results[i] = vec
                    if pipe is not None:
                        pipe.set(cache_keys[i], json.dumps(vec, separators=(",", ":")), ex=ttl)
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
    """Dual-protocol Stage-2 Reranker client supporting DashScope/Maas native & OpenAI/Jina/SiliconFlow APIs."""

    def __init__(self, settings: AgentSettings | None = None, redis_client: Any = None) -> None:
        self.settings = settings or get_settings()
        self.redis = redis_client

    @property
    def base_url(self) -> str:
        return (self.settings.rerank_base_url or "").strip()

    @property
    def api_key(self) -> str:
        return (self.settings.rerank_api_key or "").strip()

    @property
    def model(self) -> str:
        return (self.settings.rerank_model or "").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.model)

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

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int | None = None,
    ) -> list[tuple[int, float]] | None:
        """Return ordered ``[(doc_index, relevance_score), ...]`` or ``None`` if disabled/failed."""
        docs = [str(d or "")[:2000] for d in documents]
        if not self.is_configured or not query.strip() or not docs:
            return None

        limit = max(1, min(int(top_n or self.settings.rerank_top_n or 8), len(docs)))
        url = self._normalize_url(self.base_url)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        is_ds = self._is_dashscope_native(url)
        if is_ds:
            body: dict[str, Any] = {
                "model": self.model,
                "input": {"query": query.strip()[:1000], "documents": docs},
                "parameters": {"top_n": limit, "return_documents": False},
            }
        else:
            body = {
                "model": self.model,
                "query": query.strip()[:1000],
                "documents": docs,
                "top_n": limit,
                "return_documents": False,
            }

        client = _get_shared_api_client()
        try:
            resp = await client.post(
                url,
                headers=headers,
                json=body,
                timeout=httpx.Timeout(self.settings.rerank_timeout_seconds, connect=8.0),
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


class ModelRouter:
    """Task-aware OpenAI-compatible model router with Redis circuit-breaker and fallback chain."""

    def __init__(self, settings: AgentSettings | None = None, redis_client: Any = None) -> None:
        self.settings = settings or get_settings()
        self.redis = redis_client

    def endpoint_for(self, route: str) -> ModelEndpoint:
        s = self.settings
        primary_base = (s.llm_base_url or "").strip()
        primary_key = (s.llm_api_key or "").strip()
        primary_model = (s.llm_model or "").strip()
        primary_vision = bool(s.llm_supports_vision)

        if route == "fast":
            return ModelEndpoint(
                route="fast",
                base_url=(s.llm_fast_base_url or primary_base).strip(),
                api_key=(s.llm_fast_api_key or primary_key).strip(),
                model=(s.llm_fast_model or primary_model).strip(),
                supports_vision=False,
            )
        if route == "reasoning":
            return ModelEndpoint(
                route="reasoning",
                base_url=(s.llm_reasoning_base_url or primary_base).strip(),
                api_key=(s.llm_reasoning_api_key or primary_key).strip(),
                model=(s.llm_reasoning_model or primary_model).strip(),
                supports_vision=False,
            )
        if route == "vision":
            return ModelEndpoint(
                route="vision",
                base_url=(s.llm_vision_base_url or primary_base).strip(),
                api_key=(s.llm_vision_api_key or primary_key).strip(),
                model=(s.llm_vision_model or primary_model).strip(),
                supports_vision=True if s.llm_vision_model.strip() else primary_vision,
            )
        return ModelEndpoint(
            route="default",
            base_url=primary_base,
            api_key=primary_key,
            model=primary_model,
            supports_vision=primary_vision,
        )

    @staticmethod
    def _has_image_content(messages: Sequence[BaseMessage | dict[str, Any]]) -> bool:
        for msg in messages:
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") in ("image", "image_url"):
                        return True
        return False

    def infer_route(
        self,
        requested_route: str | None = "auto",
        messages: Sequence[BaseMessage | dict[str, Any]] | None = None,
        *,
        has_images: bool = False,
        task_hint: str | None = None,
    ) -> str:
        req = (requested_route or "auto").strip().lower()
        if req in ("default", "fast", "reasoning", "vision"):
            return req

        msgs = messages or []
        if has_images or self._has_image_content(msgs):
            ep = self.endpoint_for("vision")
            if ep.model and ep.supports_vision:
                return "vision"
            return "default"

        hint = (task_hint or "").strip().lower()
        if hint in ("fast", "memory_extract", "summarize", "title", "classify"):
            return "fast"
        if hint in ("reasoning", "plan", "research", "code", "subagent_research", "subagent_code"):
            return "reasoning"

        last_text = ""
        for msg in reversed(msgs):
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                last_text = content.strip()
                break

        low = last_text.lower().strip("!！。.~～ ")
        if low and self.settings.llm_fast_model.strip() and (low in _TRIVIAL_GREETINGS or (len(low) <= 6 and "?" not in low and "？" not in low)):
            return "fast"
        return "default"

    @staticmethod
    def _resolve_thinking_style(model_name: str, style: str) -> str:
        s = (style or "auto").strip().lower()
        if s in ("deepseek", "qwen", "openai", "none"):
            return s
        low = (model_name or "").strip().lower()
        if not low:
            return "none"
        if any(k in low for k in ("o1", "o3", "o4", "gpt-5")):
            return "openai"
        if "qwen" in low or "qwq" in low:
            return "qwen"
        if "deepseek" in low or "glm" in low:
            # Always-on reasoners like deepseek-r1 / deepseek-reasoner don't take toggle flags
            if "reasoner" in low or "-r1" in low or low.endswith("r1"):
                return "none"
            return "deepseek"
        return "none"

    @staticmethod
    def is_thinking_param_unsupported(ep: ModelEndpoint) -> bool:
        return (ep.base_url, ep.model) in _UNSUPPORTED_THINKING_MODELS

    @staticmethod
    def mark_thinking_param_unsupported(ep: ModelEndpoint) -> None:
        if ep.base_url or ep.model:
            _UNSUPPORTED_THINKING_MODELS.add((ep.base_url, ep.model))

    @staticmethod
    def is_unsupported_thinking_param_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        param_hit = any(k in msg for k in ("thinking", "enable_thinking", "reasoning_effort", "extra_body"))
        reject_hit = any(k in msg for k in ("unknown", "unsupported", "invalid", "unrecognized", "extra_forbidden", "400", "422"))
        return param_hit and reject_hit

    @staticmethod
    def _last_user_text(messages: Sequence[BaseMessage | dict[str, Any]] | None) -> str:
        for msg in reversed(messages or ()):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", "")
            if role in ("user", "human"):
                content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
                if isinstance(content, str):
                    return content.strip()
        return ""

    async def resolve_thinking_decision(
        self,
        requested_route: str | None = "auto",
        messages: Sequence[BaseMessage | dict[str, Any]] | None = None,
        *,
        has_images: bool = False,
    ) -> tuple[bool, str, str]:
        """Autonomously decide whether to enable thinking mode and which route to use.

        Returns ``(thinking_enabled, route, reason)``.
        """
        req = (requested_route or "auto").strip().lower()
        mode_cfg = (self.settings.llm_thinking_mode or "auto").strip().lower()

        if req == "reasoning":
            return True, "reasoning", "explicit_reasoning_route"
        if req == "fast":
            return False, "fast", "explicit_fast_route"
        if req == "vision":
            return False, "vision", "explicit_vision_route"
        if req == "default":
            return False, "default", "explicit_default_route"
        if mode_cfg == "enabled":
            return True, ("reasoning" if self.settings.llm_reasoning_model.strip() else "default"), "global_enabled"
        if mode_cfg == "disabled":
            return False, ("fast" if self.settings.llm_fast_model.strip() else "default"), "global_disabled"

        msgs = messages or []
        if has_images or self._has_image_content(msgs):
            ep = self.endpoint_for("vision")
            return False, ("vision" if (ep.model and ep.supports_vision) else "default"), "multimodal_image"

        user_text = self._last_user_text(msgs)
        if not user_text:
            return False, "default", "empty_input"

        low = user_text.lower().strip("!！。.~～ ")
        if low in _TRIVIAL_GREETINGS or (len(low) <= 8 and "?" not in low and "？" not in low):
            return False, ("fast" if self.settings.llm_fast_model.strip() else "default"), "trivial_query"

        # Zero-latency deterministic complexity heuristic (eliminates 6s TTFT probe overhead;
        # the agent can still escalate mid-turn via `request_deep_thinking`).
        if len(user_text) >= 180 or "```" in user_text or _COMPLEX_REASONING_RE.search(user_text):
            route = "reasoning" if self.settings.llm_reasoning_model.strip() else "default"
            return True, route, "heuristic_complex_thinking"

        return False, "default", "heuristic_direct"

    def fallback_chain(self, route: str) -> list[ModelEndpoint]:
        order_map = {
            "vision": ["vision", "default"],
            "reasoning": ["reasoning", "default", "fast"],
            "fast": ["fast", "default"],
            "default": ["default", "fast", "reasoning"],
        }
        order = order_map.get(route, ["default", "fast", "reasoning"])
        seen: set[tuple[str, str]] = set()
        chain: list[ModelEndpoint] = []
        for candidate_route in order:
            ep = self.endpoint_for(candidate_route)
            if not ep.model or not ep.base_url:
                continue
            dedup_key = (ep.base_url, ep.model)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            chain.append(ep)
        if not chain:
            # Always include primary endpoint even if unconfigured so callers see clear validation/runtime errors.
            chain.append(self.endpoint_for("default"))
        return chain

    @staticmethod
    def _cb_open_key(ep: ModelEndpoint) -> str:
        return f"agent:cb:open:{ep.route}:{ep.model or 'unset'}"

    @staticmethod
    def _cb_fail_key(ep: ModelEndpoint) -> str:
        return f"agent:cb:fails:{ep.route}:{ep.model or 'unset'}"

    async def is_circuit_open(self, ep: ModelEndpoint) -> bool:
        if self.redis is None:
            return False
        try:
            return bool(await self.redis.exists(self._cb_open_key(ep)))
        except Exception:
            return False

    async def record_success(self, ep: ModelEndpoint) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.delete(self._cb_fail_key(ep), self._cb_open_key(ep))
        except Exception:
            pass

    async def record_failure(self, ep: ModelEndpoint) -> None:
        if self.redis is None:
            return
        threshold = max(1, int(self.settings.model_cb_failure_threshold))
        cooldown = max(5, int(self.settings.model_cb_cooldown_seconds))
        fail_key = self._cb_fail_key(ep)
        try:
            fails = await self.redis.incr(fail_key)
            await self.redis.expire(fail_key, cooldown * 2)
            if int(fails) >= threshold:
                await self.redis.set(self._cb_open_key(ep), "1", ex=cooldown)
                logger.warning("Model circuit breaker opened route=%s model=%s", ep.route, ep.model)
        except Exception:
            pass

    def build_chat_model(
        self,
        ep: ModelEndpoint,
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        streaming: bool = True,
        thinking_enabled: bool | None = None,
        include_thinking_params: bool = True,
    ) -> ChatOpenAI:
        kwargs: dict[str, Any] = {
            "model": ep.model or "gpt-4o-mini",
            "api_key": ep.api_key or "sk-placeholder",
            "base_url": ep.base_url or "https://api.openai.com/v1",
            "temperature": temperature,
            "streaming": streaming,
            "timeout": self.settings.llm_timeout_seconds,
            "max_retries": 1,
            "stream_usage": True,
            "http_async_client": _get_shared_llm_client(self.settings.llm_timeout_seconds),
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if (
            include_thinking_params
            and thinking_enabled is not None
            and not self.is_thinking_param_unsupported(ep)
        ):
            style = self._resolve_thinking_style(ep.model, self.settings.llm_thinking_param_style)
            if style == "deepseek":
                kwargs["extra_body"] = {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
            elif style == "qwen":
                kwargs["extra_body"] = {"enable_thinking": bool(thinking_enabled)}
            elif style == "openai":
                kwargs["reasoning_effort"] = "medium" if thinking_enabled else "low"
        return WhitzChatOpenAI(**kwargs)

    async def select_candidates(
        self,
        requested_route: str | None = "auto",
        messages: Sequence[BaseMessage | dict[str, Any]] | None = None,
        *,
        has_images: bool = False,
        task_hint: str | None = None,
    ) -> list[ModelEndpoint]:
        route = self.infer_route(
            requested_route,
            messages,
            has_images=has_images,
            task_hint=task_hint,
        )
        chain = self.fallback_chain(route)
        healthy: list[ModelEndpoint] = []
        tripped: list[ModelEndpoint] = []
        for ep in chain:
            if await self.is_circuit_open(ep):
                tripped.append(ep)
            else:
                healthy.append(ep)
        # Keep tripped endpoints at the very end as last-resort if all circuits are open.
        return healthy if healthy else tripped

    async def get_chat_model(
        self,
        requested_route: str | None = "auto",
        messages: Sequence[BaseMessage | dict[str, Any]] | None = None,
        *,
        has_images: bool = False,
        task_hint: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        streaming: bool = True,
    ) -> tuple[ChatOpenAI, ModelEndpoint]:
        candidates = await self.select_candidates(
            requested_route,
            messages,
            has_images=has_images,
            task_hint=task_hint,
        )
        ep = candidates[0]
        return self.build_chat_model(
            ep,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        ), ep

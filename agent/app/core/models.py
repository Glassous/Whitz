from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

import httpx
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import AgentSettings, get_settings

logger = logging.getLogger("whitz.agent.models")

VALID_ROUTES = ("auto", "default", "fast", "reasoning", "vision")
_REASONING_KEYWORDS = (
    "analyze",
    "analysis",
    "architect",
    "compare",
    "debug",
    "design",
    "derive",
    "explain why",
    "implement",
    "optimize",
    "plan",
    "proof",
    "python",
    "refactor",
    "research",
    "step by step",
    "verify",
    "分析",
    "架构",
    "推理",
    "设计",
    "优化",
    "重构",
    "排查",
    "研究",
    "调研",
    "对比",
    "计算",
    "验证",
    "代码",
    "步骤",
    "方案",
)


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


class EmbeddingClient:
    """OpenAI-compatible /v1/embeddings client returning 1536-dim L2 vectors with deterministic fallback."""

    def __init__(self, settings: AgentSettings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def base_url(self) -> str:
        return (self.settings.embedding_base_url or self.settings.llm_base_url or "").strip()

    @property
    def api_key(self) -> str:
        return (self.settings.embedding_api_key or self.settings.llm_api_key or "").strip()

    @property
    def model(self) -> str:
        return (self.settings.embedding_model or "").strip()

    @property
    def dimensions(self) -> int:
        return max(1, int(self.settings.embedding_dimensions or 1536))

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.model)

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        items = [str(t or "") for t in texts]
        if not items:
            return []
        dim = self.dimensions
        if not self.is_configured:
            return [deterministic_embedding(t, dim=dim) for t in items]

        url = _normalize_embeddings_url(self.base_url)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.embedding_timeout_seconds),
                trust_env=False,
            ) as client:
                resp = await client.post(
                    url,
                    headers=headers,
                    json={"model": self.model, "input": items},
                )
                resp.raise_for_status()
                payload = resp.json()
            data = payload.get("data") or []
            ordered = sorted(data, key=lambda row: int(row.get("index", 0)))
            if len(ordered) != len(items):
                raise ValueError(f"unexpected embedding count {len(ordered)} != {len(items)}")
            return [fit_embedding(row["embedding"], dim=dim) for row in ordered]
        except Exception as exc:
            logger.warning("Remote embedding call failed (%s); falling back to deterministic embedding", exc)
            return [deterministic_embedding(t, dim=dim) for t in items]

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_texts([text])
        return vectors[0] if vectors else deterministic_embedding(text, dim=self.dimensions)


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
                last_text = content.strip().lower()
                break

        if last_text:
            if any(kw in last_text for kw in _REASONING_KEYWORDS) or len(last_text) > 500:
                return "reasoning"
            if len(last_text) < 25 and self.settings.llm_fast_model.strip():
                return "fast"
        return "default"

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
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(**kwargs)

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

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
from whitz_rag.embeddings import (
    EmbeddingClient as _SharedEmbeddingClient,
    RerankClient as _SharedRerankClient,
    aclose_shared_rag_clients,
    fit_embedding,
)

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
_URL_UNSUPPORTED_VISION_MODELS: set[tuple[str, str]] = set()
_UNSUPPORTED_NATIVE_PDF_MODELS: set[tuple[str, str]] = set()
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
    await aclose_shared_rag_clients()


@dataclass(frozen=True)
class ModelEndpoint:
    route: str
    base_url: str
    api_key: str
    model: str
    supports_vision: bool = False


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


class EmbeddingClient(_SharedEmbeddingClient):
    """Agent settings adapter around the shared ``whitz_rag.EmbeddingClient``."""

    def __init__(self, settings: AgentSettings | None = None, redis_client: Any = None) -> None:
        self.settings = settings or get_settings()
        super().__init__(
            base_url=self.settings.embedding_base_url,
            api_key=self.settings.embedding_api_key,
            model=self.settings.embedding_model,
            dimensions=self.settings.embedding_dimensions,
            batch_size=self.settings.embedding_batch_size,
            cache_ttl_seconds=self.settings.embedding_cache_ttl_seconds,
            timeout_seconds=self.settings.embedding_timeout_seconds,
            redis_client=redis_client,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        return _get_shared_api_client()


class RerankClient(_SharedRerankClient):
    """Agent settings adapter around the shared ``whitz_rag.RerankClient``."""

    def __init__(self, settings: AgentSettings | None = None, redis_client: Any = None) -> None:
        self.settings = settings or get_settings()
        super().__init__(
            base_url=self.settings.rerank_base_url,
            api_key=self.settings.rerank_api_key,
            model=self.settings.rerank_model,
            top_n=self.settings.rerank_top_n,
            timeout_seconds=self.settings.rerank_timeout_seconds,
            redis_client=redis_client,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        return _get_shared_api_client()


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

    @staticmethod
    def _has_native_file_content(messages: Sequence[BaseMessage | dict[str, Any]]) -> bool:
        for msg in messages:
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "file":
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
        msgs = messages or []
        needs_vision = bool(has_images or self._has_image_content(msgs))

        if req in ("default", "fast", "reasoning", "vision"):
            if needs_vision:
                ep_req = self.endpoint_for(req)
                if not ep_req.supports_vision:
                    ep_vis = self.endpoint_for("vision")
                    if ep_vis.model and ep_vis.supports_vision:
                        return "vision"
                    if self.endpoint_for("default").supports_vision:
                        return "default"
            return req

        if needs_vision:
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
    def is_image_url_unsupported(ep: ModelEndpoint) -> bool:
        return (ep.base_url, ep.model) in _URL_UNSUPPORTED_VISION_MODELS

    @staticmethod
    def mark_image_url_unsupported(ep: ModelEndpoint) -> None:
        if ep.base_url or ep.model:
            _URL_UNSUPPORTED_VISION_MODELS.add((ep.base_url, ep.model))

    @staticmethod
    def is_image_url_fetch_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        url_hit = any(
            k in msg
            for k in (
                "invalid_image_url",
                "downloading",
                "failed to download",
                "could not fetch",
                "image_url",
                "fetch image",
                "unable to access",
                "timeout while downloading",
                "error while downloading",
            )
        )
        status_hit = any(k in msg for k in ("400", "422", "timeout", "download", "fetch", "invalid", "failed"))
        return url_hit and status_hit

    @staticmethod
    def is_native_pdf_unsupported(ep: ModelEndpoint) -> bool:
        return (ep.base_url, ep.model) in _UNSUPPORTED_NATIVE_PDF_MODELS

    @staticmethod
    def mark_native_pdf_unsupported(ep: ModelEndpoint) -> None:
        if ep.base_url or ep.model:
            _UNSUPPORTED_NATIVE_PDF_MODELS.add((ep.base_url, ep.model))

    @staticmethod
    def is_unsupported_native_pdf_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        file_hit = any(
            k in msg
            for k in (
                "file_data",
                "'file'",
                '"file"',
                "type: file",
                "content type",
                "unknown variant",
                "application/pdf",
                "input_file",
            )
        )
        reject_hit = any(k in msg for k in ("400", "422", "unsupported", "invalid", "unknown", "unrecognized", "not supported"))
        return file_hit and reject_hit

    @staticmethod
    def _last_user_text(messages: Sequence[BaseMessage | dict[str, Any]] | None) -> str:
        for msg in reversed(messages or ()):
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", "")
            if role in ("user", "human"):
                content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
                if isinstance(content, str):
                    return content.strip()
                if isinstance(content, list):
                    parts = [
                        str(b.get("text") or "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") in ("text", None) and not str(b.get("text") or "").startswith("<attached_file ")
                    ]
                    joined = " ".join(p.strip() for p in parts if p.strip()).strip()
                    if joined:
                        return joined
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

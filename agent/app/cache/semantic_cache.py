from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.models import EmbeddingClient, deterministic_embedding

logger = logging.getLogger("whitz.agent.semantic_cache")

_REALTIME_KEYWORDS_RE = re.compile(
    r"(今天|今日|此刻|现在几点|实时|最新|刚刚|昨天|明天|本周|今年|股价|汇率|天气|新闻|热搜|"
    r"\b(?:today|now|latest|current|realtime|real-time|weather|stock price|news|breaking)\b)",
    re.IGNORECASE,
)

_DEICTIC_FOLLOWUP_RE = re.compile(
    r"(上面那个|上面|刚才|这个|那个|继续|再详细|展开说说|换成|改为|"
    r"\b(?:it|that|those|above|previous|continue|elaborate|expand on)\b)",
    re.IGNORECASE,
)

_WRITE_SIDE_EFFECT_TOOLS = frozenset(
    {
        "write_workspace_file",
        "edit_workspace_file",
        "memory_propose",
        "memory_manage_collection",
        "create_scheduled_task",
        "update_scheduled_task",
        "delete_scheduled_task",
        "execute_code",
        "react_to_user_message",
    }
)


def normalize_query(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def query_hash(text: str) -> str:
    return hashlib.sha256(normalize_query(text).encode("utf-8")).hexdigest()[:32]


def scope_hash(rag_scope: dict[str, Any] | None) -> str:
    if not rag_scope:
        return "default"
    canonical = json.dumps(rag_scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        na += a * a
        nb += b * b
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


@dataclass
class SemanticCacheEntry:
    entry_id: str
    scope_key: str
    query_norm: str
    query_sha: str
    embedding: list[float]
    response_text: str
    route: str = "default"
    model: str = ""
    original_tokens: int = 0
    citations: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(
            {
                "entry_id": self.entry_id,
                "scope_key": self.scope_key,
                "query_norm": self.query_norm,
                "query_sha": self.query_sha,
                "embedding": self.embedding,
                "response_text": self.response_text,
                "route": self.route,
                "model": self.model,
                "original_tokens": self.original_tokens,
                "citations": self.citations,
                "created_at": self.created_at,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> SemanticCacheEntry | None:
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
            if not isinstance(data, dict):
                return None
            return cls(
                entry_id=str(data.get("entry_id") or ""),
                scope_key=str(data.get("scope_key") or ""),
                query_norm=str(data.get("query_norm") or ""),
                query_sha=str(data.get("query_sha") or ""),
                embedding=[float(x) for x in (data.get("embedding") or [])],
                response_text=str(data.get("response_text") or ""),
                route=str(data.get("route") or "default"),
                model=str(data.get("model") or ""),
                original_tokens=int(data.get("original_tokens") or 0),
                citations=list(data.get("citations") or []),
                created_at=float(data.get("created_at") or 0.0),
            )
        except Exception:
            return None


@dataclass
class CacheLookupResult:
    hit: bool
    hit_type: str  # "hit_exact" | "hit_semantic" | "miss" | "bypass"
    similarity: float = 0.0
    entry: SemanticCacheEntry | None = None
    bypass_reason: str = ""
    latency_ms: float = 0.0

    def to_meta(self) -> dict[str, Any]:
        return {
            "hit": self.hit,
            "hit_type": self.hit_type,
            "similarity": round(self.similarity, 4),
            "bypass_reason": self.bypass_reason or None,
            "tokens_saved": self.entry.original_tokens if (self.hit and self.entry) else 0,
            "latency_ms": round(self.latency_ms, 3),
        }


class SemanticCacheStore(Protocol):
    async def get_epoch(self, user_id: str) -> str: ...
    async def bump_epoch(self, user_id: str) -> str: ...
    async def get_exact(self, scope_key: str, q_sha: str) -> SemanticCacheEntry | None: ...
    async def list_entries(self, scope_key: str) -> list[SemanticCacheEntry]: ...
    async def put_entry(self, entry: SemanticCacheEntry, *, ttl_seconds: int, max_entries: int) -> None: ...


class InMemoryCacheStore:
    """In-memory multi-tenant store used by unit tests and offline eval harness."""

    def __init__(self) -> None:
        self._epochs: dict[str, int] = {}
        self._scopes: dict[str, list[tuple[float, SemanticCacheEntry]]] = {}

    async def get_epoch(self, user_id: str) -> str:
        return str(self._epochs.get(user_id, 0))

    async def bump_epoch(self, user_id: str) -> str:
        nxt = self._epochs.get(user_id, 0) + 1
        self._epochs[user_id] = nxt
        return str(nxt)

    def _prune(self, scope_key: str) -> list[tuple[float, SemanticCacheEntry]]:
        now = time.time()
        items = [(exp, ent) for exp, ent in self._scopes.get(scope_key, []) if exp > now]
        self._scopes[scope_key] = items
        return items

    async def get_exact(self, scope_key: str, q_sha: str) -> SemanticCacheEntry | None:
        for _, ent in self._prune(scope_key):
            if ent.query_sha == q_sha:
                return ent
        return None

    async def list_entries(self, scope_key: str) -> list[SemanticCacheEntry]:
        return [ent for _, ent in self._prune(scope_key)]

    async def put_entry(self, entry: SemanticCacheEntry, *, ttl_seconds: int, max_entries: int) -> None:
        items = self._prune(entry.scope_key)
        items = [(exp, ent) for exp, ent in items if ent.query_sha != entry.query_sha]
        items.append((time.time() + max(1, ttl_seconds), entry))
        if len(items) > max_entries:
            items = items[-max_entries:]
        self._scopes[entry.scope_key] = items


class RedisCacheStore:
    """Production Redis-backed store with per-user epoch invalidation and bounded LRU slots."""

    def __init__(self, redis: Any, *, key_prefix: str = "whitz:scache") -> None:
        self.redis = redis
        self.prefix = key_prefix

    def _epoch_key(self, user_id: str) -> str:
        return f"{self.prefix}:epoch:{user_id}"

    def _exact_key(self, scope_key: str) -> str:
        return f"{self.prefix}:exact:{scope_key}"

    def _vec_key(self, scope_key: str) -> str:
        return f"{self.prefix}:vecs:{scope_key}"

    def _lru_key(self, scope_key: str) -> str:
        return f"{self.prefix}:lru:{scope_key}"

    async def get_epoch(self, user_id: str) -> str:
        if self.redis is None:
            return "0"
        try:
            val = await self.redis.get(self._epoch_key(user_id))
            if isinstance(val, (bytes, bytearray)):
                return val.decode("utf-8")
            return str(val) if val is not None else "0"
        except Exception:
            return "0"

    async def bump_epoch(self, user_id: str) -> str:
        if self.redis is None:
            return "0"
        try:
            nxt = await self.redis.incr(self._epoch_key(user_id))
            return str(nxt)
        except Exception:
            return "0"

    async def get_exact(self, scope_key: str, q_sha: str) -> SemanticCacheEntry | None:
        if self.redis is None:
            return None
        try:
            raw = await self.redis.hget(self._exact_key(scope_key), q_sha)
            return SemanticCacheEntry.from_json(raw) if raw else None
        except Exception as exc:
            logger.debug("SemanticCache Redis get_exact skipped: %s", exc)
            return None

    async def list_entries(self, scope_key: str) -> list[SemanticCacheEntry]:
        if self.redis is None:
            return []
        try:
            raw_map = await self.redis.hgetall(self._vec_key(scope_key))
            if not isinstance(raw_map, dict):
                return []
            out: list[SemanticCacheEntry] = []
            for raw in raw_map.values():
                ent = SemanticCacheEntry.from_json(raw)
                if ent is not None:
                    out.append(ent)
            return out
        except Exception as exc:
            logger.debug("SemanticCache Redis list_entries skipped: %s", exc)
            return []

    async def put_entry(self, entry: SemanticCacheEntry, *, ttl_seconds: int, max_entries: int) -> None:
        if self.redis is None:
            return
        try:
            ttl = max(30, int(ttl_seconds))
            payload = entry.to_json()
            ekey = self._exact_key(entry.scope_key)
            vkey = self._vec_key(entry.scope_key)
            lkey = self._lru_key(entry.scope_key)

            pipe = self.redis.pipeline(transaction=False)
            pipe.hset(ekey, entry.query_sha, payload)
            pipe.expire(ekey, ttl)
            pipe.hset(vkey, entry.query_sha, payload)
            pipe.expire(vkey, ttl)
            pipe.zadd(lkey, {entry.query_sha: time.time()})
            pipe.expire(lkey, ttl)
            await pipe.execute()

            # Evict oldest entries beyond bounded per-scope cap
            size = await self.redis.zcard(lkey)
            if size and int(size) > max_entries:
                overflow = int(size) - max_entries
                victims = await self.redis.zrange(lkey, 0, overflow - 1)
                if victims:
                    victim_ids = [
                        v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
                        for v in victims
                    ]
                    pipe2 = self.redis.pipeline(transaction=False)
                    pipe2.hdel(ekey, *victim_ids)
                    pipe2.hdel(vkey, *victim_ids)
                    pipe2.zrem(lkey, *victim_ids)
                    await pipe2.execute()
        except Exception as exc:
            logger.debug("SemanticCache Redis put_entry skipped: %s", exc)


class SemanticCache:
    """Two-tier (L1 Exact Hash + L2 Cosine Vector) multi-tenant Semantic Cache."""

    def __init__(
        self,
        *,
        store: SemanticCacheStore,
        embedding_client: EmbeddingClient | None = None,
        enabled: bool = True,
        similarity_threshold: float = 0.94,
        ttl_seconds: int = 3600,
        max_entries_per_user: int = 64,
        allow_deterministic_fallback: bool = False,
    ) -> None:
        self.store = store
        self.embedding_client = embedding_client
        self.enabled = enabled
        self.similarity_threshold = float(similarity_threshold)
        self.ttl_seconds = int(ttl_seconds)
        self.max_entries_per_user = max(4, int(max_entries_per_user))
        self.allow_deterministic_fallback = allow_deterministic_fallback

    def check_cacheable(
        self,
        *,
        query: str,
        has_attachments: bool = False,
        has_images: bool = False,
        history_len: int = 0,
        has_pii: bool = False,
        guardrail_flagged: bool = False,
        allow_hitl: bool = True,
        bypass_requested: bool = False,
    ) -> tuple[bool, str]:
        if not self.enabled:
            return False, "disabled"
        if bypass_requested:
            return False, "bypass_requested"
        if not allow_hitl:
            return False, "scheduled_run"
        cleaned = (query or "").strip()
        if len(cleaned) < 4:
            return False, "too_short"
        if has_attachments or has_images:
            return False, "has_attachments"
        if has_pii or guardrail_flagged:
            return False, "sensitive_or_flagged"
        if _REALTIME_KEYWORDS_RE.search(cleaned):
            return False, "realtime_query"
        if history_len > 0 and _DEICTIC_FOLLOWUP_RE.search(cleaned):
            return False, "context_dependent_followup"
        return True, ""

    @staticmethod
    def has_write_side_effects(tool_events: list[dict[str, Any]] | None) -> bool:
        for ev in tool_events or []:
            if str(ev.get("tool") or "") in _WRITE_SIDE_EFFECT_TOOLS:
                return True
        return False

    async def _embed(self, query: str) -> list[float] | None:
        if self.embedding_client is not None and self.embedding_client.is_configured:
            try:
                vec = await self.embedding_client.embed_query(query[:1000])
                if vec:
                    return vec
            except Exception as exc:
                logger.debug("SemanticCache embedding failed: %s", exc)
        if self.allow_deterministic_fallback:
            return deterministic_embedding(query, dim=256)
        return None

    async def _build_scope_key(
        self,
        *,
        user_id: str,
        model_route: str,
        rag_scope: dict[str, Any] | None = None,
    ) -> str:
        epoch = await self.store.get_epoch(user_id)
        rhash = scope_hash(rag_scope)
        return f"{user_id}:{model_route or 'auto'}:{rhash}:e{epoch}"

    async def invalidate_user(self, user_id: str) -> str:
        return await self.store.bump_epoch(user_id)

    async def lookup(
        self,
        *,
        user_id: str,
        query: str,
        model_route: str = "auto",
        rag_scope: dict[str, Any] | None = None,
        has_attachments: bool = False,
        has_images: bool = False,
        history_len: int = 0,
        has_pii: bool = False,
        guardrail_flagged: bool = False,
        allow_hitl: bool = True,
        bypass_requested: bool = False,
    ) -> CacheLookupResult:
        t0 = time.perf_counter()
        ok, reason = self.check_cacheable(
            query=query,
            has_attachments=has_attachments,
            has_images=has_images,
            history_len=history_len,
            has_pii=has_pii,
            guardrail_flagged=guardrail_flagged,
            allow_hitl=allow_hitl,
            bypass_requested=bypass_requested,
        )
        if not ok:
            return CacheLookupResult(
                hit=False,
                hit_type="bypass",
                bypass_reason=reason,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        skey = await self._build_scope_key(user_id=user_id, model_route=model_route, rag_scope=rag_scope)
        q_sha = query_hash(query)

        # L1: O(1) exact hash hit
        exact = await self.store.get_exact(skey, q_sha)
        if exact is not None and exact.response_text:
            return CacheLookupResult(
                hit=True,
                hit_type="hit_exact",
                similarity=1.0,
                entry=exact,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )

        # L2: Semantic cosine similarity search within tenant scope
        q_vec = await self._embed(normalize_query(query))
        if q_vec:
            entries = await self.store.list_entries(skey)
            best_sim = -1.0
            best_entry: SemanticCacheEntry | None = None
            for ent in entries:
                if not ent.embedding or not ent.response_text:
                    continue
                sim = cosine_similarity(q_vec, ent.embedding)
                if sim > best_sim:
                    best_sim = sim
                    best_entry = ent
            if best_entry is not None and best_sim >= self.similarity_threshold:
                return CacheLookupResult(
                    hit=True,
                    hit_type="hit_semantic",
                    similarity=best_sim,
                    entry=best_entry,
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                )

        return CacheLookupResult(
            hit=False,
            hit_type="miss",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    async def store_response(
        self,
        *,
        user_id: str,
        query: str,
        response_text: str,
        model_route: str = "auto",
        model_name: str = "",
        rag_scope: dict[str, Any] | None = None,
        original_tokens: int = 0,
        citations: list[dict[str, Any]] | None = None,
        tool_events: list[dict[str, Any]] | None = None,
    ) -> bool:
        if not self.enabled or not (response_text or "").strip():
            return False
        if self.has_write_side_effects(tool_events):
            return False
        skey = await self._build_scope_key(user_id=user_id, model_route=model_route, rag_scope=rag_scope)
        q_norm = normalize_query(query)
        q_sha = query_hash(query)
        q_vec = await self._embed(q_norm) or []
        entry = SemanticCacheEntry(
            entry_id=q_sha,
            scope_key=skey,
            query_norm=q_norm,
            query_sha=q_sha,
            embedding=q_vec,
            response_text=response_text,
            route=model_route or "auto",
            model=model_name,
            original_tokens=max(0, int(original_tokens)),
            citations=list(citations or []),
        )
        await self.store.put_entry(
            entry,
            ttl_seconds=self.ttl_seconds,
            max_entries=self.max_entries_per_user,
        )
        return True

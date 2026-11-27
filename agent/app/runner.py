from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.cache import RedisCacheStore, SemanticCache
from app.core.config import AgentSettings, get_settings
from app.core.metrics import (
    AGENT_GUARDRAIL_TRIGGERS_TOTAL,
    AGENT_PII_REDACTED_TOTAL,
    AGENT_SEMANTIC_CACHE_LOOKUP_SECONDS,
    AGENT_SEMANTIC_CACHE_REQUESTS_TOTAL,
    AGENT_SEMANTIC_CACHE_TOKENS_SAVED_TOTAL,
)
from app.core.models import EmbeddingClient, ModelRouter, RerankClient
from app.guardrails import GuardrailEngine, PiiVault
from app.core.multimodal import (
    HydratedTurnMedia,
    build_multimodal_user_message,
    extract_inline_file_ids,
    hydrate_turn_attachments,
)
from app.graph.builder import (
    DEFAULT_MAX_TOOL_ITERATIONS,
    _extract_text,
    build_agent_graph,
    extract_turn_memory_standalone,
)
from app.graph.topology import GRAPH_NODES
from app.memory.store import MemoryManager
from app.rag.citations import CitationRegistry
from app.rag.hybrid_retriever import HybridRetriever
from app.tools import parse_tool_error
from app.tools.mcp_client import load_whitz_mcp_tools
from app.tools.sandbox import get_sandbox_executor

logger = logging.getLogger("whitz.agent.runner")

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
TERMINAL_EVENT_NAMES = frozenset({"run.completed", "run.failed", "run.cancelled", "run.interrupted"})
NODE_LABELS = {n["id"]: n["label"] for n in GRAPH_NODES}
ACTIVE_RUNS_SET = "agent:active_runs"
WORKER_HEARTBEAT_KEY = "agent:worker:heartbeat"
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def meta_key(run_id: str) -> str:
    return f"run:{run_id}:meta"


def events_key(run_id: str) -> str:
    return f"run:{run_id}:events"


def cancel_key(run_id: str) -> str:
    return f"run:{run_id}:cancel"


def cancel_channel(run_id: str) -> str:
    return f"run:{run_id}:cancel_ch"


def secret_key(run_id: str) -> str:
    return f"run:{run_id}:secret"


def checkpoint_thread_id(base_thread_id: str, run_id: str) -> str:
    """Scope LangGraph checkpoint per run to prevent cross-turn state pollution while keeping HITL resume durable."""
    base = (base_thread_id or "").strip()
    if not base or base == run_id:
        return run_id
    return f"{base}:{run_id}"


async def publish_event(
    redis: Any,
    run_id: str,
    event_name: str,
    payload: dict[str, Any],
    *,
    ttl_seconds: int = 86400,
    max_len: int = 10000,
    refresh_ttl: bool = True,
) -> str | None:
    if redis is None:
        return None
    data_json = json.dumps(payload, ensure_ascii=False, default=str)
    skey = events_key(run_id)
    if refresh_ttl and hasattr(redis, "pipeline"):
        try:
            pipe = redis.pipeline(transaction=False)
            pipe.xadd(skey, {"event": event_name, "data": data_json}, maxlen=max_len, approximate=True)
            pipe.expire(skey, ttl_seconds)
            res = await pipe.execute()
            return str(res[0]) if res else None
        except Exception:
            pass
    entry_id = await redis.xadd(
        skey,
        {"event": event_name, "data": data_json},
        maxlen=max_len,
        approximate=True,
    )
    if refresh_ttl:
        await redis.expire(skey, ttl_seconds)
    return str(entry_id)


async def load_run_meta(redis: Any, run_id: str) -> dict[str, Any] | None:
    if redis is None:
        return None
    raw = await redis.get(meta_key(run_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


async def save_run_meta(
    redis: Any,
    run_id: str,
    meta: dict[str, Any],
    *,
    ttl_seconds: int = 86400,
) -> None:
    if redis is None:
        return
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    await redis.set(meta_key(run_id), json.dumps(meta, ensure_ascii=False, default=str), ex=ttl_seconds)


async def load_run_secret(redis: Any, run_id: str) -> str:
    if redis is None:
        return ""
    try:
        val = await redis.get(secret_key(run_id))
        return str(val or "")
    except Exception:
        return ""


async def save_run_secret(redis: Any, run_id: str, agent_api_key: str, *, ttl_seconds: int = 86400) -> None:
    if redis is None or not agent_api_key:
        return
    try:
        await redis.set(secret_key(run_id), agent_api_key, ex=ttl_seconds)
    except Exception:
        pass


async def is_cancelled(redis: Any, run_id: str) -> bool:
    if redis is None:
        return False
    try:
        return bool(await redis.get(cancel_key(run_id)))
    except Exception:
        return False


async def _mark_active_run(redis: Any, run_id: str, active: bool) -> None:
    if redis is None:
        return
    try:
        if active and hasattr(redis, "sadd"):
            await redis.sadd(ACTIVE_RUNS_SET, run_id)
        elif not active and hasattr(redis, "srem"):
            await redis.srem(ACTIVE_RUNS_SET, run_id)
    except Exception:
        pass


def build_snapshot_payload(meta: dict[str, Any]) -> dict[str, Any]:
    """Construct a complete, self-contained snapshot for late-joining or reconnecting clients."""
    return {
        "run_id": meta.get("run_id"),
        "conversation_id": meta.get("conversation_id"),
        "status": meta.get("status") or "running",
        "output": meta.get("output") or "",
        "reasoning": meta.get("reasoning") or [],
        "plan": meta.get("plan"),
        "tool_events": meta.get("tool_events") or [],
        "citations": meta.get("citations") or [],
        "rag_metrics": meta.get("rag_metrics"),
        "pending_controls": meta.get("pending_controls") or [],
        "usage": meta.get("usage"),
        "route": meta.get("route"),
        "model": meta.get("model"),
        "last_event_id": meta.get("last_event_id") or "0-0",
        "error": meta.get("error"),
    }


def _extract_chunk_text_and_reasoning(msg_chunk: Any) -> tuple[str, str]:
    text_parts: list[str] = []
    reasoning_parts: list[str] = []

    add_kw = getattr(msg_chunk, "additional_kwargs", None) or {}
    if isinstance(add_kw, dict):
        r_kw = add_kw.get("reasoning_content") or add_kw.get("reasoning")
        if isinstance(r_kw, str) and r_kw:
            reasoning_parts.append(r_kw)

    content = getattr(msg_chunk, "content", None)
    if isinstance(content, str):
        if content:
            text_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = str(block.get("type") or "").lower()
            if btype in ("thinking", "reasoning"):
                t = block.get("thinking") or block.get("reasoning") or block.get("text") or ""
                if isinstance(t, str) and t:
                    reasoning_parts.append(t)
            elif btype == "text":
                t = block.get("text") or ""
                if isinstance(t, str) and t:
                    text_parts.append(t)

    return "".join(text_parts), "".join(reasoning_parts)


def _unpack_stream_item(item: Any) -> tuple[tuple[Any, ...], str, Any]:
    if isinstance(item, tuple) and len(item) == 3:
        ns, mode, chunk = item
        return tuple(ns) if isinstance(ns, (list, tuple)) else (), str(mode), chunk
    if isinstance(item, tuple) and len(item) == 2:
        mode, chunk = item
        return (), str(mode), chunk
    return (), "updates", item


def _clip_str(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "\n... [truncated]"
    return value


def _parse_tool_error(content: Any, status: str | None) -> str | None:
    return parse_tool_error(content, status)


def _build_initial_messages(
    payload: dict[str, Any],
    *,
    hydrated_media: HydratedTurnMedia | None = None,
) -> list[Any]:
    msgs: list[Any] = []
    history = payload.get("conversation_history") or payload.get("history") or []
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "")
            if not content.strip():
                continue
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "assistant":
                msgs.append(AIMessage(content=content))
    input_text = str(payload.get("input") or payload.get("input_text") or "").strip()
    if input_text or (hydrated_media is not None and hydrated_media.content_blocks):
        msgs.append(build_multimodal_user_message(input_text, hydrated_media))
    return msgs


async def _build_runtime_config(
    payload: dict[str, Any],
    *,
    run_id: str,
    redis: Any,
    pool: Any,
    store: Any,
    settings: AgentSettings,
    initial_citations: list[dict[str, Any]] | None = None,
    preloaded_mcp_tools: list[Any] | None = None,
) -> dict[str, Any]:
    agent_namespace = str(payload.get("agent_namespace") or "")
    agent_api_key = str(payload.get("agent_api_key") or "") or await load_run_secret(redis, run_id)
    if preloaded_mcp_tools is not None:
        mcp_tools = list(preloaded_mcp_tools)
    else:
        mcp_tools = []
        if agent_namespace and agent_api_key and settings.internal_mcp_base_url.strip():
            mcp_tools = await load_whitz_mcp_tools(
                internal_mcp_base_url=settings.internal_mcp_base_url,
                agent_namespace=agent_namespace,
                agent_api_key=agent_api_key,
            )

    emb_client = EmbeddingClient(settings=settings, redis_client=redis)
    rerank_client = RerankClient(settings=settings, redis_client=redis)
    model_router = ModelRouter(settings=settings, redis_client=redis)
    hybrid_retriever = HybridRetriever(pool=pool, embedding_client=emb_client, rerank_client=rerank_client)
    citation_registry = CitationRegistry.from_serialized(initial_citations)
    raw_attachments = list(payload.get("attachments") or [])
    input_text = str(payload.get("input") or payload.get("input_text") or "")
    seen_fids: set[str] = set()
    attached_file_ids: list[str] = []
    for a in raw_attachments:
        if isinstance(a, dict) and a.get("attached") and (a.get("file_id") or a.get("id")):
            fid = str(a.get("file_id") or a.get("id"))
            if fid not in seen_fids:
                seen_fids.add(fid)
                attached_file_ids.append(fid)
    for fid in extract_inline_file_ids(input_text):
        if fid not in seen_fids:
            seen_fids.add(fid)
            attached_file_ids.append(fid)
    rag_scope = payload.get("rag_scope") if isinstance(payload.get("rag_scope"), dict) else {}
    memory_manager = MemoryManager(
        store=store,
        pool=pool,
        embedding_client=emb_client,
        rerank_client=rerank_client,
    )
    sandbox_executor = get_sandbox_executor(settings=settings)
    guardrail_engine = GuardrailEngine(
        mode=settings.guardrails_mode,
        pii_redaction_enabled=settings.guardrails_pii_redaction_enabled,
        block_threshold=settings.guardrails_block_threshold,
    )

    skills_list = payload.get("skills") or []
    skills_catalog = {
        str(sk.get("name")): sk
        for sk in skills_list
        if isinstance(sk, dict) and sk.get("name")
    }

    base_thread = str(payload.get("thread_id") or payload.get("conversation_id") or run_id)
    scoped_thread = checkpoint_thread_id(base_thread, run_id)
    max_tool_iters = max(1, int(payload.get("max_tool_iterations") or DEFAULT_MAX_TOOL_ITERATIONS))
    max_subagent_iters = max(8, min(25, max_tool_iters // 5))
    recursion_limit = max(50, max_tool_iters * 3 + max_subagent_iters + 30)
    return {
        "recursion_limit": recursion_limit,
        "configurable": {
            "thread_id": scoped_thread,
            "run_id": run_id,
            "user_id": str(payload.get("user_id") or ""),
            "conversation_id": str(payload.get("conversation_id") or base_thread),
            "conversation_kind": str(payload.get("conversation_kind") or "side"),
            "assistant_name": str(payload.get("assistant_name") or "").strip() or "Whitz",
            "agent_namespace": agent_namespace,
            "guardrail_engine": guardrail_engine,
            "agent_api_key": agent_api_key,
            "internal_mcp_base_url": settings.internal_mcp_base_url,
            "memory_enabled": bool(payload.get("memory_enabled", True)),
            "memory_require_confirm": bool(payload.get("memory_require_confirm", False)),
            "ai_reactions_enabled": bool(payload.get("ai_reactions_enabled", True)),
            "allow_hitl": bool(payload.get("allow_hitl", True)),
            "max_tool_iterations": max_tool_iters,
            "max_subagent_iterations": max_subagent_iters,
            "requested_route": str(payload.get("model_route") or "auto"),
            "timezone": str(payload.get("timezone") or "Asia/Shanghai"),
            "skills_catalog": skills_catalog,
            "mcp_tools": mcp_tools,
            "model_router": model_router,
            "embedding_client": emb_client,
            "rerank_client": rerank_client,
            "hybrid_retriever": hybrid_retriever,
            "citation_registry": citation_registry,
            "attached_file_ids": attached_file_ids,
            "rag_scope": rag_scope,
            "memory_manager": memory_manager,
            "sandbox_executor": sandbox_executor,
            "pool": pool,
            "store": store,
        }
    }


def _active_plan_step(plan: dict[str, Any] | None) -> tuple[int | None, str]:
    """Return 1-based step index and title of the active in_progress plan item, if any."""
    if not isinstance(plan, dict):
        return None, ""
    items = plan.get("items")
    if not isinstance(items, list):
        return None, ""
    for idx, it in enumerate(items, start=1):
        if isinstance(it, dict) and str(it.get("status") or "").lower() == "in_progress":
            return idx, str(it.get("content") or "")[:80]
    return None, ""


class _CoalescedEmitter:
    """Coalesces high-frequency delta events and tracks live snapshot state with serialized meta saves."""

    def __init__(
        self,
        redis: Any,
        run_id: str,
        meta: dict[str, Any],
        settings: AgentSettings,
        meta_lock: asyncio.Lock | None = None,
    ) -> None:
        self.redis = redis
        self.run_id = run_id
        self.meta = meta
        self.meta_lock = meta_lock or asyncio.Lock()
        self.event_ttl = settings.event_stream_ttl_seconds
        self.meta_ttl = settings.run_state_ttl_seconds
        self.max_len = settings.stream_max_len

        self._msg_pending: list[str] = []
        self._reason_pending: list[str] = []
        self._reason_step: int | None = None
        self._reason_title: str = ""
        self._last_flush_ts = time.monotonic()
        self._last_meta_save_ts = time.monotonic()
        self._ttl_counter = 0

    async def emit_delta(
        self,
        kind: str,
        text: str,
        *,
        step: int | None = None,
        title: str = "",
    ) -> None:
        if not text:
            return
        if kind == "message":
            self._msg_pending.append(text)
        else:
            if self._reason_pending and (step != self._reason_step or title != self._reason_title):
                await self.flush_deltas()
            self._reason_step = step
            self._reason_title = title
            self._reason_pending.append(text)

        now = time.monotonic()
        pending_len = sum(len(s) for s in self._msg_pending) + sum(len(s) for s in self._reason_pending)
        if pending_len >= 32 or (now - self._last_flush_ts) >= 0.035:
            await self.flush_deltas()

    async def flush_deltas(self) -> None:
        self._last_flush_ts = time.monotonic()
        if self._reason_pending:
            chunk = "".join(self._reason_pending)
            step = self._reason_step
            title = self._reason_title
            self._reason_pending.clear()
            await self.emit("reasoning.delta", {"text": chunk, "delta": chunk, "step": step, "title": title})
        if self._msg_pending:
            chunk = "".join(self._msg_pending)
            self._msg_pending.clear()
            await self.emit("message.delta", {"text": chunk, "delta": chunk})

    async def emit(self, event_name: str, payload: dict[str, Any], *, force_ttl: bool = False) -> str | None:
        if event_name not in ("message.delta", "reasoning.delta"):
            await self.flush_deltas()
        self._ttl_counter += 1
        refresh_ttl = force_ttl or (self._ttl_counter == 1) or (self._ttl_counter % 25 == 0)
        entry_id = await publish_event(
            self.redis,
            self.run_id,
            event_name,
            payload,
            ttl_seconds=self.event_ttl,
            max_len=self.max_len,
            refresh_ttl=refresh_ttl,
        )
        if entry_id:
            async with self.meta_lock:
                self.meta["last_event_id"] = entry_id
        return entry_id

    async def maybe_checkpoint_meta(
        self,
        *,
        output: str,
        reasoning_blocks: list[dict[str, Any]] | None,
        plan: dict[str, Any] | None,
        tool_events: list[dict[str, Any]],
        usage: dict[str, int],
        route: str,
        model: str,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and (now - self._last_meta_save_ts) < 1.0:
            return
        self._last_meta_save_ts = now
        async with self.meta_lock:
            self.meta["output"] = output
            self.meta["reasoning"] = list(reasoning_blocks) if reasoning_blocks else []
            self.meta["plan"] = plan
            self.meta["tool_events"] = tool_events[-40:]
            self.meta["usage"] = usage
            self.meta["route"] = route
            self.meta["model"] = model
            self.meta["heartbeat_at"] = time.time()
            self.meta["worker_id"] = WORKER_ID
            await save_run_meta(self.redis, self.run_id, self.meta, ttl_seconds=self.meta_ttl)


async def _watch_cancel_and_heartbeat(
    redis: Any,
    run_id: str,
    meta: dict[str, Any],
    settings: AgentSettings,
    target_task: asyncio.Task[Any],
    cancel_flag: dict[str, bool],
    meta_lock: asyncio.Lock | None = None,
) -> None:
    """Concurrently monitors cancel_key / PubSub cancel channel and refreshes run heartbeat."""
    lock = meta_lock or asyncio.Lock()
    pubsub = None
    if redis is not None and hasattr(redis, "pubsub"):
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(cancel_channel(run_id))
        except Exception:
            pubsub = None

    last_hb = time.monotonic()
    try:
        while not target_task.done():
            # 1. Check Pub/Sub instant cancel notification
            if pubsub is not None:
                try:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.25)
                    if msg is not None:
                        cancel_flag["cancelled"] = True
                        target_task.cancel()
                        return
                except Exception:
                    await asyncio.sleep(0.25)
            else:
                await asyncio.sleep(0.25)

            # 2. Check durable cancel_key
            if await is_cancelled(redis, run_id):
                cancel_flag["cancelled"] = True
                target_task.cancel()
                return

            # 3. Refresh heartbeat every 10s under meta_lock so snapshot consistency is preserved
            now = time.monotonic()
            if (now - last_hb) >= 10.0:
                last_hb = now
                try:
                    async with lock:
                        meta["heartbeat_at"] = time.time()
                        meta["worker_id"] = WORKER_ID
                        await save_run_meta(redis, run_id, meta, ttl_seconds=settings.run_state_ttl_seconds)
                except Exception:
                    pass
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(cancel_channel(run_id))
                await pubsub.aclose()
            except Exception:
                pass


async def _stream_graph(
    *,
    graph: Any,
    graph_input: Any,
    config: dict[str, Any],
    run_id: str,
    meta: dict[str, Any],
    redis: Any,
    settings: AgentSettings,
) -> None:
    meta_ttl = settings.run_state_ttl_seconds
    meta_lock = asyncio.Lock()
    emitter = _CoalescedEmitter(redis, run_id, meta, settings, meta_lock=meta_lock)

    node_started_at: dict[str, float] = {}
    # Restore pending started_tools across HITL resume so args & wall-clock duration are never lost
    started_tools: dict[str, tuple[str, Any, float]] = {}
    raw_saved_started = meta.get("started_tools")
    if isinstance(raw_saved_started, dict):
        for cid, entry in raw_saved_started.items():
            if isinstance(entry, dict):
                started_tools[str(cid)] = (
                    str(entry.get("tool") or "tool"),
                    entry.get("args"),
                    float(entry.get("started_ts") or time.time()),
                )

    # Preserve prior partial output / structured reasoning blocks / tool_events across HITL resume
    reasoning_blocks_state: list[dict[str, Any]] = []
    if isinstance(meta.get("reasoning"), list):
        for b in meta["reasoning"]:
            if isinstance(b, dict):
                reasoning_blocks_state.append(
                    {
                        "step": b.get("step"),
                        "title": str(b.get("title") or ""),
                        "text": str(b.get("text") or ""),
                    }
                )

    def _append_reasoning_text(delta_txt: str, step: int | None, title: str) -> None:
        if not delta_txt:
            return
        if reasoning_blocks_state and reasoning_blocks_state[-1].get("step") == step and reasoning_blocks_state[-1].get("title") == title:
            reasoning_blocks_state[-1]["text"] += delta_txt
        else:
            reasoning_blocks_state.append({"step": step, "title": title, "text": delta_txt})

    buffered_text: list[str] = [str(meta.get("output") or "")] if meta.get("output") else []
    tool_events: list[dict[str, Any]] = list(meta.get("tool_events") or [])
    latest_citations: list[dict[str, Any]] = list(meta.get("citations") or [])
    latest_rag_metrics: dict[str, Any] = dict(meta.get("rag_metrics") or {})
    last_ai_text = ""
    latest_plan: dict[str, Any] | None = meta.get("plan")
    latest_usage: dict[str, int] = dict(meta.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    selected_route = str(meta.get("route") or payload_route(meta))
    selected_model = str(meta.get("model") or "")
    called_memory_propose = bool(meta.get("called_memory_propose", False))

    async def _run_loop() -> str:
        nonlocal last_ai_text, latest_plan, latest_usage, selected_route, selected_model, called_memory_propose, latest_citations
        async for raw_item in graph.astream(
            graph_input,
            config=config,
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True,
        ):
            if await is_cancelled(redis, run_id):
                return "cancelled"

            ns, mode, chunk = _unpack_stream_item(raw_item)
            is_root = len(ns) == 0

            if mode == "custom" and isinstance(chunk, dict):
                ev_type = str(chunk.get("type") or "")
                if ev_type == "graph.node":
                    node_name = str(chunk.get("node") or "")
                    if node_name:
                        node_started_at[node_name] = time.monotonic()
                        if chunk.get("route"):
                            selected_route = str(chunk["route"])
                        if chunk.get("model"):
                            selected_model = str(chunk["model"])
                        await emitter.emit(
                            "graph.node",
                            {
                                "node": node_name,
                                "status": str(chunk.get("status") or "running"),
                                "label": chunk.get("label") or NODE_LABELS.get(node_name, node_name),
                                "route": selected_route or None,
                                "model": selected_model or None,
                                "duration_ms": None,
                            },
                        )
                elif ev_type == "plan.updated":
                    latest_plan = {"items": list(chunk.get("items") or [])}
                    await emitter.emit("plan.updated", latest_plan)
                    await emitter.maybe_checkpoint_meta(
                        output=last_ai_text or "".join(buffered_text),
                        reasoning_blocks=reasoning_blocks_state,
                        plan=latest_plan,
                        tool_events=tool_events,
                        usage=latest_usage,
                        route=selected_route,
                        model=selected_model,
                        force=True,
                    )
                elif ev_type == "tool.started":
                    cur_step, _ = _active_plan_step(latest_plan)
                    payload = {k: v for k, v in chunk.items() if k != "type"}
                    payload.setdefault("step", cur_step)
                    tool_events.append(payload)
                    await emitter.emit("tool.started", payload)
                elif ev_type == "tool.completed":
                    cur_step, _ = _active_plan_step(latest_plan)
                    payload = {k: v for k, v in chunk.items() if k != "type"}
                    payload.setdefault("step", cur_step)
                    cid = payload.get("call_id")
                    updated = False
                    for idx, te in enumerate(tool_events):
                        if cid and te.get("call_id") == cid:
                            tool_events[idx] = payload
                            updated = True
                            break
                    if not updated:
                        tool_events.append(payload)
                    await emitter.emit("tool.completed", payload)
                elif ev_type == "rag.context":
                    cites = list(chunk.get("citations") or [])
                    if cites:
                        latest_citations = cites
                        async with meta_lock:
                            meta["citations"] = latest_citations
                    diag = chunk.get("diagnostics")
                    if isinstance(diag, dict) and diag:
                        stage_key = str(chunk.get("stage") or diag.get("stage") or "prefetch")
                        if stage_key == "prefetch":
                            latest_rag_metrics["prefetch_ms"] = diag.get("latency_ms", 0.0)
                            latest_rag_metrics["used_llm_rewrite"] = bool(diag.get("used_llm_rewrite", False))
                        latest_rag_metrics["hits_by_source"] = diag.get("hits_by_source") or latest_rag_metrics.get("hits_by_source") or {}
                        latest_rag_metrics["top_score"] = max(
                            float(latest_rag_metrics.get("top_score") or 0.0),
                            float(diag.get("top_score") or 0.0),
                        )
                        latest_rag_metrics["corrective_retries"] = int(latest_rag_metrics.get("corrective_retries") or 0) + int(
                            diag.get("corrective_retries") or 0
                        )
                        latest_rag_metrics["citations_count"] = len(latest_citations)
                        async with meta_lock:
                            meta["rag_metrics"] = latest_rag_metrics
                    await emitter.emit(
                        "rag.context",
                        {
                            "stage": str(chunk.get("stage") or "prefetch"),
                            "citations": latest_citations,
                            "diagnostics": diag if isinstance(diag, dict) else {},
                        },
                    )
                elif ev_type:
                    payload = {k: v for k, v in chunk.items() if k != "type"}
                    await emitter.emit(ev_type, payload)

            elif mode == "messages":
                if not is_root:
                    continue
                if isinstance(chunk, tuple) and len(chunk) == 2:
                    msg_chunk, metadata = chunk
                else:
                    msg_chunk, metadata = chunk, {}
                langgraph_node = (metadata or {}).get("langgraph_node") if isinstance(metadata, dict) else None
                if langgraph_node and langgraph_node != "agent":
                    continue
                txt, r_txt = _extract_chunk_text_and_reasoning(msg_chunk)
                if r_txt:
                    cur_step, cur_title = _active_plan_step(latest_plan)
                    _append_reasoning_text(r_txt, cur_step, cur_title)
                    await emitter.emit_delta("reasoning", r_txt, step=cur_step, title=cur_title)
                if txt:
                    buffered_text.append(txt)
                    await emitter.emit_delta("message", txt)
                if txt or r_txt:
                    await emitter.maybe_checkpoint_meta(
                        output=last_ai_text or "".join(buffered_text),
                        reasoning_blocks=reasoning_blocks_state,
                        plan=latest_plan,
                        tool_events=tool_events,
                        usage=latest_usage,
                        route=selected_route,
                        model=selected_model,
                    )

            elif mode == "updates" and isinstance(chunk, dict):
                if not is_root:
                    continue

                if "__interrupt__" in chunk:
                    await emitter.flush_deltas()
                    interrupts = chunk.get("__interrupt__") or ()
                    intr = interrupts[0] if interrupts else None
                    val = getattr(intr, "value", intr)
                    if not isinstance(val, dict):
                        val = {"kind": "clarify", "preview": str(val)}
                    kind = str(val.get("kind") or "clarify").lower()
                    tool_name = str(val.get("tool") or ("execute_code" if kind == "approval" else "clarify"))
                    req_id = str(val.get("call_id") or val.get("request_id") or uuid.uuid4().hex)
                    gen = int(meta.get("execution_generation") or 0) + 1
                    control = {
                        "request_id": req_id,
                        "prompt_id": req_id,
                        "execution_generation": gen,
                        "kind": kind,
                        "tool": tool_name,
                        "preview": val.get("preview"),
                        "detail": val,
                    }
                    async with meta_lock:
                        meta["execution_generation"] = gen
                        meta["status"] = "waiting_for_approval" if kind == "approval" else "waiting_for_clarify"
                        meta["pending_controls"] = [control]
                        meta["citations"] = latest_citations
                        meta["called_memory_propose"] = called_memory_propose
                        meta["started_tools"] = {
                            cid: {"tool": tn, "args": ta, "started_ts": ts}
                            for cid, (tn, ta, ts) in started_tools.items()
                        }
                    await emitter.emit(
                        "graph.node",
                        {
                            "node": "hitl_gate",
                            "status": "interrupted",
                            "label": NODE_LABELS.get("hitl_gate", "hitl_gate"),
                            "route": selected_route or None,
                            "model": selected_model or None,
                            "duration_ms": None,
                        },
                    )
                    ev_name = "approval.request" if kind == "approval" else "clarify.request"
                    await emitter.emit(ev_name, control, force_ttl=True)
                    await emitter.maybe_checkpoint_meta(
                        output=last_ai_text or "".join(buffered_text),
                        reasoning_blocks=reasoning_blocks_state,
                        plan=latest_plan,
                        tool_events=tool_events,
                        usage=latest_usage,
                        route=selected_route,
                        model=selected_model,
                        force=True,
                    )
                    return "interrupted"

                for node_name, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    t_start = node_started_at.pop(node_name, None)
                    dur_ms = round((time.monotonic() - t_start) * 1000.0, 1) if t_start is not None else None
                    if update.get("selected_route"):
                        selected_route = str(update["selected_route"])
                    if update.get("selected_model"):
                        selected_model = str(update["selected_model"])
                    if isinstance(update.get("plan"), dict):
                        latest_plan = update["plan"]
                    if isinstance(update.get("usage"), dict):
                        latest_usage = dict(update["usage"])
                    if isinstance(update.get("citations"), list) and update["citations"]:
                        latest_citations = list(update["citations"])

                    await emitter.emit(
                        "graph.node",
                        {
                            "node": node_name,
                            "status": "completed",
                            "label": NODE_LABELS.get(node_name, node_name),
                            "route": selected_route or None,
                            "model": selected_model or None,
                            "duration_ms": dur_ms,
                        },
                    )

                    cur_step, cur_title = _active_plan_step(latest_plan)
                    for msg in update.get("messages") or []:
                        if isinstance(msg, AIMessage):
                            if getattr(msg, "tool_calls", None):
                                await emitter.flush_deltas()
                                interim = "".join(buffered_text).strip()
                                if interim:
                                    buffered_text.clear()
                                    await emitter.emit(
                                        "commentary",
                                        {"text": interim, "step": cur_step, "title": cur_title, "already_streamed": True},
                                    )
                                for tc in msg.tool_calls:
                                    cid = str(tc.get("id") or uuid.uuid4().hex)
                                    tname = str(tc.get("name") or "tool")
                                    if tname == "memory_propose":
                                        called_memory_propose = True
                                    targs = tc.get("args")
                                    if cid not in started_tools:
                                        started_tools[cid] = (tname, targs, time.time())
                                        ev_obj = {
                                            "tool": tname,
                                            "preview": targs,
                                            "args": targs,
                                            "call_id": cid,
                                            "step": cur_step,
                                            "status": "running",
                                        }
                                        tool_events.append(ev_obj)
                                        await emitter.emit("tool.started", ev_obj)
                            else:
                                ai_txt = _extract_text(msg.content)
                                if ai_txt.strip():
                                    last_ai_text = ai_txt

                        elif isinstance(msg, ToolMessage):
                            cid = str(getattr(msg, "tool_call_id", "") or "")
                            raw_name = str(getattr(msg, "name", "") or "")
                            targs = None
                            dur_tool_ms = None
                            orig_name = ""
                            if cid in started_tools:
                                orig_name, targs, t0 = started_tools.pop(cid)
                                dur_tool_ms = round(max(0.0, (time.time() - t0) * 1000.0), 1)
                            tname = raw_name or orig_name or "tool"
                            if tname == "memory_propose":
                                called_memory_propose = True
                            err = _parse_tool_error(msg.content, getattr(msg, "status", None))
                            # Preserve original args from prior tool_events if started_tools didn't have it
                            if targs is None and cid:
                                for te in tool_events:
                                    if te.get("call_id") == cid and te.get("args") is not None:
                                        targs = te.get("args")
                                        break
                            done_obj = {
                                "tool": tname,
                                "preview": _clip_str(msg.content, 8000),
                                "args": targs,
                                "result": _clip_str(msg.content, 24000),
                                "error": err,
                                "duration": dur_tool_ms,
                                "duration_ms": dur_tool_ms,
                                "call_id": cid or None,
                                "step": cur_step,
                                "status": "failed" if err else "completed",
                            }
                            updated = False
                            for idx, te in enumerate(tool_events):
                                if cid and te.get("call_id") == cid:
                                    done_obj["step"] = te.get("step") if te.get("step") is not None else cur_step
                                    tool_events[idx] = done_obj
                                    updated = True
                                    break
                            if not updated:
                                tool_events.append(done_obj)
                            await emitter.emit("tool.completed", done_obj)

                    await emitter.maybe_checkpoint_meta(
                        output=last_ai_text or "".join(buffered_text),
                        reasoning_blocks=reasoning_blocks_state,
                        plan=latest_plan,
                        tool_events=tool_events,
                        usage=latest_usage,
                        route=selected_route,
                        model=selected_model,
                    )
        return "completed"

    cancel_flag = {"cancelled": False}
    loop_task = asyncio.create_task(_run_loop())
    watcher_task = asyncio.create_task(
        _watch_cancel_and_heartbeat(redis, run_id, meta, settings, loop_task, cancel_flag, meta_lock=meta_lock)
    )
    timed_out = False
    outcome = "completed"
    try:
        async with asyncio.timeout(max(5, int(settings.run_max_seconds))):
            outcome = await loop_task
    except asyncio.CancelledError:
        if cancel_flag["cancelled"] or await is_cancelled(redis, run_id):
            outcome = "cancelled"
        else:
            outcome = "cancelled"
            raise
    except TimeoutError:
        timed_out = True
        loop_task.cancel()
        try:
            await loop_task
        except (asyncio.CancelledError, Exception):
            pass
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except (asyncio.CancelledError, Exception):
            pass

    await emitter.flush_deltas()
    partial = last_ai_text or "".join(buffered_text)
    reasoning_blocks = list(reasoning_blocks_state) if reasoning_blocks_state else None

    if timed_out:
        async with meta_lock:
            meta["status"] = "failed"
            meta["error"] = "运行超时"
            meta["output"] = partial
            meta["plan"] = latest_plan
            meta["usage"] = latest_usage
            meta["reasoning"] = reasoning_blocks
            meta["citations"] = latest_citations
            meta["rag_metrics"] = latest_rag_metrics or None
            meta["pending_controls"] = []
            meta.pop("started_tools", None)
        await emitter.emit(
            "run.failed",
            {"error": "运行超过时长上限，已终止", "output": partial, "usage": latest_usage, "plan": latest_plan},
            force_ttl=True,
        )
        async with meta_lock:
            await save_run_meta(redis, run_id, meta, ttl_seconds=meta_ttl)
        return

    if outcome == "interrupted":
        return

    if outcome == "cancelled":
        async with meta_lock:
            meta["status"] = "cancelled"
            meta["output"] = partial
            meta["plan"] = latest_plan
            meta["usage"] = latest_usage
            meta["reasoning"] = reasoning_blocks
            meta["citations"] = latest_citations
            meta["rag_metrics"] = latest_rag_metrics or None
            meta["pending_controls"] = []
            meta.pop("started_tools", None)
        await emitter.emit(
            "run.cancelled",
            {
                "error": "运行已取消",
                "output": partial,
                "plan": latest_plan,
                "usage": latest_usage,
                "reasoning": reasoning_blocks,
            },
            force_ttl=True,
        )
        async with meta_lock:
            await save_run_meta(redis, run_id, meta, ttl_seconds=meta_ttl)
        return

    async with meta_lock:
        meta["status"] = "completed"
        meta["output"] = partial
        meta["usage"] = latest_usage
        meta["plan"] = latest_plan
        meta["reasoning"] = reasoning_blocks
        meta["tool_events"] = tool_events[-40:]
        meta["citations"] = latest_citations
        meta["rag_metrics"] = latest_rag_metrics or None
        meta["pending_controls"] = []
        meta["route"] = selected_route
        meta["model"] = selected_model
        meta["called_memory_propose"] = called_memory_propose
        meta.pop("started_tools", None)
    await emitter.emit(
        "run.completed",
        {
            "output": partial,
            "usage": latest_usage,
            "plan": latest_plan,
            "reasoning": reasoning_blocks,
            "citations": latest_citations or None,
            "rag_metrics": latest_rag_metrics or None,
        },
        force_ttl=True,
    )
    async with meta_lock:
        await save_run_meta(redis, run_id, meta, ttl_seconds=meta_ttl)


def payload_route(meta: dict[str, Any]) -> str:
    payload = meta.get("payload") or {}
    return str(payload.get("model_route") or "auto")


def _sanitized_meta_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Never persist plaintext agent_api_key inside run:{id}:meta."""
    clean = dict(payload)
    clean.pop("agent_api_key", None)
    return clean


async def _maybe_dispatch_async_memory_extract(
    *,
    meta: dict[str, Any],
    payload: dict[str, Any],
    arq_pool: Any,
) -> None:
    if meta.get("status") != "completed":
        return
    if not bool(payload.get("memory_enabled", True)) or bool(meta.get("called_memory_propose")):
        return
    user_text = str(payload.get("input") or payload.get("input_text") or "").strip()
    assistant_text = str(meta.get("output") or "").strip()
    if len(user_text) < 12 or not assistant_text:
        return
    job_payload = {
        "user_id": str(meta.get("user_id") or payload.get("user_id") or ""),
        "agent_namespace": str(payload.get("agent_namespace") or ""),
        "conversation_id": str(meta.get("conversation_id") or payload.get("conversation_id") or ""),
        "user_text": user_text[:1500],
        "assistant_text": assistant_text[:1500],
        "memory_index": str(payload.get("memory_index") or "")[:1000],
        "memory_require_confirm": bool(payload.get("memory_require_confirm", False)),
    }
    if arq_pool is not None and hasattr(arq_pool, "enqueue_job"):
        try:
            await arq_pool.enqueue_job(
                "extract_turn_memory_job",
                job_payload,
                _job_id=f"memext:{meta.get('run_id') or uuid.uuid4().hex}",
            )
        except Exception as exc:
            logger.debug("Failed to enqueue extract_turn_memory_job: %s", exc)


async def execute_run(
    run_id: str,
    payload: dict[str, Any],
    *,
    redis: Any,
    pool: Any = None,
    checkpointer: Any = None,
    store: Any = None,
    settings: AgentSettings | None = None,
    compiled_graph: Any = None,
    arq_pool: Any = None,
    async_memory_extract: bool = False,
) -> dict[str, Any]:
    s = settings or get_settings()
    s.configure_langsmith()

    raw_api_key = str(payload.get("agent_api_key") or "")
    if raw_api_key:
        await save_run_secret(redis, run_id, raw_api_key, ttl_seconds=s.run_state_ttl_seconds)

    meta = await load_run_meta(redis, run_id) or {
        "run_id": run_id,
        "thread_id": str(payload.get("thread_id") or payload.get("conversation_id") or run_id),
        "conversation_id": str(payload.get("conversation_id") or ""),
        "user_id": str(payload.get("user_id") or ""),
        "execution_generation": 0,
    }
    meta["payload"] = _sanitized_meta_payload(payload)

    if await is_cancelled(redis, run_id) or meta.get("status") == "cancelled":
        if meta.get("status") != "cancelled":
            meta["status"] = "cancelled"
            meta["pending_controls"] = []
            entry_id = await publish_event(
                redis,
                run_id,
                "run.cancelled",
                {"error": "运行已取消", "output": ""},
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )
            if entry_id:
                meta["last_event_id"] = entry_id
            await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        return meta

    meta["status"] = "running"
    meta["heartbeat_at"] = time.time()
    meta["worker_id"] = WORKER_ID
    await _mark_active_run(redis, run_id, True)
    entry_id = await publish_event(
        redis,
        run_id,
        "run.started",
        {
            "run_id": run_id,
            "thread_id": meta["thread_id"],
            "conversation_id": meta["conversation_id"],
            "route": str(payload.get("model_route") or "auto"),
        },
        ttl_seconds=s.event_stream_ttl_seconds,
        max_len=s.stream_max_len,
    )
    if entry_id:
        meta["last_event_id"] = entry_id
    await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)

    try:
        agent_namespace = str(payload.get("agent_namespace") or "")
        agent_api_key = raw_api_key or await load_run_secret(redis, run_id)
        raw_attachments = list(payload.get("attachments") or [])
        input_text = str(payload.get("input") or payload.get("input_text") or "")

        # --- Stage 1: Input Security Guardrail (Prompt Injection + PII Vault) ---
        guardrail_engine = GuardrailEngine(
            mode=s.guardrails_mode,
            pii_redaction_enabled=s.guardrails_pii_redaction_enabled,
            block_threshold=s.guardrails_block_threshold,
        )
        pii_vault = PiiVault()
        guardrail_events: list[dict[str, Any]] = []
        in_decision = guardrail_engine.inspect_input(input_text, vault=pii_vault)
        if in_decision.action != "allow":
            ev_payload = in_decision.to_event_payload()
            guardrail_events.append(ev_payload)
            cat = in_decision.matches[0].category if in_decision.matches else ("pii" if in_decision.pii_count else "policy")
            AGENT_GUARDRAIL_TRIGGERS_TOTAL.labels(stage="input", action=in_decision.action, category=cat).inc()
            for etype, cnt in in_decision.pii_types.items():
                AGENT_PII_REDACTED_TOTAL.labels(entity_type=etype).inc(cnt)
            await publish_event(
                redis,
                run_id,
                "guardrail.event",
                ev_payload,
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )

        if not in_decision.allowed:
            refusal = in_decision.reason or "该请求触发了安全护栏策略，无法执行。"
            meta["status"] = "completed"
            meta["output"] = refusal
            meta["guardrail_events"] = guardrail_events
            meta["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            meta["pending_controls"] = []
            await publish_event(
                redis,
                run_id,
                "message.delta",
                {"delta": refusal},
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )
            entry_id = await publish_event(
                redis,
                run_id,
                "run.completed",
                {
                    "output": refusal,
                    "usage": meta["usage"],
                    "guardrail_events": guardrail_events,
                },
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )
            if entry_id:
                meta["last_event_id"] = entry_id
            await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
            return meta

        effective_payload = dict(payload)
        if in_decision.pii_count > 0 and in_decision.sanitized_text != input_text:
            if "input" in effective_payload:
                effective_payload["input"] = in_decision.sanitized_text
            if "input_text" in effective_payload:
                effective_payload["input_text"] = in_decision.sanitized_text
            input_text = in_decision.sanitized_text

        seen_fids: set[str] = set()
        attached_fids: list[str] = []
        for a in raw_attachments:
            if isinstance(a, dict) and a.get("attached") and (a.get("file_id") or a.get("id")):
                fid = str(a.get("file_id") or a.get("id"))
                if fid not in seen_fids:
                    seen_fids.add(fid)
                    attached_fids.append(fid)
        for fid in extract_inline_file_ids(input_text):
            if fid not in seen_fids:
                seen_fids.add(fid)
                attached_fids.append(fid)

        # --- Stage 2: Multi-Tenant Semantic Cache Fast-Path ---
        rag_scope_dict = dict(payload.get("rag_scope") or {}) if isinstance(payload.get("rag_scope"), dict) else {}
        history_list = payload.get("conversation_history") or payload.get("history") or []
        req_route = str(payload.get("model_route") or "auto")
        scache = SemanticCache(
            store=RedisCacheStore(redis),
            embedding_client=EmbeddingClient(settings=s, redis_client=redis),
            enabled=s.semantic_cache_enabled and redis is not None,
            similarity_threshold=s.semantic_cache_similarity_threshold,
            ttl_seconds=s.semantic_cache_ttl_seconds,
            max_entries_per_user=s.semantic_cache_max_entries_per_user,
        )
        cache_res = await scache.lookup(
            user_id=meta["user_id"],
            query=input_text,
            model_route=req_route,
            rag_scope=rag_scope_dict,
            has_attachments=bool(attached_fids),
            has_images=any(isinstance(a, dict) and a.get("category") == "image" and a.get("attached") for a in raw_attachments),
            history_len=len(history_list) if isinstance(history_list, list) else 0,
            has_pii=in_decision.pii_count > 0,
            guardrail_flagged=bool(in_decision.matches),
            allow_hitl=bool(payload.get("allow_hitl", True)),
            bypass_requested=bool(payload.get("bypass_cache", False)),
        )
        AGENT_SEMANTIC_CACHE_REQUESTS_TOTAL.labels(result=cache_res.hit_type).inc()
        AGENT_SEMANTIC_CACHE_LOOKUP_SECONDS.observe(cache_res.latency_ms / 1000.0)

        if cache_res.hit and cache_res.entry is not None:
            cached = cache_res.entry
            if cached.original_tokens > 0:
                AGENT_SEMANTIC_CACHE_TOKENS_SAVED_TOTAL.inc(cached.original_tokens)
            cache_meta = cache_res.to_meta()
            meta["status"] = "completed"
            meta["output"] = cached.response_text
            meta["route"] = cached.route
            meta["model"] = cached.model or "semantic-cache"
            meta["citations"] = cached.citations
            meta["cache_meta"] = cache_meta
            meta["rag_metrics"] = {"cache_hit": True, "cache_hit_type": cache_res.hit_type, "cache_similarity": round(cache_res.similarity, 4)}
            meta["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens_saved": cached.original_tokens}
            meta["pending_controls"] = []
            await publish_event(
                redis,
                run_id,
                "semantic_cache.hit",
                cache_meta,
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )
            await publish_event(
                redis,
                run_id,
                "message.delta",
                {"delta": cached.response_text},
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )
            entry_id = await publish_event(
                redis,
                run_id,
                "run.completed",
                {
                    "output": cached.response_text,
                    "usage": meta["usage"],
                    "citations": cached.citations or None,
                    "rag_metrics": meta["rag_metrics"],
                    "cache_meta": cache_meta,
                },
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )
            if entry_id:
                meta["last_event_id"] = entry_id
            await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
            return meta

        # Parallelize Turn-0 MCP tool discovery & multimodal attachment hydration to slash TTFT!
        async def _load_mcp() -> list[Any]:
            if agent_namespace and agent_api_key and s.internal_mcp_base_url.strip():
                return await load_whitz_mcp_tools(
                    internal_mcp_base_url=s.internal_mcp_base_url,
                    agent_namespace=agent_namespace,
                    agent_api_key=agent_api_key,
                )
            return []

        async def _hydrate_media() -> HydratedTurnMedia | None:
            if not attached_fids:
                return None
            probe_router = ModelRouter(settings=s, redis_client=redis)
            target_ep = probe_router.endpoint_for("vision" if probe_router.endpoint_for("vision").model else "default")
            primary_ep = probe_router.endpoint_for("default")
            prefer_img_mode = (
                "base64"
                if (s.llm_image_delivery_mode == "base64" or await probe_router.is_capability_unsupported("image_url", target_ep))
                else s.llm_image_delivery_mode
            )
            allow_pdf = (
                s.llm_native_pdf_mode != "disabled"
                and not await probe_router.is_capability_unsupported("native_pdf", primary_ep)
            )
            return await hydrate_turn_attachments(
                internal_mcp_base_url=s.internal_mcp_base_url,
                agent_namespace=agent_namespace,
                agent_api_key=agent_api_key,
                conversation_id=meta["conversation_id"],
                attached_file_ids=attached_fids,
                prefer_image_mode=prefer_img_mode,
                allow_native_pdf=allow_pdf,
                settings=s,
            )

        preloaded_mcp, hydrated_media = await asyncio.gather(_load_mcp(), _hydrate_media())

        config = await _build_runtime_config(
            payload,
            run_id=run_id,
            redis=redis,
            pool=pool,
            store=store,
            settings=s,
            preloaded_mcp_tools=preloaded_mcp,
        )
        graph = compiled_graph if compiled_graph is not None else build_agent_graph(checkpointer=checkpointer, store=store)
        graph_input = {
            "messages": _build_initial_messages(effective_payload, hydrated_media=hydrated_media),
            "run_id": run_id,
            "thread_id": meta["thread_id"],
            "conversation_id": meta["conversation_id"],
            "conversation_kind": str(payload.get("conversation_kind") or "side"),
            "assistant_name": str(payload.get("assistant_name") or "").strip() or "Whitz",
            "rolling_summary": str(payload.get("rolling_summary") or ""),
            "cross_chat_context": str(payload.get("cross_chat_context") or ""),
            "memory_index": str(payload.get("memory_index") or ""),
            "pinned_memories": str(payload.get("pinned_memories") or ""),
            "user_id": meta["user_id"],
            "agent_namespace": agent_namespace,
            "persona": str(payload.get("persona") or ""),
            "profile_context": str(payload.get("profile_context") or ""),
            "timezone": str(payload.get("timezone") or "Asia/Shanghai"),
            "instructions": str(payload.get("instructions") or ""),
            "attachments": list(payload.get("attachments") or []),
            "directly_delivered_file_ids": list(hydrated_media.directly_delivered_ids) if hydrated_media else [],
            "attachment_delivery_map": dict(hydrated_media.delivery_map) if hydrated_media else {},
            "skills": list(payload.get("skills") or []),
            "requested_skills": list(payload.get("requested_skills") or payload.get("skill_names") or []),
            "memory_enabled": bool(payload.get("memory_enabled", True)),
            "memory_require_confirm": bool(payload.get("memory_require_confirm", False)),
            "ai_reactions_enabled": bool(payload.get("ai_reactions_enabled", True)),
            "allow_hitl": bool(payload.get("allow_hitl", True)),
            "max_tool_iterations": max(1, int(payload.get("max_tool_iterations") or DEFAULT_MAX_TOOL_ITERATIONS)),
            "requested_route": str(payload.get("model_route") or "auto"),
            "rag_scope": dict(payload.get("rag_scope") or {}) if isinstance(payload.get("rag_scope"), dict) else {},
            "async_memory_extract": bool(async_memory_extract),
        }
        await _stream_graph(
            graph=graph,
            graph_input=graph_input,
            config=config,
            run_id=run_id,
            meta=meta,
            redis=redis,
            settings=s,
        )

        # --- Stage 3: Output Guardrail, PII Restore & Semantic Cache Write-Back ---
        if meta.get("status") == "completed":
            raw_out = str(meta.get("output") or "")
            out_dec = guardrail_engine.inspect_output(raw_out, vault=pii_vault)
            if out_dec.action != "allow":
                ev_out = out_dec.to_event_payload()
                guardrail_events.append(ev_out)
                cat = out_dec.matches[0].category if out_dec.matches else "output_policy"
                AGENT_GUARDRAIL_TRIGGERS_TOTAL.labels(stage="output", action=out_dec.action, category=cat).inc()
            if out_dec.sanitized_text != raw_out:
                meta["output"] = out_dec.sanitized_text
                await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
            if guardrail_events:
                meta["guardrail_events"] = guardrail_events
                await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)

            if cache_res.hit_type == "miss" and out_dec.action == "allow" and pii_vault.entity_count == 0:
                usage_dict = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
                total_tok = int(usage_dict.get("total_tokens") or 0)
                await scache.store_response(
                    user_id=meta["user_id"],
                    query=input_text,
                    response_text=str(meta.get("output") or ""),
                    model_route=str(meta.get("route") or req_route),
                    model_name=str(meta.get("model") or ""),
                    rag_scope=rag_scope_dict,
                    original_tokens=total_tok,
                    citations=list(meta.get("citations") or []),
                    tool_events=list(meta.get("tool_events") or []),
                )
        if async_memory_extract:
            await _maybe_dispatch_async_memory_extract(meta=meta, payload=payload, arq_pool=arq_pool)
    except asyncio.CancelledError:
        meta["status"] = "cancelled"
        meta["error"] = "工作进程重启或任务已取消"
        meta["pending_controls"] = []
        entry_id = await publish_event(
            redis,
            run_id,
            "run.cancelled",
            {"error": meta["error"], "output": meta.get("output") or ""},
            ttl_seconds=s.event_stream_ttl_seconds,
            max_len=s.stream_max_len,
        )
        if entry_id:
            meta["last_event_id"] = entry_id
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        raise
    except Exception as exc:
        logger.exception("Run %s failed", run_id)
        meta["status"] = "failed"
        meta["error"] = str(exc)
        meta["pending_controls"] = []
        entry_id = await publish_event(
            redis,
            run_id,
            "run.failed",
            {"error": str(exc), "output": meta.get("output") or ""},
            ttl_seconds=s.event_stream_ttl_seconds,
            max_len=s.stream_max_len,
        )
        if entry_id:
            meta["last_event_id"] = entry_id
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
    finally:
        await _mark_active_run(redis, run_id, False)

    return meta


async def resume_run(
    run_id: str,
    resume_payload: Any,
    *,
    redis: Any,
    pool: Any = None,
    checkpointer: Any = None,
    store: Any = None,
    settings: AgentSettings | None = None,
    compiled_graph: Any = None,
    arq_pool: Any = None,
    async_memory_extract: bool = False,
) -> dict[str, Any]:
    s = settings or get_settings()
    s.configure_langsmith()

    meta = await load_run_meta(redis, run_id)
    if meta is None:
        raise ValueError(f"Unknown run_id: {run_id}")

    if await is_cancelled(redis, run_id) or meta.get("status") == "cancelled":
        if meta.get("status") != "cancelled":
            meta["status"] = "cancelled"
            meta["pending_controls"] = []
            entry_id = await publish_event(
                redis,
                run_id,
                "run.cancelled",
                {"error": "运行已取消", "output": meta.get("output") or ""},
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )
            if entry_id:
                meta["last_event_id"] = entry_id
            await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        return meta

    payload = dict(meta.get("payload") or {})
    meta["status"] = "running"
    meta["pending_controls"] = []
    meta["heartbeat_at"] = time.time()
    meta["worker_id"] = WORKER_ID
    await _mark_active_run(redis, run_id, True)
    entry_id = await publish_event(
        redis,
        run_id,
        "run.resumed",
        {"run_id": run_id, "status": "running"},
        ttl_seconds=s.event_stream_ttl_seconds,
        max_len=s.stream_max_len,
    )
    if entry_id:
        meta["last_event_id"] = entry_id
    await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)

    try:
        config = await _build_runtime_config(
            payload,
            run_id=run_id,
            redis=redis,
            pool=pool,
            store=store,
            settings=s,
            initial_citations=list(meta.get("citations") or []),
        )
        graph = compiled_graph if compiled_graph is not None else build_agent_graph(checkpointer=checkpointer, store=store)
        await _stream_graph(
            graph=graph,
            graph_input=Command(resume=resume_payload),
            config=config,
            run_id=run_id,
            meta=meta,
            redis=redis,
            settings=s,
        )
        if async_memory_extract:
            await _maybe_dispatch_async_memory_extract(meta=meta, payload=payload, arq_pool=arq_pool)
    except asyncio.CancelledError:
        meta["status"] = "cancelled"
        meta["error"] = "工作进程重启或任务已取消"
        meta["pending_controls"] = []
        entry_id = await publish_event(
            redis,
            run_id,
            "run.cancelled",
            {"error": meta["error"], "output": meta.get("output") or ""},
            ttl_seconds=s.event_stream_ttl_seconds,
            max_len=s.stream_max_len,
        )
        if entry_id:
            meta["last_event_id"] = entry_id
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        raise
    except Exception as exc:
        logger.exception("Resume run %s failed", run_id)
        meta["status"] = "failed"
        meta["error"] = str(exc)
        meta["pending_controls"] = []
        entry_id = await publish_event(
            redis,
            run_id,
            "run.failed",
            {"error": str(exc), "output": meta.get("output") or ""},
            ttl_seconds=s.event_stream_ttl_seconds,
            max_len=s.stream_max_len,
        )
        if entry_id:
            meta["last_event_id"] = entry_id
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
    finally:
        await _mark_active_run(redis, run_id, False)

    return meta

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.core.config import AgentSettings, get_settings
from app.core.models import EmbeddingClient, ModelRouter
from app.graph.builder import build_agent_graph
from app.graph.topology import GRAPH_NODES
from app.memory.store import MemoryManager
from app.rag.hybrid_retriever import HybridRetriever
from app.tools.mcp_client import load_whitz_mcp_tools
from app.tools.sandbox import get_sandbox_executor

logger = logging.getLogger("whitz.agent.runner")

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})
TERMINAL_EVENT_NAMES = frozenset({"run.completed", "run.failed", "run.cancelled", "run.interrupted"})
NODE_LABELS = {n["id"]: n["label"] for n in GRAPH_NODES}


def meta_key(run_id: str) -> str:
    return f"run:{run_id}:meta"


def events_key(run_id: str) -> str:
    return f"run:{run_id}:events"


def cancel_key(run_id: str) -> str:
    return f"run:{run_id}:cancel"


async def publish_event(
    redis: Any,
    run_id: str,
    event_name: str,
    payload: dict[str, Any],
    *,
    ttl_seconds: int = 3600,
) -> str | None:
    if redis is None:
        return None
    data_json = json.dumps(payload, ensure_ascii=False, default=str)
    entry_id = await redis.xadd(
        events_key(run_id),
        {"event": event_name, "data": data_json},
        maxlen=5000,
        approximate=True,
    )
    await redis.expire(events_key(run_id), ttl_seconds)
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


async def is_cancelled(redis: Any, run_id: str) -> bool:
    if redis is None:
        return False
    try:
        return bool(await redis.get(cancel_key(run_id)))
    except Exception:
        return False


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
    if status == "error":
        return str(content or "tool error")
    if isinstance(content, str):
        try:
            obj = json.loads(content)
            if isinstance(obj, dict) and obj.get("error"):
                return str(obj["error"])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _build_initial_messages(payload: dict[str, Any]) -> list[Any]:
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
    if input_text:
        msgs.append(HumanMessage(content=input_text))
    return msgs


async def _build_runtime_config(
    payload: dict[str, Any],
    *,
    run_id: str,
    redis: Any,
    pool: Any,
    store: Any,
    settings: AgentSettings,
) -> dict[str, Any]:
    agent_namespace = str(payload.get("agent_namespace") or "")
    agent_api_key = str(payload.get("agent_api_key") or "")
    mcp_tools = []
    if agent_namespace and agent_api_key and settings.internal_mcp_base_url.strip():
        mcp_tools = await load_whitz_mcp_tools(
            internal_mcp_base_url=settings.internal_mcp_base_url,
            agent_namespace=agent_namespace,
            agent_api_key=agent_api_key,
        )

    emb_client = EmbeddingClient(settings=settings)
    model_router = ModelRouter(settings=settings, redis_client=redis)
    hybrid_retriever = HybridRetriever(pool=pool, embedding_client=emb_client)
    memory_manager = MemoryManager(store=store, pool=pool, embedding_client=emb_client)
    sandbox_executor = get_sandbox_executor(settings=settings)

    skills_list = payload.get("skills") or []
    skills_catalog = {
        str(sk.get("name")): sk
        for sk in skills_list
        if isinstance(sk, dict) and sk.get("name")
    }

    thread_id = str(payload.get("thread_id") or payload.get("conversation_id") or run_id)
    return {
        "configurable": {
            "thread_id": thread_id,
            "run_id": run_id,
            "user_id": str(payload.get("user_id") or ""),
            "conversation_id": str(payload.get("conversation_id") or thread_id),
            "agent_namespace": agent_namespace,
            "memory_enabled": bool(payload.get("memory_enabled")),
            "memory_require_confirm": bool(payload.get("memory_require_confirm", True)),
            "requested_route": str(payload.get("model_route") or "auto"),
            "skills_catalog": skills_catalog,
            "mcp_tools": mcp_tools,
            "model_router": model_router,
            "embedding_client": emb_client,
            "hybrid_retriever": hybrid_retriever,
            "memory_manager": memory_manager,
            "sandbox_executor": sandbox_executor,
            "pool": pool,
            "store": store,
        }
    }


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
    event_ttl = settings.event_stream_ttl_seconds
    meta_ttl = settings.run_state_ttl_seconds

    node_started_at: dict[str, float] = {}
    started_tools: dict[str, tuple[str, Any, float]] = {}
    buffered_text: list[str] = []
    reasoning_buf: list[str] = []
    last_ai_text = ""
    latest_plan: dict[str, Any] | None = meta.get("plan")
    latest_usage: dict[str, int] = dict(meta.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    selected_route = str(meta.get("route") or payload_route(meta))
    selected_model = str(meta.get("model") or "")

    async with asyncio.timeout(max(5, int(settings.run_max_seconds))):
        async for raw_item in graph.astream(
            graph_input,
            config=config,
            stream_mode=["messages", "updates", "custom"],
            subgraphs=True,
        ):
            if await is_cancelled(redis, run_id):
                partial = last_ai_text or "".join(buffered_text)
                meta["status"] = "cancelled"
                meta["output"] = partial
                meta["plan"] = latest_plan
                meta["usage"] = latest_usage
                await save_run_meta(redis, run_id, meta, ttl_seconds=meta_ttl)
                await publish_event(
                    redis,
                    run_id,
                    "run.cancelled",
                    {
                        "error": "运行已取消",
                        "output": partial,
                        "plan": latest_plan,
                        "reasoning": [{"text": "".join(reasoning_buf)}] if reasoning_buf else None,
                    },
                    ttl_seconds=event_ttl,
                )
                return

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
                        await publish_event(
                            redis,
                            run_id,
                            "graph.node",
                            {
                                "node": node_name,
                                "status": str(chunk.get("status") or "running"),
                                "label": chunk.get("label") or NODE_LABELS.get(node_name, node_name),
                                "route": selected_route or None,
                                "model": selected_model or None,
                                "duration_ms": None,
                            },
                            ttl_seconds=event_ttl,
                        )
                elif ev_type == "plan.updated":
                    latest_plan = {"items": list(chunk.get("items") or [])}
                    meta["plan"] = latest_plan
                    await save_run_meta(redis, run_id, meta, ttl_seconds=meta_ttl)
                    await publish_event(redis, run_id, "plan.updated", latest_plan, ttl_seconds=event_ttl)
                elif ev_type:
                    payload = {k: v for k, v in chunk.items() if k != "type"}
                    await publish_event(redis, run_id, ev_type, payload, ttl_seconds=event_ttl)

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
                    reasoning_buf.append(r_txt)
                    await publish_event(
                        redis,
                        run_id,
                        "reasoning.delta",
                        {"text": r_txt, "delta": r_txt, "step": None, "title": ""},
                        ttl_seconds=event_ttl,
                    )
                if txt:
                    buffered_text.append(txt)
                    await publish_event(
                        redis,
                        run_id,
                        "message.delta",
                        {"text": txt, "delta": txt},
                        ttl_seconds=event_ttl,
                    )

            elif mode == "updates" and isinstance(chunk, dict):
                if not is_root:
                    continue

                if "__interrupt__" in chunk:
                    interrupts = chunk.get("__interrupt__") or ()
                    intr = interrupts[0] if interrupts else None
                    val = getattr(intr, "value", intr)
                    if not isinstance(val, dict):
                        val = {"kind": "clarify", "preview": str(val)}
                    kind = str(val.get("kind") or "clarify").lower()
                    tool_name = str(val.get("tool") or ("execute_code" if kind == "approval" else "clarify"))
                    req_id = str(val.get("call_id") or val.get("request_id") or uuid.uuid4().hex)
                    gen = int(meta.get("execution_generation") or 0) + 1
                    meta["execution_generation"] = gen
                    meta["status"] = "waiting_for_approval" if kind == "approval" else "waiting_for_clarify"
                    control = {
                        "request_id": req_id,
                        "prompt_id": req_id,
                        "execution_generation": gen,
                        "kind": kind,
                        "tool": tool_name,
                        "preview": val.get("preview"),
                        "detail": val,
                    }
                    meta["pending_controls"] = [control]
                    meta["plan"] = latest_plan
                    meta["usage"] = latest_usage
                    await save_run_meta(redis, run_id, meta, ttl_seconds=meta_ttl)

                    await publish_event(
                        redis,
                        run_id,
                        "graph.node",
                        {
                            "node": "hitl_gate",
                            "status": "interrupted",
                            "label": NODE_LABELS.get("hitl_gate", "hitl_gate"),
                            "route": selected_route or None,
                            "model": selected_model or None,
                            "duration_ms": None,
                        },
                        ttl_seconds=event_ttl,
                    )
                    ev_name = "approval.request" if kind == "approval" else "clarify.request"
                    await publish_event(redis, run_id, ev_name, control, ttl_seconds=event_ttl)
                    return

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

                    await publish_event(
                        redis,
                        run_id,
                        "graph.node",
                        {
                            "node": node_name,
                            "status": "completed",
                            "label": NODE_LABELS.get(node_name, node_name),
                            "route": selected_route or None,
                            "model": selected_model or None,
                            "duration_ms": dur_ms,
                        },
                        ttl_seconds=event_ttl,
                    )

                    for msg in update.get("messages") or []:
                        if isinstance(msg, AIMessage):
                            if getattr(msg, "tool_calls", None):
                                # If text was buffered before tool call, clear delta accumulator for final reply
                                interim = "".join(buffered_text).strip()
                                if interim:
                                    buffered_text.clear()
                                    await publish_event(
                                        redis,
                                        run_id,
                                        "commentary",
                                        {"text": interim, "step": None, "title": "", "already_streamed": True},
                                        ttl_seconds=event_ttl,
                                    )
                                for tc in msg.tool_calls:
                                    cid = str(tc.get("id") or uuid.uuid4().hex)
                                    tname = str(tc.get("name") or "tool")
                                    targs = tc.get("args")
                                    if cid not in started_tools:
                                        started_tools[cid] = (tname, targs, time.monotonic())
                                        await publish_event(
                                            redis,
                                            run_id,
                                            "tool.started",
                                            {
                                                "tool": tname,
                                                "preview": targs,
                                                "args": targs,
                                                "call_id": cid,
                                            },
                                            ttl_seconds=event_ttl,
                                        )
                            elif isinstance(msg.content, str) and msg.content.strip():
                                last_ai_text = msg.content

                        elif isinstance(msg, ToolMessage):
                            cid = str(getattr(msg, "tool_call_id", "") or "")
                            tname = str(getattr(msg, "name", "") or "tool")
                            targs = None
                            dur_tool_ms = None
                            if cid in started_tools:
                                orig_name, targs, t0 = started_tools.pop(cid)
                                tname = tname or orig_name
                                dur_tool_ms = round((time.monotonic() - t0) * 1000.0, 1)
                            err = _parse_tool_error(msg.content, getattr(msg, "status", None))
                            await publish_event(
                                redis,
                                run_id,
                                "tool.completed",
                                {
                                    "tool": tname,
                                    "preview": _clip_str(msg.content, 8000),
                                    "args": targs,
                                    "result": _clip_str(msg.content, 24000),
                                    "error": err,
                                    "duration": dur_tool_ms,
                                    "duration_ms": dur_tool_ms,
                                    "call_id": cid or None,
                                },
                                ttl_seconds=event_ttl,
                            )

    final_output = last_ai_text or "".join(buffered_text)
    reasoning_blocks = [{"step": None, "title": "", "text": "".join(reasoning_buf)}] if reasoning_buf else None
    meta["status"] = "completed"
    meta["output"] = final_output
    meta["usage"] = latest_usage
    meta["plan"] = latest_plan
    meta["reasoning"] = reasoning_blocks
    meta["pending_controls"] = []
    meta["route"] = selected_route
    meta["model"] = selected_model
    await save_run_meta(redis, run_id, meta, ttl_seconds=meta_ttl)
    await publish_event(
        redis,
        run_id,
        "run.completed",
        {
            "output": final_output,
            "usage": latest_usage,
            "plan": latest_plan,
            "reasoning": reasoning_blocks,
        },
        ttl_seconds=event_ttl,
    )


def payload_route(meta: dict[str, Any]) -> str:
    payload = meta.get("payload") or {}
    return str(payload.get("model_route") or "auto")


async def execute_run(
    run_id: str,
    payload: dict[str, Any],
    *,
    redis: Any,
    pool: Any = None,
    checkpointer: Any = None,
    store: Any = None,
    settings: AgentSettings | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    s.configure_langsmith()

    meta = await load_run_meta(redis, run_id) or {
        "run_id": run_id,
        "thread_id": str(payload.get("thread_id") or payload.get("conversation_id") or run_id),
        "conversation_id": str(payload.get("conversation_id") or ""),
        "user_id": str(payload.get("user_id") or ""),
        "payload": payload,
        "execution_generation": 0,
    }
    meta["payload"] = payload

    if await is_cancelled(redis, run_id):
        meta["status"] = "cancelled"
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        await publish_event(
            redis,
            run_id,
            "run.cancelled",
            {"error": "运行已取消", "output": ""},
            ttl_seconds=s.event_stream_ttl_seconds,
        )
        return meta

    meta["status"] = "running"
    await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
    await publish_event(
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
    )

    try:
        config = await _build_runtime_config(
            payload,
            run_id=run_id,
            redis=redis,
            pool=pool,
            store=store,
            settings=s,
        )
        graph = build_agent_graph(checkpointer=checkpointer, store=store)
        graph_input = {
            "messages": _build_initial_messages(payload),
            "run_id": run_id,
            "thread_id": meta["thread_id"],
            "conversation_id": meta["conversation_id"],
            "user_id": meta["user_id"],
            "agent_namespace": str(payload.get("agent_namespace") or ""),
            "persona": str(payload.get("persona") or ""),
            "profile_context": str(payload.get("profile_context") or ""),
            "instructions": str(payload.get("instructions") or ""),
            "attachments": list(payload.get("attachments") or []),
            "skills": list(payload.get("skills") or []),
            "requested_skills": list(payload.get("requested_skills") or payload.get("skill_names") or []),
            "memory_enabled": bool(payload.get("memory_enabled")),
            "memory_require_confirm": bool(payload.get("memory_require_confirm", True)),
            "requested_route": str(payload.get("model_route") or "auto"),
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
    except TimeoutError:
        meta["status"] = "failed"
        meta["error"] = "运行超时"
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        await publish_event(
            redis,
            run_id,
            "run.failed",
            {"error": "运行超过时长上限，已终止", "output": meta.get("output") or ""},
            ttl_seconds=s.event_stream_ttl_seconds,
        )
    except Exception as exc:
        logger.exception("Run %s failed", run_id)
        meta["status"] = "failed"
        meta["error"] = str(exc)
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        await publish_event(
            redis,
            run_id,
            "run.failed",
            {"error": str(exc), "output": meta.get("output") or ""},
            ttl_seconds=s.event_stream_ttl_seconds,
        )

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
) -> dict[str, Any]:
    s = settings or get_settings()
    s.configure_langsmith()

    meta = await load_run_meta(redis, run_id)
    if meta is None:
        raise ValueError(f"Unknown run_id: {run_id}")

    payload = meta.get("payload") or {}
    meta["status"] = "running"
    meta["pending_controls"] = []
    await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)

    try:
        config = await _build_runtime_config(
            payload,
            run_id=run_id,
            redis=redis,
            pool=pool,
            store=store,
            settings=s,
        )
        graph = build_agent_graph(checkpointer=checkpointer, store=store)
        await _stream_graph(
            graph=graph,
            graph_input=Command(resume=resume_payload),
            config=config,
            run_id=run_id,
            meta=meta,
            redis=redis,
            settings=s,
        )
    except TimeoutError:
        meta["status"] = "failed"
        meta["error"] = "恢复运行超时"
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        await publish_event(
            redis,
            run_id,
            "run.failed",
            {"error": "运行超过时长上限，已终止", "output": meta.get("output") or ""},
            ttl_seconds=s.event_stream_ttl_seconds,
        )
    except Exception as exc:
        logger.exception("Resume run %s failed", run_id)
        meta["status"] = "failed"
        meta["error"] = str(exc)
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        await publish_event(
            redis,
            run_id,
            "run.failed",
            {"error": str(exc), "output": meta.get("output") or ""},
            ttl_seconds=s.event_stream_ttl_seconds,
        )

    return meta

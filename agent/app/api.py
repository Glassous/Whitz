from __future__ import annotations

import hmac
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import ResponseError as RedisResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sse_starlette.sse import EventSourceResponse

from app.core.config import AgentSettings, get_settings
from app.core.metrics import (
    AGENT_ARQ_QUEUE_DEPTH,
    AGENT_RUNS_ENQUEUED_TOTAL,
    metrics_middleware,
    render_prometheus_metrics,
)
from app.core.models import aclose_shared_http_clients
from app.graph.topology import get_graph_topology
from app.runner import (
    TERMINAL_EVENT_NAMES,
    TERMINAL_RUN_STATUSES,
    WORKER_HEARTBEAT_KEY,
    build_snapshot_payload,
    cancel_channel,
    cancel_key,
    events_key,
    load_run_meta,
    publish_event,
    save_run_meta,
    save_run_secret,
)

logger = logging.getLogger("whitz.agent.api")

_STREAM_ID_RE = re.compile(r"^(\d+-\d+|0-0|0|\$)$")


def _sanitize_cursor(raw: str | None) -> tuple[str, bool]:
    """Return ``(valid_cursor, was_valid)`` so invalid Last-Event-ID headers never crash XREAD."""
    cleaned = (raw or "").strip()
    if not cleaned:
        return "0-0", True
    if _STREAM_ID_RE.match(cleaned):
        return ("0-0" if cleaned == "0" else cleaned), True
    return "0-0", False


class CreateRunRequest(BaseModel):
    run_id: str | None = None
    thread_id: str | None = None
    conversation_id: str
    conversation_kind: str = "side"
    assistant_name: str = "Whitz"
    rolling_summary: str = ""
    cross_chat_context: str = ""
    memory_index: str = ""
    pinned_memories: str = ""
    user_id: str
    agent_namespace: str = ""
    agent_api_key: str = ""
    input: str = ""
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    persona: str = ""
    profile_context: str = ""
    timezone: str = "Asia/Shanghai"
    instructions: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    requested_skills: list[str] = Field(default_factory=list)
    skill_names: list[str] = Field(default_factory=list)
    memory_enabled: bool = True
    memory_require_confirm: bool = False
    ai_reactions_enabled: bool = True
    allow_hitl: bool = True
    max_tool_iterations: int | None = None
    model_route: str = "auto"
    rag_scope: dict[str, Any] | None = None
    idempotency_key: str | None = None


class ResumeRunRequest(BaseModel):
    request_id: str | None = None
    execution_generation: int | None = None
    kind: str | None = None
    choice: str | None = None
    answer: str | None = None
    answers: list[dict[str, Any]] | None = None
    approved: bool | None = None
    resume: Any = None


def verify_agent_token(
    request: Request,
    x_agent_token: str | None = Header(default=None),
) -> None:
    settings: AgentSettings = getattr(request.app.state, "settings", None) or get_settings()
    expected = settings.agent_internal_token.strip()
    if not expected:
        if (settings.app_env or "").strip().lower() == "production":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="agent_token_unconfigured")
        return
    if not x_agent_token or not hmac.compare_digest(x_agent_token.strip(), expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_agent_token")


def create_app(
    *,
    redis_client: Any = None,
    arq_pool: Any = None,
    pg_pool: Any = None,
    settings_override: AgentSettings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings_override or get_settings()
        s.configure_langsmith()
        app.state.settings = s

        owns_redis = redis_client is None
        owns_arq = arq_pool is None
        owns_pg = pg_pool is None

        app.state.redis = redis_client or Redis.from_url(
            s.redis_url,
            decode_responses=True,
            max_connections=s.redis_max_connections,
            socket_timeout=s.redis_socket_timeout,
        )
        # Dedicated pool for blocking XREAD SSE consumers
        app.state.stream_redis = (
            None
            if redis_client is not None
            else Redis.from_url(
                s.redis_url,
                decode_responses=True,
                max_connections=max(64, s.redis_max_connections),
                socket_timeout=30.0,
                health_check_interval=15,
            )
        )
        if arq_pool is not None:
            app.state.arq = arq_pool
        else:
            app.state.arq = await create_pool(RedisSettings.from_dsn(s.redis_url))

        if pg_pool is not None:
            app.state.pg_pool = pg_pool
        else:
            pool = AsyncConnectionPool(
                conninfo=s.psycopg_database_url,
                min_size=1,
                max_size=6,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            try:
                await pool.open()
                app.state.pg_pool = pool
            except Exception as exc:
                logger.warning("PG pool unavailable at startup: %s", exc)
                app.state.pg_pool = None
                owns_pg = False

        try:
            yield
        finally:
            await aclose_shared_http_clients()
            if owns_arq and app.state.arq is not None:
                await app.state.arq.aclose()
            if getattr(app.state, "stream_redis", None) is not None:
                await app.state.stream_redis.aclose()
            if owns_redis and app.state.redis is not None:
                await app.state.redis.aclose()
            if owns_pg and app.state.pg_pool is not None:
                await app.state.pg_pool.close()

    app = FastAPI(title="Whitz LangGraph Agent Service", version="0.2.0", lifespan=lifespan)
    app.middleware("http")(metrics_middleware)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        redis_inst = getattr(app.state, "redis", None)
        if redis_inst is not None:
            try:
                # ARQ stores its queue as a Redis ZSET ("arq:queue")
                depth = await redis_inst.zcard("arq:queue") if hasattr(redis_inst, "zcard") else 0
                AGENT_ARQ_QUEUE_DEPTH.set(int(depth or 0))
            except Exception:
                pass
        return render_prometheus_metrics()

    @app.get("/health")
    async def health():
        s: AgentSettings = getattr(app.state, "settings", get_settings())
        redis_ok = False
        pg_ok = False
        worker_ok = False
        if getattr(app.state, "redis", None) is not None:
            try:
                redis_ok = bool(await app.state.redis.ping())
                if redis_ok:
                    hb = await app.state.redis.get(WORKER_HEARTBEAT_KEY)
                    if hb:
                        worker_ok = (time.time() - float(hb)) < 45.0
            except Exception:
                redis_ok = False
        if getattr(app.state, "pg_pool", None) is not None:
            try:
                async with app.state.pg_pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT 1")
                        await cur.fetchone()
                pg_ok = True
            except Exception:
                pg_ok = False

        healthy = redis_ok and (pg_ok or getattr(app.state, "pg_pool", None) is None)
        body = {
            "ok": healthy,
            "status": "ok" if (redis_ok and pg_ok) else ("degraded" if redis_ok else "unhealthy"),
            "redis": redis_ok,
            "postgres": pg_ok,
            "worker": worker_ok,
            "sandbox_mode": s.sandbox_mode,
        }
        return JSONResponse(body, status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.get("/v1/graph/topology", dependencies=[Depends(verify_agent_token)])
    async def graph_topology() -> dict[str, Any]:
        return get_graph_topology()

    @app.post("/v1/runs", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_agent_token)])
    async def create_run(
        body: CreateRunRequest,
        idempotency_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        s: AgentSettings = app.state.settings
        redis = app.state.redis
        arq = app.state.arq

        run_id = body.run_id or uuid.uuid4().hex
        eff_idemp = (idempotency_key or body.idempotency_key or "").strip()

        # Atomic idempotency claim via SET NX
        if eff_idemp:
            idemp_key = f"agent:idemp:{eff_idemp}"
            claimed = await redis.set(idemp_key, run_id, ex=3600, nx=True)
            if not claimed:
                existing_id = await redis.get(idemp_key)
                if existing_id:
                    existing_meta = await load_run_meta(redis, existing_id)
                    if existing_meta is not None:
                        return {
                            "id": existing_id,
                            "run_id": existing_id,
                            "thread_id": existing_meta.get("thread_id"),
                            "status": existing_meta.get("status", "queued"),
                        }
                await redis.set(idemp_key, run_id, ex=3600)

        # Prevent accidental overwrite of an existing run_id
        if body.run_id:
            prior = await load_run_meta(redis, run_id)
            if prior is not None:
                return {
                    "id": run_id,
                    "run_id": run_id,
                    "thread_id": prior.get("thread_id"),
                    "status": prior.get("status", "queued"),
                }

        thread_id = body.thread_id or body.conversation_id
        payload = body.model_dump()
        payload["thread_id"] = thread_id

        raw_api_key = str(payload.get("agent_api_key") or "")
        if raw_api_key:
            await save_run_secret(redis, run_id, raw_api_key, ttl_seconds=s.run_state_ttl_seconds)
        sanitized_payload = dict(payload)
        sanitized_payload.pop("agent_api_key", None)

        meta = {
            "id": run_id,
            "run_id": run_id,
            "thread_id": thread_id,
            "conversation_id": body.conversation_id,
            "user_id": body.user_id,
            "status": "queued",
            "route": body.model_route,
            "model": "",
            "output": "",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "plan": None,
            "reasoning": [],
            "tool_events": [],
            "pending_controls": [],
            "last_event_id": "0-0",
            "execution_generation": 0,
            "heartbeat_at": time.time(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": sanitized_payload,
        }
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)

        await arq.enqueue_job("execute_run_job", run_id, sanitized_payload, _job_id=f"run:{run_id}")
        AGENT_RUNS_ENQUEUED_TOTAL.labels(route=(body.model_route or "auto").strip() or "auto").inc()
        return {
            "id": run_id,
            "run_id": run_id,
            "thread_id": thread_id,
            "status": "queued",
        }

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(verify_agent_token)])
    async def get_run(run_id: str) -> dict[str, Any]:
        meta = await load_run_meta(app.state.redis, run_id)
        if meta is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_not_found")
        return {
            "id": run_id,
            "run_id": run_id,
            "thread_id": meta.get("thread_id"),
            "conversation_id": meta.get("conversation_id"),
            "status": meta.get("status"),
            "route": meta.get("route"),
            "model": meta.get("model"),
            "output": meta.get("output") or "",
            "usage": meta.get("usage"),
            "plan": meta.get("plan"),
            "reasoning": meta.get("reasoning"),
            "tool_events": meta.get("tool_events") or [],
            "citations": meta.get("citations") or [],
            "rag_metrics": meta.get("rag_metrics"),
            "pending_controls": meta.get("pending_controls") or [],
            "last_event_id": meta.get("last_event_id") or "0-0",
            "heartbeat_at": meta.get("heartbeat_at"),
            "error": meta.get("error"),
        }

    @app.post("/v1/runs/{run_id}/resume", dependencies=[Depends(verify_agent_token)])
    async def resume_run_endpoint(run_id: str, body: ResumeRunRequest) -> dict[str, Any]:
        s: AgentSettings = app.state.settings
        redis = app.state.redis
        meta = await load_run_meta(redis, run_id)
        if meta is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_not_found")
        if meta.get("status") not in ("waiting_for_approval", "waiting_for_clarify", "interrupted"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="run_not_waiting")

        current_gen = int(meta.get("execution_generation") or 0)
        if body.execution_generation is not None and int(body.execution_generation) != current_gen:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale_execution_generation")

        # Atomic compare-and-swap lock per (run_id, generation) prevents duplicate resume jobs
        resume_lock_key = f"run:{run_id}:resume_lock:{current_gen}"
        claimed = await redis.set(resume_lock_key, "1", ex=120, nx=True)
        if not claimed:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="resume_already_submitted")

        if body.resume is not None:
            resume_payload = body.resume
        elif body.answer is not None or body.answers is not None:
            resume_payload = {"answer": body.answer or ""}
            if body.answers is not None:
                resume_payload["answers"] = body.answers
        else:
            resume_payload = {"choice": body.choice, "approved": body.approved}

        meta["status"] = "running"
        meta["pending_controls"] = []
        meta["heartbeat_at"] = time.time()
        entry_id = await publish_event(
            redis,
            run_id,
            "control.resolved",
            {
                "request_id": body.request_id,
                "execution_generation": current_gen,
                "kind": body.kind or ("clarify" if (body.answer is not None or body.answers is not None) else "approval"),
            },
            ttl_seconds=s.event_stream_ttl_seconds,
            max_len=s.stream_max_len,
        )
        if entry_id:
            meta["last_event_id"] = entry_id
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)

        await app.state.arq.enqueue_job(
            "resume_run_job",
            run_id,
            resume_payload,
            _job_id=f"resume:{run_id}:g{current_gen}",
        )
        return {"id": run_id, "run_id": run_id, "status": "running"}

    @app.post("/v1/runs/{run_id}/cancel", dependencies=[Depends(verify_agent_token)])
    async def cancel_run_endpoint(run_id: str) -> dict[str, Any]:
        s: AgentSettings = app.state.settings
        redis = app.state.redis
        meta = await load_run_meta(redis, run_id)
        if meta is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_not_found")

        await redis.set(cancel_key(run_id), "1", ex=s.run_state_ttl_seconds)
        # Instant wake-up for active worker cancel watcher
        if hasattr(redis, "publish"):
            try:
                await redis.publish(cancel_channel(run_id), "1")
            except Exception:
                pass

        cur_status = str(meta.get("status") or "")
        if cur_status in ("queued", "waiting_for_approval", "waiting_for_clarify", "interrupted"):
            meta["status"] = "cancelled"
            meta["pending_controls"] = []
            entry_id = await publish_event(
                redis,
                run_id,
                "run.cancelled",
                {"error": "运行已取消", "output": meta.get("output") or "", "plan": meta.get("plan")},
                ttl_seconds=s.event_stream_ttl_seconds,
                max_len=s.stream_max_len,
            )
            if entry_id:
                meta["last_event_id"] = entry_id
            await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
            return {"id": run_id, "run_id": run_id, "status": "cancelled"}

        return {"id": run_id, "run_id": run_id, "status": "cancelling"}

    @app.get("/v1/runs/{run_id}/events", dependencies=[Depends(verify_agent_token)])
    async def stream_run_events(
        run_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        last_event_id_qs: str | None = Query(default=None, alias="last_event_id"),
        include_snapshot: bool = Query(default=False),
    ) -> EventSourceResponse:
        redis = app.state.redis
        stream_redis = getattr(app.state, "stream_redis", None) or redis
        meta = await load_run_meta(redis, run_id)
        if meta is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_not_found")

        stream_key = events_key(run_id)
        raw_cursor = last_event_id or last_event_id_qs
        cursor, cursor_valid = _sanitize_cursor(raw_cursor)

        async def _drain_all_remaining(cur_id: str) -> tuple[list[tuple[str, str, str]], str, bool]:
            collected: list[tuple[str, str, str]] = []
            saw_term = False
            while True:
                batch = await redis.xread({stream_key: cur_id}, count=100)
                if not batch:
                    break
                batch_count = 0
                for _, items in batch:
                    for entry_id, fields in items:
                        batch_count += 1
                        cur_id = str(entry_id)
                        ev_name = str(fields.get("event") or "message")
                        raw_data = fields.get("data") or "{}"
                        collected.append((cur_id, ev_name, raw_data))
                        if ev_name in TERMINAL_EVENT_NAMES:
                            saw_term = True
                if batch_count < 100 or saw_term:
                    break
            return collected, cur_id, saw_term

        async def event_generator():
            nonlocal cursor
            cur_meta = meta

            # Emit atomic state snapshot for late-joining / reconnecting clients so they never
            # replay & duplicate earlier deltas or miss HITL controls after stream trim/expiry.
            need_snapshot = include_snapshot or not cursor_valid
            if need_snapshot and cur_meta is not None:
                snap = build_snapshot_payload(cur_meta)
                snap_cursor = str(snap.get("last_event_id") or "0-0")
                yield {
                    "event": "run.snapshot",
                    "id": snap_cursor,
                    "data": json.dumps(snap, ensure_ascii=False, default=str),
                }
                if snap_cursor and snap_cursor != "0-0":
                    cursor = snap_cursor
                if str(cur_meta.get("status") or "") in TERMINAL_RUN_STATUSES:
                    term_ev = f"run.{cur_meta['status']}"
                    yield {
                        "event": term_ev,
                        "id": snap_cursor,
                        "data": json.dumps(
                            {
                                "output": cur_meta.get("output") or "",
                                "usage": cur_meta.get("usage"),
                                "plan": cur_meta.get("plan"),
                                "reasoning": cur_meta.get("reasoning"),
                                "error": cur_meta.get("error"),
                            },
                            ensure_ascii=False,
                        ),
                    }
                    return

            while True:
                if await request.is_disconnected():
                    return
                try:
                    entries = await stream_redis.xread({stream_key: cursor}, count=100, block=2000)
                except (RedisTimeoutError, TimeoutError):
                    entries = None
                except RedisResponseError:
                    cursor = "0-0"
                    entries = None
                if entries:
                    for _, items in entries:
                        for entry_id, fields in items:
                            cursor = str(entry_id)
                            ev_name = str(fields.get("event") or "message")
                            raw_data = fields.get("data") or "{}"
                            yield {"event": ev_name, "id": cursor, "data": raw_data}
                            if ev_name in TERMINAL_EVENT_NAMES:
                                return
                else:
                    cur_meta = await load_run_meta(redis, run_id)
                    if cur_meta is None:
                        yield {
                            "event": "run.failed",
                            "data": json.dumps({"error": "run_expired"}, ensure_ascii=False),
                        }
                        return
                    cur_status = str(cur_meta.get("status") or "")
                    if cur_status in TERMINAL_RUN_STATUSES:
                        remaining, cursor, saw_terminal = await _drain_all_remaining(cursor)
                        for eid, ev_name, raw_data in remaining:
                            yield {"event": ev_name, "id": eid, "data": raw_data}
                        if not saw_terminal:
                            term_ev = f"run.{cur_status}"
                            yield {
                                "event": term_ev,
                                "id": cursor,
                                "data": json.dumps(
                                    {
                                        "output": cur_meta.get("output") or "",
                                        "usage": cur_meta.get("usage"),
                                        "plan": cur_meta.get("plan"),
                                        "reasoning": cur_meta.get("reasoning"),
                                        "error": cur_meta.get("error"),
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        return

        return EventSourceResponse(event_generator(), ping=10)

    @app.delete("/v1/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_agent_token)])
    async def delete_thread(thread_id: str) -> None:
        pool = getattr(app.state, "pg_pool", None)
        if pool is None:
            return
        try:
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.adelete_thread(thread_id)
            # Also clean up per-run scoped checkpoints ("{thread_id}:{run_id}")
            prefix = f"{thread_id}:%"
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for tbl in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                        try:
                            await cur.execute(f"DELETE FROM {tbl} WHERE thread_id LIKE %s", (prefix,))
                        except Exception:
                            pass
        except Exception as exc:
            logger.warning("Failed to delete checkpoints for thread=%s: %s", thread_id, exc)

    return app


app = create_app()

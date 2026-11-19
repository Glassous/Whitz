from __future__ import annotations

import hmac
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError
from sse_starlette.sse import EventSourceResponse

from app.core.config import AgentSettings, get_settings
from app.graph.topology import get_graph_topology
from app.runner import (
    TERMINAL_EVENT_NAMES,
    TERMINAL_RUN_STATUSES,
    cancel_key,
    events_key,
    load_run_meta,
    publish_event,
    save_run_meta,
)

logger = logging.getLogger("whitz.agent.api")


class CreateRunRequest(BaseModel):
    run_id: str | None = None
    thread_id: str | None = None
    conversation_id: str
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
    memory_enabled: bool = False
    memory_require_confirm: bool = True
    model_route: str = "auto"
    idempotency_key: str | None = None


class ResumeRunRequest(BaseModel):
    request_id: str | None = None
    execution_generation: int | None = None
    kind: str | None = None
    choice: str | None = None
    answer: str | None = None
    approved: bool | None = None
    resume: Any = None


def verify_agent_token(
    request: Request,
    x_agent_token: str | None = Header(default=None),
) -> None:
    settings: AgentSettings = getattr(request.app.state, "settings", None) or get_settings()
    expected = settings.agent_internal_token.strip()
    if not expected:
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
        # Blocking XREAD streams require a socket timeout longer than the block interval.
        app.state.stream_redis = (
            None
            if redis_client is not None
            else Redis.from_url(
                s.redis_url,
                decode_responses=True,
                max_connections=s.redis_max_connections,
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
                max_size=4,
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
            if owns_arq and app.state.arq is not None:
                await app.state.arq.aclose()
            if getattr(app.state, "stream_redis", None) is not None:
                await app.state.stream_redis.aclose()
            if owns_redis and app.state.redis is not None:
                await app.state.redis.aclose()
            if owns_pg and app.state.pg_pool is not None:
                await app.state.pg_pool.close()

    app = FastAPI(title="Whitz LangGraph Agent Service", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        s: AgentSettings = getattr(app.state, "settings", get_settings())
        redis_ok = False
        pg_ok = False
        if getattr(app.state, "redis", None) is not None:
            try:
                redis_ok = bool(await app.state.redis.ping())
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
        return {
            "ok": redis_ok,
            "status": "ok" if (redis_ok and pg_ok) else "degraded",
            "redis": redis_ok,
            "postgres": pg_ok,
            "sandbox_mode": s.sandbox_mode,
        }

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

        eff_idemp = (idempotency_key or body.idempotency_key or "").strip()
        if eff_idemp:
            existing_id = await redis.get(f"agent:idemp:{eff_idemp}")
            if existing_id:
                existing_meta = await load_run_meta(redis, existing_id)
                if existing_meta is not None:
                    return {
                        "id": existing_id,
                        "run_id": existing_id,
                        "thread_id": existing_meta.get("thread_id"),
                        "status": existing_meta.get("status", "queued"),
                    }

        run_id = body.run_id or uuid.uuid4().hex
        thread_id = body.thread_id or body.conversation_id
        payload = body.model_dump()
        payload["thread_id"] = thread_id

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
            "reasoning": None,
            "pending_controls": [],
            "execution_generation": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        if eff_idemp:
            await redis.set(f"agent:idemp:{eff_idemp}", run_id, ex=3600)

        await arq.enqueue_job("execute_run_job", run_id, payload, _job_id=f"run:{run_id}")
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
            "pending_controls": meta.get("pending_controls") or [],
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

        if body.execution_generation is not None:
            current_gen = int(meta.get("execution_generation") or 0)
            if int(body.execution_generation) != current_gen:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stale_execution_generation")

        if body.resume is not None:
            resume_payload = body.resume
        elif body.answer is not None:
            resume_payload = {"answer": body.answer}
        else:
            resume_payload = {"choice": body.choice, "approved": body.approved}

        meta["status"] = "running"
        await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
        await app.state.arq.enqueue_job(
            "resume_run_job",
            run_id,
            resume_payload,
            _job_id=f"resume:{run_id}:{uuid.uuid4().hex[:8]}",
        )
        return {"id": run_id, "run_id": run_id, "status": "running"}

    @app.post("/v1/runs/{run_id}/cancel", dependencies=[Depends(verify_agent_token)])
    async def cancel_run_endpoint(run_id: str) -> dict[str, Any]:
        s: AgentSettings = app.state.settings
        redis = app.state.redis
        meta = await load_run_meta(redis, run_id)
        if meta is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_not_found")

        await redis.set(cancel_key(run_id), "1", ex=3600)
        cur_status = str(meta.get("status") or "")
        if cur_status in ("queued", "waiting_for_approval", "waiting_for_clarify", "interrupted"):
            meta["status"] = "cancelled"
            meta["pending_controls"] = []
            await save_run_meta(redis, run_id, meta, ttl_seconds=s.run_state_ttl_seconds)
            await publish_event(
                redis,
                run_id,
                "run.cancelled",
                {"error": "运行已取消", "output": meta.get("output") or "", "plan": meta.get("plan")},
                ttl_seconds=s.event_stream_ttl_seconds,
            )
            return {"id": run_id, "run_id": run_id, "status": "cancelled"}

        return {"id": run_id, "run_id": run_id, "status": "cancelling"}

    @app.get("/v1/runs/{run_id}/events", dependencies=[Depends(verify_agent_token)])
    async def stream_run_events(
        run_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        last_event_id_qs: str | None = Query(default=None, alias="last_event_id"),
    ) -> EventSourceResponse:
        redis = app.state.redis
        stream_redis = getattr(app.state, "stream_redis", None) or redis
        meta = await load_run_meta(redis, run_id)
        if meta is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_not_found")

        stream_key = events_key(run_id)
        cursor = (last_event_id or last_event_id_qs or "").strip() or "0-0"

        async def event_generator():
            nonlocal cursor
            while True:
                if await request.is_disconnected():
                    return
                try:
                    entries = await stream_redis.xread({stream_key: cursor}, count=50, block=2500)
                except (RedisTimeoutError, TimeoutError):
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
                        # Drain once more in case terminal event landed right before status read
                        tail = await redis.xread({stream_key: cursor}, count=50)
                        saw_terminal = False
                        if tail:
                            for _, items in tail:
                                for entry_id, fields in items:
                                    cursor = str(entry_id)
                                    ev_name = str(fields.get("event") or "message")
                                    yield {"event": ev_name, "id": cursor, "data": fields.get("data") or "{}"}
                                    if ev_name in TERMINAL_EVENT_NAMES:
                                        saw_terminal = True
                        if not saw_terminal:
                            term_ev = f"run.{cur_status}"
                            yield {
                                "event": term_ev,
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
        except Exception as exc:
            logger.warning("Failed to delete checkpoints for thread=%s: %s", thread_id, exc)

    return app


app = create_app()

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.models import EmbeddingClient, ModelRouter, RerankClient, aclose_shared_http_clients
from app.graph.builder import build_agent_graph, extract_turn_memory_standalone
from app.memory.store import MemoryManager
from app.runner import (
    ACTIVE_RUNS_SET,
    TERMINAL_RUN_STATUSES,
    WORKER_HEARTBEAT_KEY,
    execute_run,
    load_run_meta,
    publish_event,
    resume_run,
    save_run_meta,
)

logger = logging.getLogger("whitz.agent.worker")

_ORPHAN_STALE_SECONDS = 55.0


async def _heartbeat_and_reaper_loop(ctx: dict[str, Any]) -> None:
    """Publishes worker liveness heartbeat (for Docker healthcheck) and reaps orphaned crashed runs."""
    redis = ctx["redis"]
    settings = ctx["settings"]
    tick = 0
    while True:
        try:
            await redis.set(WORKER_HEARTBEAT_KEY, str(time.time()), ex=60)
            tick += 1
            if tick % 3 == 0 and hasattr(redis, "smembers"):
                active_ids = await redis.smembers(ACTIVE_RUNS_SET)
                now = time.time()
                for rid in active_ids or ():
                    run_id = str(rid)
                    meta = await load_run_meta(redis, run_id)
                    if meta is None:
                        await redis.srem(ACTIVE_RUNS_SET, run_id)
                        continue
                    cur_status = str(meta.get("status") or "")
                    if cur_status in TERMINAL_RUN_STATUSES or cur_status.startswith("waiting_"):
                        await redis.srem(ACTIVE_RUNS_SET, run_id)
                        continue
                    hb = float(meta.get("heartbeat_at") or 0.0)
                    if hb > 0 and (now - hb) > _ORPHAN_STALE_SECONDS:
                        logger.warning("Reaping orphaned agent run %s (stale heartbeat %.1fs)", run_id, now - hb)
                        meta["status"] = "failed"
                        meta["error"] = "Agent 工作进程意外中断，任务已自动中止"
                        meta["pending_controls"] = []
                        entry_id = await publish_event(
                            redis,
                            run_id,
                            "run.failed",
                            {"error": meta["error"], "output": meta.get("output") or ""},
                            ttl_seconds=settings.event_stream_ttl_seconds,
                            max_len=settings.stream_max_len,
                        )
                        if entry_id:
                            meta["last_event_id"] = entry_id
                        await save_run_meta(redis, run_id, meta, ttl_seconds=settings.run_state_ttl_seconds)
                        await redis.srem(ACTIVE_RUNS_SET, run_id)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug("Worker heartbeat/reaper tick skipped: %s", exc)
        await asyncio.sleep(10.0)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    settings.configure_langsmith()

    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        socket_timeout=settings.redis_socket_timeout,
    )
    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    pool = AsyncConnectionPool(
        conninfo=settings.psycopg_database_url,
        min_size=1,
        max_size=12,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    # Precompile LangGraph ONCE per worker instead of rebuilding 3 StateGraphs on every turn!
    compiled_graph = build_agent_graph(checkpointer=checkpointer, store=None)

    ctx["settings"] = settings
    ctx["redis"] = redis
    ctx["arq"] = arq_pool
    ctx["pool"] = pool
    ctx["checkpointer"] = checkpointer
    ctx["graph"] = compiled_graph
    ctx["store"] = None
    ctx["active_tasks"] = set()
    ctx["reaper_task"] = asyncio.create_task(_heartbeat_and_reaper_loop(ctx))
    await redis.set(WORKER_HEARTBEAT_KEY, str(time.time()), ex=60)
    logger.info("Whitz agent arq worker initialized (precompiled graph + async memory extractor + orphan reaper)")


async def shutdown(ctx: dict[str, Any]) -> None:
    reaper = ctx.get("reaper_task")
    if reaper is not None:
        reaper.cancel()
        try:
            await reaper
        except (asyncio.CancelledError, Exception):
            pass

    active_tasks: set[asyncio.Task[Any]] = ctx.get("active_tasks") or set()
    if active_tasks:
        logger.info("Gracefully draining %d active agent tasks...", len(active_tasks))
        for t in list(active_tasks):
            t.cancel()
        await asyncio.gather(*list(active_tasks), return_exceptions=True)

    await aclose_shared_http_clients()
    arq_pool = ctx.get("arq")
    if arq_pool is not None:
        await arq_pool.aclose()
    redis = ctx.get("redis")
    if redis is not None:
        await redis.aclose()
    pool = ctx.get("pool")
    if pool is not None:
        await pool.close()
    logger.info("Whitz agent arq worker shut down cleanly")


async def execute_run_job(ctx: dict[str, Any], run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = asyncio.current_task()
    active_tasks: set[asyncio.Task[Any]] = ctx.setdefault("active_tasks", set())
    if task is not None:
        active_tasks.add(task)
    try:
        return await execute_run(
            run_id,
            payload,
            redis=ctx["redis"],
            pool=ctx.get("pool"),
            checkpointer=ctx.get("checkpointer"),
            store=ctx.get("store"),
            settings=ctx.get("settings"),
            compiled_graph=ctx.get("graph"),
            arq_pool=ctx.get("arq"),
            async_memory_extract=True,
        )
    finally:
        if task is not None:
            active_tasks.discard(task)


async def resume_run_job(ctx: dict[str, Any], run_id: str, resume_payload: Any) -> dict[str, Any]:
    task = asyncio.current_task()
    active_tasks: set[asyncio.Task[Any]] = ctx.setdefault("active_tasks", set())
    if task is not None:
        active_tasks.add(task)
    try:
        return await resume_run(
            run_id,
            resume_payload,
            redis=ctx["redis"],
            pool=ctx.get("pool"),
            checkpointer=ctx.get("checkpointer"),
            store=ctx.get("store"),
            settings=ctx.get("settings"),
            compiled_graph=ctx.get("graph"),
            arq_pool=ctx.get("arq"),
            async_memory_extract=True,
        )
    finally:
        if task is not None:
            active_tasks.discard(task)


async def extract_turn_memory_job(ctx: dict[str, Any], job_payload: dict[str, Any]) -> bool:
    """Off-critical-path post-turn memory extraction & consolidation job (eliminates 2-10s tail lag)."""
    settings = ctx.get("settings") or get_settings()
    redis = ctx.get("redis")
    pool = ctx.get("pool")
    emb_client = EmbeddingClient(settings=settings, redis_client=redis)
    rerank_client = RerankClient(settings=settings, redis_client=redis)
    router = ModelRouter(settings=settings, redis_client=redis)
    manager = MemoryManager(
        store=ctx.get("store"),
        pool=pool,
        embedding_client=emb_client,
        rerank_client=rerank_client,
    )
    return await extract_turn_memory_standalone(
        user_id=str(job_payload.get("user_id") or ""),
        agent_namespace=str(job_payload.get("agent_namespace") or ""),
        conversation_id=str(job_payload.get("conversation_id") or "") or None,
        user_text=str(job_payload.get("user_text") or ""),
        assistant_text=str(job_payload.get("assistant_text") or ""),
        memory_index=str(job_payload.get("memory_index") or ""),
        memory_require_confirm=bool(job_payload.get("memory_require_confirm", False)),
        manager=manager,
        router=router,
    )


class WorkerSettings:
    functions = [execute_run_job, resume_run_job, extract_turn_memory_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = get_settings().worker_max_jobs
    job_timeout = get_settings().run_max_seconds + 60

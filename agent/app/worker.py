from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from arq.connections import RedisSettings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.models import aclose_shared_http_clients
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

    # MemoryManager now uses PostgreSQL `memory_entries` as single source of truth (store=None).
    ctx["settings"] = settings
    ctx["redis"] = redis
    ctx["pool"] = pool
    ctx["checkpointer"] = checkpointer
    ctx["store"] = None
    ctx["active_tasks"] = set()
    ctx["reaper_task"] = asyncio.create_task(_heartbeat_and_reaper_loop(ctx))
    await redis.set(WORKER_HEARTBEAT_KEY, str(time.time()), ex=60)
    logger.info("Whitz agent arq worker initialized (single-source PG memory + orphan reaper enabled)")


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
        )
    finally:
        if task is not None:
            active_tasks.discard(task)


class WorkerSettings:
    functions = [execute_run_job, resume_run_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = get_settings().worker_max_jobs
    job_timeout = get_settings().run_max_seconds + 60

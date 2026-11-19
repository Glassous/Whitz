from __future__ import annotations

import logging
from typing import Any

from arq.connections import RedisSettings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.models import EmbeddingClient
from app.memory.store import WhitzEmbeddings
from app.runner import execute_run, resume_run

logger = logging.getLogger("whitz.agent.worker")


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
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()

    emb = EmbeddingClient(settings=settings)
    try:
        store = AsyncPostgresStore(
            pool,
            index={
                "dims": settings.embedding_dimensions,
                "embed": WhitzEmbeddings(emb),
                "fields": ["content"],
                "distance_type": "cosine",
            },
        )
        await store.setup()
    except Exception as exc:
        logger.warning("AsyncPostgresStore pgvector index setup failed (%s); using plain KV store", exc)
        store = AsyncPostgresStore(pool)
        await store.setup()

    ctx["settings"] = settings
    ctx["redis"] = redis
    ctx["pool"] = pool
    ctx["checkpointer"] = checkpointer
    ctx["store"] = store
    logger.info("Whitz agent arq worker initialized")


async def shutdown(ctx: dict[str, Any]) -> None:
    redis = ctx.get("redis")
    if redis is not None:
        await redis.aclose()
    pool = ctx.get("pool")
    if pool is not None:
        await pool.close()
    logger.info("Whitz agent arq worker shut down")


async def execute_run_job(ctx: dict[str, Any], run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await execute_run(
        run_id,
        payload,
        redis=ctx["redis"],
        pool=ctx.get("pool"),
        checkpointer=ctx.get("checkpointer"),
        store=ctx.get("store"),
        settings=ctx.get("settings"),
    )


async def resume_run_job(ctx: dict[str, Any], run_id: str, resume_payload: Any) -> dict[str, Any]:
    return await resume_run(
        run_id,
        resume_payload,
        redis=ctx["redis"],
        pool=ctx.get("pool"),
        checkpointer=ctx.get("checkpointer"),
        store=ctx.get("store"),
        settings=ctx.get("settings"),
    )


class WorkerSettings:
    functions = [execute_run_job, resume_run_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = get_settings().worker_max_jobs
    job_timeout = get_settings().run_max_seconds + 60

import logging
import secrets
import time

from app.core.config import get_settings
from app.core.metrics import ACTIVE_SSE_STREAMS
from app.core.redis import get_redis

logger = logging.getLogger("whitz.limits")

RUN_SLOT_TTL = 1800
SSE_SLOT_TTL = 3600


async def _incr_counter(key: str, ttl: int) -> int:
    r = get_redis()
    value = await r.incr(key)
    await r.expire(key, ttl)
    return value


async def _decr_counter(key: str, ttl: int) -> None:
    r = get_redis()
    value = await r.decr(key)
    if value < 0:
        await r.set(key, 0, ex=ttl)


async def _acquire(kind: str, user_id, max_global: int, max_user: int, ttl: int) -> str | None:
    """Reserve a slot. Returns a release token, or None when at capacity/backend down."""
    member = secrets.token_hex(16)
    global_key = f"lim:{kind}:global"
    user_key = f"lim:{kind}:user:{user_id}"
    slot_key = f"lim:{kind}:slot:{member}"
    try:
        r = get_redis()
        global_count = await _incr_counter(global_key, ttl)
        if global_count > max_global:
            await _decr_counter(global_key, ttl)
            return None
        user_count = await _incr_counter(user_key, ttl)
        if user_count > max_user:
            await _decr_counter(user_key, ttl)
            await _decr_counter(global_key, ttl)
            return None
        await r.set(slot_key, "1", ex=ttl, nx=True)
        return member
    except Exception:
        logger.warning("%s slot backend unavailable", kind, exc_info=True)
        return None


async def _release(kind: str, user_id, member: str | None, ttl: int) -> None:
    if not member:
        return
    slot_key = f"lim:{kind}:slot:{member}"
    try:
        r = get_redis()
        if not await r.getdel(slot_key):
            return
        await _decr_counter(f"lim:{kind}:global", ttl)
        await _decr_counter(f"lim:{kind}:user:{user_id}", ttl)
    except Exception:
        logger.warning("%s slot release failed", kind, exc_info=True)


async def acquire_run(user_id, per_user: int | None = None) -> str | None:
    settings = get_settings()
    return await _acquire(
        "run",
        user_id,
        settings.max_concurrent_runs,
        per_user or settings.max_concurrent_runs_per_user,
        RUN_SLOT_TTL,
    )


async def release_run(user_id, member: str | None) -> None:
    await _release("run", user_id, member, RUN_SLOT_TTL)


async def acquire_sse(user_id) -> str | None:
    settings = get_settings()
    return await _acquire(
        "sse", user_id, settings.max_sse_streams, settings.max_sse_streams_per_user, SSE_SLOT_TTL
    )


async def release_sse(user_id, member: str | None) -> None:
    await _release("sse", user_id, member, SSE_SLOT_TTL)


async def allow_chat(user_id, per_minute: int | None = None) -> bool:
    settings = get_settings()
    limit = per_minute or settings.chat_rate_per_minute
    window = int(time.time() // 60)
    key = f"rate:chat:{user_id}:{window}"
    try:
        count = await _incr_counter(key, 70)
    except Exception:
        logger.warning("chat rate limiter backend unavailable", exc_info=True)
        return False
    return count <= limit


async def wrap_stream(inner, user_id, *, run_slot: str | None = None, sse_slot: str | None = None):
    ACTIVE_SSE_STREAMS.inc()
    try:
        async for event in inner:
            yield event
    finally:
        ACTIVE_SSE_STREAMS.dec()
        if run_slot:
            await release_run(user_id, run_slot)
        if sse_slot:
            await release_sse(user_id, sse_slot)

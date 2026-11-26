from __future__ import annotations

import logging
import secrets
import time

from app.core.config import get_settings
from app.core.metrics import ACTIVE_SSE_STREAMS
from app.core.redis import MemoryRedis, get_redis

logger = logging.getLogger("whitz.limits")

RUN_SLOT_TTL = 1800
SSE_SLOT_TTL = 3600

# Atomic lease-based slot acquisition via Redis Sorted Sets:
# Expired members (from crashed workers) are pruned on every acquire so slots NEVER leak permanently.
_ZSET_ACQUIRE_LUA = """
local gkey = KEYS[1]
local ukey = KEYS[2]
local now = tonumber(ARGV[1])
local exp = tonumber(ARGV[2])
local max_g = tonumber(ARGV[3])
local max_u = tonumber(ARGV[4])
local member = ARGV[5]
local ttl = tonumber(ARGV[6])

redis.call('ZREMRANGEBYSCORE', gkey, '-inf', now)
redis.call('ZREMRANGEBYSCORE', ukey, '-inf', now)

if redis.call('ZCARD', gkey) >= max_g then
  return 0
end
if redis.call('ZCARD', ukey) >= max_u then
  return 0
end

redis.call('ZADD', gkey, exp, member)
redis.call('ZADD', ukey, exp, member)
redis.call('EXPIRE', gkey, ttl)
redis.call('EXPIRE', ukey, ttl)
return 1
"""


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
    """Reserve a lease slot. Returns a release token, or None when at capacity/backend down."""
    member = secrets.token_hex(16)
    global_key = f"lim:{kind}:z:global"
    user_key = f"lim:{kind}:z:user:{user_id}"
    try:
        r = get_redis()
        if not isinstance(r, MemoryRedis) and hasattr(r, "eval"):
            now = time.time()
            exp = now + ttl
            ok = await r.eval(
                _ZSET_ACQUIRE_LUA,
                2,
                global_key,
                user_key,
                str(now),
                str(exp),
                str(max_global),
                str(max_user),
                member,
                str(ttl + 60),
            )
            return member if int(ok or 0) == 1 else None

        # MemoryRedis fallback for unit tests
        cnt_global_key = f"lim:{kind}:global"
        cnt_user_key = f"lim:{kind}:user:{user_id}"
        slot_key = f"lim:{kind}:slot:{member}"
        global_count = await _incr_counter(cnt_global_key, ttl)
        if global_count > max_global:
            await _decr_counter(cnt_global_key, ttl)
            return None
        user_count = await _incr_counter(cnt_user_key, ttl)
        if user_count > max_user:
            await _decr_counter(cnt_user_key, ttl)
            await _decr_counter(cnt_global_key, ttl)
            return None
        await r.set(slot_key, "1", ex=ttl, nx=True)
        return member
    except Exception:
        logger.warning("%s slot backend unavailable", kind, exc_info=True)
        return None


async def _release(kind: str, user_id, member: str | None, ttl: int) -> None:
    if not member:
        return
    try:
        r = get_redis()
        if not isinstance(r, MemoryRedis) and hasattr(r, "zrem"):
            await r.zrem(f"lim:{kind}:z:global", member)
            await r.zrem(f"lim:{kind}:z:user:{user_id}", member)
            return

        slot_key = f"lim:{kind}:slot:{member}"
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

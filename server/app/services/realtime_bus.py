from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.core.redis import MemoryRedis, get_redis

logger = logging.getLogger("whitz.realtime_bus")

# Local fallback queues used when Redis is MemoryRedis (unit tests) or pubsub is unavailable.
_LOCAL_SUBSCRIBERS: dict[str, set[asyncio.Queue[tuple[str, dict[str, Any]]]]] = {}


def user_channel(user_id: uuid.UUID | str) -> str:
    return f"user:{user_id}:sync"


async def publish_user_event(user_id: uuid.UUID | str, event: str, data: dict[str, Any]) -> None:
    """Broadcast a real-time sync event to all connected tabs/devices of ``user_id``."""
    uid = str(user_id)
    payload = {"event": event, "data": data}
    try:
        r = get_redis()
        if isinstance(r, MemoryRedis) or not hasattr(r, "publish"):
            for q in list(_LOCAL_SUBSCRIBERS.get(uid, ())):
                try:
                    q.put_nowait((event, data))
                except asyncio.QueueFull:
                    pass
            return
        await r.publish(user_channel(uid), json.dumps(payload, ensure_ascii=False, default=str))
    except Exception as exc:
        logger.debug("publish_user_event skipped for user=%s event=%s: %s", uid, event, exc)


async def subscribe_user_events(user_id: uuid.UUID | str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ``(event_name, data_dict)`` for a user from Redis Pub/Sub (or local queue in tests)."""
    uid = str(user_id)
    r = get_redis()

    if isinstance(r, MemoryRedis) or not hasattr(r, "pubsub"):
        q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=128)
        _LOCAL_SUBSCRIBERS.setdefault(uid, set()).add(q)
        try:
            while True:
                ev, data = await q.get()
                yield ev, data
        finally:
            subs = _LOCAL_SUBSCRIBERS.get(uid)
            if subs:
                subs.discard(q)
                if not subs:
                    _LOCAL_SUBSCRIBERS.pop(uid, None)
        return

    pubsub = r.pubsub()
    channel = user_channel(uid)
    await pubsub.subscribe(channel)
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if msg is None:
                await asyncio.sleep(0.05)
                continue
            raw = msg.get("data")
            if not isinstance(raw, str):
                continue
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("event"):
                    yield str(parsed["event"]), parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
            except (json.JSONDecodeError, ValueError):
                continue
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass

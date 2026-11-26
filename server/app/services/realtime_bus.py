from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.core.metrics import REALTIME_SUBSCRIBERS_ACTIVE
from app.core.redis import MemoryRedis, get_redis

logger = logging.getLogger("whitz.realtime_bus")

MAX_CONNECTIONS_PER_USER = 12


def user_channel(user_id: uuid.UUID | str) -> str:
    return f"user:{user_id}:sync"


class _RealtimeMultiplexer:
    """Process-wide single-connection Redis Pub/Sub fan-out multiplexer.

    Instead of opening 1 dedicated Redis connection per browser tab (which quickly
    exhausts the 64-connection Redis pool), this maintains ONE shared Pub/Sub
    listener per worker process and dispatches messages to in-memory per-user queues.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[tuple[str, dict[str, Any]]]]] = {}
        self._lock: asyncio.Lock | None = None
        self._pubsub: Any = None
        self._reader_task: asyncio.Task[Any] | None = None
        self._subscribed_channels: set[str] = set()

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _dispatch_local(self, uid: str, event: str, data: dict[str, Any]) -> None:
        queues = list(self._subscribers.get(uid, ()))
        for q in queues:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait((event, data))
            except asyncio.QueueFull:
                pass

    def _total_connections(self) -> int:
        return sum(len(qs) for qs in self._subscribers.values())

    async def _ensure_reader_started(self, r: Any) -> None:
        if self._reader_task is not None and not self._reader_task.done():
            return
        self._pubsub = r.pubsub()
        self._subscribed_channels.clear()
        self._reader_task = asyncio.create_task(self._reader_loop(), name="realtime-pubsub-mux")

    async def _reader_loop(self) -> None:
        backoff = 0.5
        while True:
            try:
                r = get_redis()
                if isinstance(r, MemoryRedis) or not hasattr(r, "pubsub"):
                    return
                if self._pubsub is None:
                    self._pubsub = r.pubsub()
                    self._subscribed_channels.clear()

                async with self._get_lock():
                    desired = {user_channel(uid) for uid, qs in self._subscribers.items() if qs}
                    to_sub = desired - self._subscribed_channels
                    to_unsub = self._subscribed_channels - desired
                    if to_sub:
                        await self._pubsub.subscribe(*sorted(to_sub))
                        self._subscribed_channels.update(to_sub)
                    if to_unsub:
                        await self._pubsub.unsubscribe(*sorted(to_unsub))
                        self._subscribed_channels.difference_update(to_unsub)

                if not self._subscribed_channels:
                    await asyncio.sleep(0.25)
                    continue

                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                backoff = 0.5
                if msg is None:
                    await asyncio.sleep(0.02)
                    continue
                channel = msg.get("channel")
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8", "ignore")
                raw = msg.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "ignore")
                if not isinstance(channel, str) or not isinstance(raw, str):
                    continue
                # Channel format: user:{uid}:sync
                parts = channel.split(":")
                if len(parts) != 3 or parts[0] != "user" or parts[2] != "sync":
                    continue
                uid = parts[1]
                try:
                    parsed = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(parsed, dict) and parsed.get("event"):
                    ev = str(parsed["event"])
                    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
                    self._dispatch_local(uid, ev, data)
            except asyncio.CancelledError:
                await self._close_pubsub()
                return
            except Exception as exc:
                logger.warning("realtime multiplexer error (reconnecting in %.1fs): %s", backoff, exc)
                await self._close_pubsub()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 10.0)

    async def _close_pubsub(self) -> None:
        ps = self._pubsub
        self._pubsub = None
        self._subscribed_channels.clear()
        if ps is not None:
            try:
                await ps.aclose()
            except Exception:
                pass

    async def publish(self, user_id: uuid.UUID | str, event: str, data: dict[str, Any]) -> None:
        uid = str(user_id)
        payload = {"event": event, "data": data}
        try:
            r = get_redis()
            if isinstance(r, MemoryRedis) or not hasattr(r, "publish"):
                self._dispatch_local(uid, event, data)
                return
            await r.publish(user_channel(uid), json.dumps(payload, ensure_ascii=False, default=str))
        except Exception as exc:
            logger.debug("publish_user_event skipped for user=%s event=%s: %s", uid, event, exc)

    async def subscribe(self, user_id: uuid.UUID | str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        uid = str(user_id)
        q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=128)
        r = get_redis()
        use_redis = not isinstance(r, MemoryRedis) and hasattr(r, "pubsub")

        async with self._get_lock():
            bucket = self._subscribers.setdefault(uid, set())
            # Evict oldest queue if single user opens too many tabs
            while len(bucket) >= MAX_CONNECTIONS_PER_USER:
                evicted = next(iter(bucket))
                bucket.discard(evicted)
                try:
                    evicted.put_nowait(("__close__", {}))
                except asyncio.QueueFull:
                    pass
            bucket.add(q)
            REALTIME_SUBSCRIBERS_ACTIVE.set(self._total_connections())
            if use_redis:
                await self._ensure_reader_started(r)
                ch = user_channel(uid)
                if self._pubsub is not None and ch not in self._subscribed_channels:
                    try:
                        await self._pubsub.subscribe(ch)
                        self._subscribed_channels.add(ch)
                    except Exception:
                        pass

        try:
            while True:
                ev, data = await q.get()
                if ev == "__close__":
                    return
                yield ev, data
        finally:
            async with self._get_lock():
                subs = self._subscribers.get(uid)
                if subs is not None:
                    subs.discard(q)
                    if not subs:
                        self._subscribers.pop(uid, None)
                        ch = user_channel(uid)
                        if self._pubsub is not None and ch in self._subscribed_channels:
                            try:
                                await self._pubsub.unsubscribe(ch)
                            except Exception:
                                pass
                            self._subscribed_channels.discard(ch)
                REALTIME_SUBSCRIBERS_ACTIVE.set(self._total_connections())

    async def aclose(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        await self._close_pubsub()
        self._subscribers.clear()
        REALTIME_SUBSCRIBERS_ACTIVE.set(0)


_MUX = _RealtimeMultiplexer()
# Backward-compatible reference for any tests inspecting local subscribers
_LOCAL_SUBSCRIBERS = _MUX._subscribers


async def publish_user_event(user_id: uuid.UUID | str, event: str, data: dict[str, Any]) -> None:
    """Broadcast a real-time sync event to all connected tabs/devices of ``user_id``."""
    await _MUX.publish(user_id, event, data)


async def subscribe_user_events(user_id: uuid.UUID | str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ``(event_name, data_dict)`` for a user from the multiplexed Redis Pub/Sub listener."""
    async for item in _MUX.subscribe(user_id):
        yield item


async def aclose_realtime_bus() -> None:
    """Shut down the shared realtime Pub/Sub multiplexer cleanly."""
    await _MUX.aclose()

"""Redis client with an in-memory fallback for local tests.

Production uses a real Redis instance. Tests can set ``REDIS_URL=memory://``
so the API works without an external service while keeping the same interface.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.config import get_settings

_redis: Any = None


class MemoryRedis:
    """Small async Redis subset used by tests and local fallback."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}

    def _purge(self, key: str) -> None:
        item = self._data.get(key)
        if item and item[1] is not None and item[1] <= time.monotonic():
            self._data.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Any:
        self._purge(key)
        item = self._data.get(key)
        return item[0] if item else None

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        self._purge(key)
        if nx and key in self._data:
            return None
        expires_at = time.monotonic() + ex if ex else None
        self._data[key] = (value, expires_at)
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += 1 if self._data.pop(key, None) is not None else 0
        return removed

    async def exists(self, key: str) -> int:
        self._purge(key)
        return 1 if key in self._data else 0

    async def expire(self, key: str, seconds: int) -> bool:
        self._purge(key)
        if key not in self._data:
            return False
        value, _ = self._data[key]
        self._data[key] = (value, time.monotonic() + seconds)
        return True

    async def incr(self, key: str, amount: int = 1) -> int:
        self._purge(key)
        item = self._data.get(key)
        current = int(item[0]) if item else 0
        value = current + amount
        expires_at = item[1] if item else None
        self._data[key] = (value, expires_at)
        return value

    async def decr(self, key: str, amount: int = 1) -> int:
        return await self.incr(key, -amount)

    async def getdel(self, key: str) -> Any:
        self._purge(key)
        item = self._data.pop(key, None)
        return item[0] if item else None

    async def aclose(self) -> None:
        self._data.clear()


def get_redis() -> Any:
    global _redis
    if _redis is not None:
        return _redis
    settings = get_settings()
    if settings.redis_url.startswith("memory://"):
        _redis = MemoryRedis()
        return _redis
    try:
        from redis import asyncio as redis_async
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError("Redis 未安装：请安装 redis>=5 或配置 REDIS_URL=memory://") from exc
    _redis = redis_async.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        socket_timeout=settings.redis_socket_timeout,
        socket_connect_timeout=settings.redis_socket_timeout,
    )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None

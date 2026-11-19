from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any


class FakeRedis:
    """Minimal async Redis fake supporting KV + Streams (XADD/XREAD) for unit tests."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._seq = 0

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.kv:
            return False
        self.kv[key] = str(value)
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self.kv:
                del self.kv[k]
                removed += 1
        return removed

    async def exists(self, key: str) -> int:
        return 1 if key in self.kv else 0

    async def incr(self, key: str) -> int:
        val = int(self.kv.get(key, "0")) + 1
        self.kv[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def xadd(self, key: str, fields: dict[str, str], **kwargs: Any) -> str:
        self._seq += 1
        entry_id = f"{self._seq}-0"
        self.streams.setdefault(key, []).append((entry_id, dict(fields)))
        return entry_id

    async def xread(self, streams: dict[str, str], count: int = 50, block: int | None = None):
        out = []
        for key, cursor in streams.items():
            entries = self.streams.get(key, [])
            if cursor in ("0", "0-0", ""):
                matched = entries[:count]
            else:
                cur_seq = int(cursor.split("-", 1)[0])
                matched = [e for e in entries if int(e[0].split("-", 1)[0]) > cur_seq][:count]
            if matched:
                out.append((key, matched))
        return out

    async def aclose(self) -> None:
        return None


class FakeArqPool:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any):
        self.jobs.append((name, args, kwargs))
        return kwargs.get("_job_id") or name

    async def aclose(self) -> None:
        return None


class FakeCursor:
    def __init__(self, pool: "FakePGPool") -> None:
        self.pool = pool
        self._rows: list[tuple[Any, ...]] = []

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.pool.queries.append((sql.strip(), params))
        if self.pool.responder is not None:
            self._rows = list(self.pool.responder(sql, params))
        else:
            self._rows = []

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self, pool: "FakePGPool") -> None:
        self.pool = pool
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.pool)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakePGPool:
    def __init__(self, responder=None) -> None:
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.responder = responder

    @asynccontextmanager
    async def connection(self):
        yield FakeConnection(self)

    async def close(self) -> None:
        return None

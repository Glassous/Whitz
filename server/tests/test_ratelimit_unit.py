import pytest

from app.core import ratelimit
from app.core.ratelimit import RateLimiter


class FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, seconds):
        self.expires[key] = seconds


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(ratelimit, "get_redis", lambda: r)
    return r


async def test_allows_up_to_limit_then_blocks(fake_redis):
    lim = RateLimiter(2, 60, prefix="t1")
    assert await lim.allow("k") is True
    assert await lim.allow("k") is True
    assert await lim.allow("k") is False


async def test_keys_are_independent(fake_redis):
    lim = RateLimiter(1, 60, prefix="t2")
    assert await lim.allow("a") is True
    assert await lim.allow("b") is True
    assert await lim.allow("a") is False


async def test_expire_set_once_with_grace(fake_redis):
    lim = RateLimiter(5, 30, prefix="t3")
    await lim.allow("k")
    await lim.allow("k")
    assert list(fake_redis.expires.values()) == [40]


async def test_fails_closed_when_backend_unavailable(monkeypatch):
    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(ratelimit, "get_redis", boom)
    assert await RateLimiter(10, 60, prefix="t4").allow("k") is False


def test_constructor_clamps_and_auto_prefix():
    lim = RateLimiter(0, 0)
    assert lim.max_attempts == 1 and lim.window == 1
    assert RateLimiter(1, 1).prefix != RateLimiter(1, 1).prefix

import hashlib
import logging
import time

from app.core.redis import get_redis

logger = logging.getLogger("whitz.ratelimit")


class RateLimiter:
    """Redis-backed fixed-window rate limiter (works with MemoryRedis in tests)."""

    _seq = 0

    def __init__(self, max_attempts: int, window_seconds: int, *, prefix: str | None = None) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window = max(1, int(window_seconds))
        if prefix:
            self.prefix = prefix
        else:
            RateLimiter._seq += 1
            self.prefix = f"lim{RateLimiter._seq}"

    async def allow(self, key: str) -> bool:
        bucket = int(time.time() // self.window)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        redis_key = f"rl:{self.prefix}:{bucket}:{digest}"
        try:
            r = get_redis()
            count = await r.incr(redis_key)
            if count == 1:
                await r.expire(redis_key, self.window + 10)
        except Exception:
            logger.warning("rate limiter backend unavailable prefix=%s", self.prefix, exc_info=True)
            return False
        return count <= self.max_attempts


email_code_ip_limiter = RateLimiter(max_attempts=30, window_seconds=3600, prefix="email_code_ip")
email_code_addr_limiter = RateLimiter(max_attempts=10, window_seconds=3600, prefix="email_code_addr")
reset_password_limiter = RateLimiter(max_attempts=20, window_seconds=3600, prefix="reset_password")
login_code_limiter = RateLimiter(max_attempts=20, window_seconds=3600, prefix="login_code")
redeem_limiter = RateLimiter(max_attempts=5, window_seconds=60, prefix="redeem")

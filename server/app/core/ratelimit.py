import time
from collections import defaultdict


class RateLimiter:
    """In-memory sliding-window limiter (single-instance deployment)."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = [t for t in self._hits[key] if now - t < self.window]
        if len(hits) >= self.max_attempts:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


security_questions_limiter = RateLimiter(max_attempts=10, window_seconds=3600)
reset_password_limiter = RateLimiter(max_attempts=20, window_seconds=3600)
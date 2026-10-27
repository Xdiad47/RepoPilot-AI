"""Abuse controls: per-client sliding window plus a global daily cap on investigations (protects LLM credits)."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import Settings
from app.core.errors import RateLimited

HOUR = 3600
DAY = 86400


class RateLimiter:
    def __init__(self, settings: Settings, clock=time.monotonic) -> None:
        self._s = settings
        self._clock = clock
        self._by_client: dict[str, deque[float]] = defaultdict(deque)
        self._global: deque[float] = deque()

    def client_key(self, request: Request) -> str:
        if self._s.trust_proxy_headers:
            forwarded = request.headers.get("x-real-ip")
            if forwarded and len(forwarded) <= 64:
                return forwarded.strip()
        return request.client.host if request.client else "unknown"

    def check(self, key: str) -> None:
        """Record one investigation request or raise RateLimited."""
        now = self._clock()
        window = self._by_client[key]
        while window and now - window[0] > HOUR:
            window.popleft()
        while self._global and now - self._global[0] > DAY:
            self._global.popleft()

        if len(self._global) >= self._s.daily_global_limit:
            raise RateLimited(
                "The daily capacity of this demo has been reached. Please try again tomorrow.",
                retry_after=int(DAY - (now - self._global[0])),
            )
        if len(window) >= self._s.rate_limit_per_hour:
            raise RateLimited(
                f"Rate limit reached: at most {self._s.rate_limit_per_hour} investigations per hour per visitor.",
                retry_after=max(1, int(HOUR - (now - window[0]))),
            )
        window.append(now)
        self._global.append(now)
        if len(self._by_client) > 5000:  # bound memory against many distinct clients
            for k in [k for k, v in self._by_client.items() if not v][:1000]:
                del self._by_client[k]

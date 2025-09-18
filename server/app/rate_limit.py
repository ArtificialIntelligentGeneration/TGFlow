import asyncio
import time
from typing import Optional, Dict
from collections import defaultdict
import threading

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status

from .core.config import get_settings


class InMemoryRateLimiter:
    """Simple in-memory rate limiter for stage environment when Redis is unavailable"""
    def __init__(self):
        self._counters: Dict[str, Dict[int, int]] = defaultdict(dict)
        self._lock = threading.Lock()
        self._cleanup_interval = 60  # seconds
        self._last_cleanup = time.time()

    def check(self, key: str, limit_rps: int) -> None:
        now = int(time.time())

        with self._lock:
            # Periodic cleanup of old entries
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_old_entries(now)
                self._last_cleanup = now

            # Get or create bucket for this key
            bucket = self._counters[key]
            count = bucket.get(now, 0) + 1
            bucket[now] = count

            if count > limit_rps:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too Many Requests")

    def _cleanup_old_entries(self, now: int) -> None:
        """Remove entries older than 2 minutes"""
        cutoff = now - 120
        for key in list(self._counters.keys()):
            self._counters[key] = {ts: count for ts, count in self._counters[key].items() if ts > cutoff}
            if not self._counters[key]:
                del self._counters[key]


class RateLimiter:
    def __init__(self, redis: Optional[aioredis.Redis]):
        self.redis = redis
        self.settings = get_settings()
        self.fallback_limiter = InMemoryRateLimiter()

    async def check(self, key: str, limit_rps: int) -> None:
        if self.redis is not None:
            # Use Redis if available
            now = int(time.time())
            bucket_key = f"rl:{key}:{now}"
            count = await self.redis.incr(bucket_key)
            if count == 1:
                await self.redis.expire(bucket_key, 1)
            if count > limit_rps:
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too Many Requests")
        else:
            # Fallback to in-memory limiter
            self.fallback_limiter.check(key, limit_rps)


async def rate_limit_token(request: Request):
    app = request.app
    limiter = RateLimiter(app.state.redis)
    auth = request.headers.get("authorization") or ""
    token_hash = str(hash(auth))
    await limiter.check(f"token:{token_hash}", limiter.settings.RATE_LIMIT_PER_TOKEN_RPS)


async def rate_limit_ip(request: Request):
    app = request.app
    limiter = RateLimiter(app.state.redis)
    client_ip = request.client.host if request.client else "unknown"
    await limiter.check(f"ip:{client_ip}", limiter.settings.RATE_LIMIT_PER_IP_RPS)




"""Redis-backed sliding window rate limiter."""

from __future__ import annotations

import math
import time
from uuid import uuid4

from redis.asyncio import Redis


SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)

local current = redis.call('ZCARD', key)
if current >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_after_ms = window_ms
  if oldest[2] then
    retry_after_ms = window_ms - (now_ms - tonumber(oldest[2]))
  end
  return {0, current, retry_after_ms}
end

redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
return {1, current + 1, 0}
"""


class RateLimitExceededError(Exception):
    """Raised when a principal exceeds the configured request budget."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many requests.")
        self.retry_after_seconds = retry_after_seconds


class RedisSlidingWindowRateLimiter:
    """A simple Redis sorted-set based sliding window limiter."""

    def __init__(self, redis: Redis, limit: int, window_seconds: int) -> None:
        self._redis = redis
        self._limit = limit
        self._window_seconds = window_seconds

    async def check(self, principal: str) -> None:
        """Raise when the principal is above the configured request budget."""

        now_ms = int(time.time() * 1000)
        window_ms = self._window_seconds * 1000
        key = f"rate:{principal}"
        member = f"{now_ms}-{uuid4().hex}"

        allowed, _, retry_after_ms = await self._redis.eval(
            SLIDING_WINDOW_LUA,
            1,
            key,
            now_ms,
            window_ms,
            self._limit,
            member,
        )

        if int(allowed) == 0:
            retry_after_seconds = max(1, math.ceil(int(retry_after_ms) / 1000))
            raise RateLimitExceededError(retry_after_seconds=retry_after_seconds)

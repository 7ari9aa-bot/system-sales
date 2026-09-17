"""Redis rate limiters.

Two limiters share the same ``allow()`` interface and result type:

- RateLimiter: sliding-window over a sorted set — precise, slightly heavier.
  Runs as a single Lua script so prune / count / add / expire are atomic.
- FixedWindowLimiter: INCR + EXPIRE counter — cheaper, but allows up to 2x
  the limit across a window boundary. Windows follow Redis server time.

Note the sliding window only counts *allowed* requests: a denied request does
not insert a member, so denied traffic cannot further consume capacity.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import redis.asyncio as aioredis

SLIDING_WINDOW_LUA = """
local key      = KEYS[1]
local now      = tonumber(ARGV[1])
local window   = tonumber(ARGV[2])
local limit    = tonumber(ARGV[3])
local member   = ARGV[4]
local ttl_ms   = tonumber(ARGV[5])

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count     = redis.call('ZCARD', key)
local allowed   = 0
local remaining = 0
local retry_ms  = 0
if count < limit then
    redis.call('ZADD', key, now, member)
    count     = count + 1
    allowed   = 1
    remaining = limit - count
else
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    if oldest[2] ~= nil then
        retry_ms = math.max(0, math.ceil(tonumber(oldest[2]) + window - now))
    end
end
redis.call('PEXPIRE', key, ttl_ms)
return {allowed, remaining, retry_ms}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Outcome of a rate limit check.

    ``remaining`` is the number of further allowed calls inside the current
    window; ``retry_after_seconds`` is 0.0 unless the call was denied.
    """

    allowed: bool
    remaining: int
    retry_after_seconds: float


class RateLimiter:
    """Sliding-window limiter backed by a Redis sorted set (atomic via Lua)."""

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        limit: int,
        window_seconds: float,
        prefix: str = "rl",
        clock: Callable[[], float] | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._client = client
        self._limit = limit
        self._window_seconds = window_seconds
        self._prefix = prefix
        self._clock = clock or time.time

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def allow(self, key: str) -> RateLimitResult:
        now_ms = int(self._clock() * 1000)
        window_ms = int(self._window_seconds * 1000)
        member = f"{self._key(key)}:{uuid.uuid4().hex}"
        allowed, remaining, retry_ms = await self._client.eval(
            SLIDING_WINDOW_LUA,
            1,
            self._key(key),
            now_ms,
            window_ms,
            self._limit,
            member,
            window_ms,
        )
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=int(remaining),
            retry_after_seconds=int(retry_ms) / 1000.0,
        )


class FixedWindowLimiter:
    """Simple INCR/EXPIRE counter over fixed windows — cheaper, burstier."""

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        limit: int,
        window_seconds: float,
        prefix: str = "fw",
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._client = client
        self._limit = limit
        self._window_seconds = window_seconds
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def allow(self, key: str) -> RateLimitResult:
        name = self._key(key)
        window_ms = int(self._window_seconds * 1000)
        count = await self._client.incr(name)
        if count == 1:
            await self._client.pexpire(name, window_ms)
            ttl_ms = window_ms
        else:
            ttl_ms = await self._client.pttl(name)
            if ttl_ms < 0:  # expiry lost (e.g. manual PERSIST) — restore it
                await self._client.pexpire(name, window_ms)
                ttl_ms = window_ms
        allowed = count <= self._limit
        remaining = max(0, self._limit - count)
        retry_after = 0.0 if allowed else max(ttl_ms, 0) / 1000.0
        return RateLimitResult(
            allowed=allowed, remaining=remaining, retry_after_seconds=retry_after
        )

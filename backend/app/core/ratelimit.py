"""Redis rate limiters.

Two single-bucket limiters share the same ``allow()`` interface and result type:

- RateLimiter: sliding-window over a sorted set — precise, slightly heavier.
  Runs as a single Lua script so prune / count / add / expire are atomic.
- FixedWindowLimiter: INCR + EXPIRE counter — cheaper, but allows up to 2x
  the limit across a window boundary. Windows follow Redis server time.

Note the sliding window only counts *allowed* requests: a denied request does
not insert a member, so denied traffic cannot further consume capacity.

LayeredRateLimiter (spec §25) checks several buckets — IP, tenant, user,
endpoint — in ONE Lua call. The script prunes and counts every bucket first and
only records the request when ALL buckets allow, so a request denied at a later
tier has not already consumed capacity at an earlier one (the same
"denied traffic costs nothing" property, extended across tiers). Each tier has
its own key, which is what makes "one tenant cannot exhaust another's budget"
true.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
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


# Prune + count every tier, and only if EVERY tier allows, record the request.
# Doing it in one script is what keeps "a denied request consumes no capacity"
# true across tiers instead of only within a single bucket.
LAYERED_WINDOW_LUA = """
local now      = tonumber(ARGV[1])
local window   = tonumber(ARGV[2])
local ttl_ms   = tonumber(ARGV[3])
local n        = #KEYS
local denied   = 0
local denied_i = 0
local retry_ms = 0

for i = 1, n do
    local key   = KEYS[i]
    local limit = tonumber(ARGV[2 + 2 * i])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    local count = redis.call('ZCARD', key)
    if count >= limit and denied == 0 then
        denied   = 1
        denied_i = i
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        if oldest[2] ~= nil then
            retry_ms = math.max(0, math.ceil(tonumber(oldest[2]) + window - now))
        end
    end
end

if denied == 1 then
    return {0, denied_i, retry_ms}
end

for i = 1, n do
    local member = ARGV[3 + 2 * i]
    redis.call('ZADD', KEYS[i], now, member)
    redis.call('PEXPIRE', KEYS[i], ttl_ms)
end
return {1, 0, 0}
"""


@dataclass(frozen=True, slots=True)
class TierLimit:
    """One bucket in a layered check.

    ``key`` is the identity within the tier (tenant id, user id, client ip …).
    ``fail_closed`` is consulted only when Redis itself is unreachable: an
    auth-tier bucket must keep protecting the endpoint even without the cache,
    while the throughput tiers prefer availability.
    """

    name: str
    key: str
    limit: int
    fail_closed: bool = False


@dataclass(frozen=True, slots=True)
class LayeredResult:
    """Aggregate outcome across tiers; ``denied_tier`` names the first denier."""

    allowed: bool
    retry_after_seconds: float = 0.0
    denied_tier: str | None = None


class LayeredRateLimiter:
    """Sliding-window limit across several independent tiers, atomically.

    Tiers are evaluated in the order given; the first one over its limit
    denies the request and is reported in ``denied_tier``. Because the Lua
    script only records when every tier allows, a denied request does not
    consume capacity in any tier.
    """

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        window_seconds: float = 60.0,
        prefix: str = "rl",
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._window_seconds = window_seconds
        self._prefix = prefix
        self._clock = clock or time.time

    def _key(self, tier: TierLimit) -> str:
        return f"{self._prefix}:{tier.name}:{tier.key}"

    async def check(self, tiers: Sequence[TierLimit]) -> LayeredResult:
        tiers = [t for t in tiers if t.limit > 0]
        if not tiers:
            return LayeredResult(allowed=True)

        now_ms = int(self._clock() * 1000)
        window_ms = int(self._window_seconds * 1000)
        keys = [self._key(t) for t in tiers]
        args: list[int | str] = [now_ms, window_ms, window_ms]
        for tier in tiers:
            args.append(tier.limit)
            args.append(f"{self._prefix}:{uuid.uuid4().hex}")
        try:
            allowed, denied_index, retry_ms = await self._client.eval(
                LAYERED_WINDOW_LUA, len(keys), *keys, *args
            )
        except Exception:
            # Redis is unreachable. Fail CLOSED if any tier is a
            # brute-force/auth bucket (protection must not vanish with the
            # cache); otherwise fail OPEN so a cache outage cannot take the
            # whole API down. Mirrors the single-tier policy below.
            closed = [t for t in tiers if t.fail_closed]
            if closed:
                return LayeredResult(
                    allowed=False,
                    retry_after_seconds=float(self._window_seconds),
                    denied_tier=closed[0].name,
                )
            return LayeredResult(allowed=True)

        if int(allowed) == 1:
            return LayeredResult(allowed=True)

        index = int(denied_index) - 1
        name = tiers[index].name if 0 <= index < len(tiers) else "unknown"
        return LayeredResult(
            allowed=False,
            retry_after_seconds=int(retry_ms) / 1000.0,
            denied_tier=name,
        )

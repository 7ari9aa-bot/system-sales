"""Progressive per-account login lockout (Redis-backed).

Brute-force protection that survives process restarts and multiple workers:
failures accumulate in Redis under a key derived from the (ip, email) pair,
and once a threshold of CONSECUTIVE failures is reached the pair is locked
out with an exponentially growing duration — 15 minutes on the first lock,
doubling per additional failure, capped at 24 hours.

Design notes:
- The helper is deliberately policy-free about WHAT a failure is: the login
  flow calls ``record_failure`` after a bad credential and ``reset`` after a
  successful one. Rate limiting (middleware §25) caps request VOLUME per
  window; this caps ATTEMPTS per account, which a distributed attacker
  spreads across IPs — the two layers complement each other.
- State lives in ONE Redis hash so counter and lock expiry move together,
  and the increment + lock decision run in a single Lua script (atomic even
  against concurrent failures from both an IP rotation and the real account).
- The counter outlives its own lock: the key TTL is the failure window
  (default 24h, refreshed on every failure), so the NEXT lock after expiry
  escalates instead of starting over at 15 minutes.
- An ACTIVE lock is not extended by more failures — each step up happens
  only once the previous lock has expired, which keeps the backoff
  predictable for a user who is waiting out the timer.
- Fail-open on Redis outage is deliberate at THIS layer: the §25 auth bucket
  in front of the login endpoint already fails closed, so an outage degrades
  per-account lockout (not brute-force protection as a whole) rather than
  taking login down entirely.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass

import redis.asyncio as aioredis

#: Consecutive failures before the first lock.
DEFAULT_FAILURE_THRESHOLD = 5
#: First lock duration (the audit constant: 15 minutes).
DEFAULT_BASE_LOCK_SECONDS = 15 * 60.0
#: Escalation cap (the audit constant: 24 hours).
DEFAULT_MAX_LOCK_SECONDS = 24 * 60 * 60.0
#: How long the failure counter itself survives WITHOUT a new failure. The
#: next failure refreshes it, so sustained attacks escalate and a quiet
#: account starts fresh.
DEFAULT_COUNTER_TTL_SECONDS = 24 * 60 * 60.0

_PREFIX = "auth_lockout"

_RECORD_LUA = """
local key       = KEYS[1]
local now_ms    = tonumber(ARGV[1])
local threshold = tonumber(ARGV[2])
local base_ms   = tonumber(ARGV[3])
local max_ms    = tonumber(ARGV[4])
local ttl_ms    = tonumber(ARGV[5])

local failures = tonumber(redis.call('HINCRBY', key, 'failures', 1))
local lock_until = tonumber(redis.call('HGET', key, 'lock_until') or '0')
local retry_ms = 0

if lock_until > now_ms then
    -- Already locked: report the remaining time, do not extend it.
    retry_ms = lock_until - now_ms
elseif failures >= threshold then
    -- First lock at the threshold, doubling per failure after it, capped.
    local step = failures - threshold
    local duration = math.min(base_ms * (2 ^ step), max_ms)
    lock_until = now_ms + duration
    retry_ms = duration
    redis.call('HSET', key, 'lock_until', lock_until)
end

redis.call('PEXPIRE', key, ttl_ms)
return {failures, lock_until, retry_ms}
"""


@dataclass(frozen=True, slots=True)
class LockoutStatus:
    """Outcome of a lockout check or a recorded failure.

    ``locked`` is True when the (ip, email) pair must be refused;
    ``retry_after_seconds`` is the remaining lock time (0 when unlocked);
    ``failures`` is the consecutive-failure count (diagnostics only).
    """

    locked: bool
    failures: int
    retry_after_seconds: float


def lockout_key(ip: str, email: str) -> str:
    """The Redis key for one (ip, email) pair.

    The email is normalized (trimmed, case-folded) so ``User@x.com`` and
    ``user@x.com`` share a budget, then hashed — keys must never carry raw
    user identifiers, and a hostile email string must not be able to shape
    the key namespace.
    """
    normalized = email.strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{_PREFIX}:{ip or 'unknown'}:{digest}"


def _ms(clock: Callable[[], float]) -> int:
    return int(clock() * 1000)


async def check(
    client: aioredis.Redis,
    *,
    ip: str,
    email: str,
    clock: Callable[[], float] | None = None,
) -> LockoutStatus:
    """Whether this (ip, email) pair is currently locked out."""
    now_ms = _ms(clock or time.time)
    failures, lock_until = await client.hmget(lockout_key(ip, email), "failures", "lock_until")
    lock_until_ms = int(lock_until) if lock_until else 0
    remaining_ms = max(0, lock_until_ms - now_ms)
    return LockoutStatus(
        locked=remaining_ms > 0,
        failures=int(failures) if failures else 0,
        retry_after_seconds=remaining_ms / 1000.0,
    )


async def record_failure(
    client: aioredis.Redis,
    *,
    ip: str,
    email: str,
    threshold: int = DEFAULT_FAILURE_THRESHOLD,
    base_lock_seconds: float = DEFAULT_BASE_LOCK_SECONDS,
    max_lock_seconds: float = DEFAULT_MAX_LOCK_SECONDS,
    counter_ttl_seconds: float = DEFAULT_COUNTER_TTL_SECONDS,
    clock: Callable[[], float] | None = None,
) -> LockoutStatus:
    """Record one failed attempt and lock the pair once the threshold is hit.

    The first lock at ``threshold`` lasts ``base_lock_seconds``; every
    additional failure past it (recorded after the previous lock expired)
    doubles the next lock, capped at ``max_lock_seconds``. Atomic: the
    increment, escalation decision and TTL refresh run in one Lua call.
    """
    if threshold < 1:
        raise ValueError("threshold must be >= 1")
    if base_lock_seconds <= 0 or max_lock_seconds < base_lock_seconds:
        raise ValueError("lock durations must be positive and max >= base")
    now_ms = _ms(clock or time.time)
    failures, _lock_until, retry_ms = await client.eval(
        _RECORD_LUA,
        1,
        lockout_key(ip, email),
        now_ms,
        threshold,
        int(base_lock_seconds * 1000),
        int(max_lock_seconds * 1000),
        int(counter_ttl_seconds * 1000),
    )
    return LockoutStatus(
        locked=int(retry_ms) > 0,
        failures=int(failures),
        retry_after_seconds=int(retry_ms) / 1000.0,
    )


async def reset(client: aioredis.Redis, *, ip: str, email: str) -> None:
    """Clear the pair's state — call after a SUCCESSFUL authentication."""
    await client.delete(lockout_key(ip, email))

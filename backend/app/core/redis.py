"""Redis client factory.

In production, cache and streams must live on separate Redis instances: a shared
instance with an allkeys-* eviction policy can evict stream entries. The URL in
REDIS_URL should therefore point at the streams/queue instance for workers.

§163: a circuit breaker lets the system fail open when Redis is down instead of
stalling every request. That gate is DELIBERATELY process-local and is NOT the
canonical ``app.core.circuit_breaker.get_breaker`` registry, for two structural
reasons: (1) the state a breaker records lives in the dependency it guards, and
Redis — the dependency here — cannot store "is Redis down"; (2) the gate is a
synchronous boolean (``redis_available()``) consulted before a call, whereas the
canonical breaker routes an awaitable through an async ``call()``. What must NOT
be local is the POLICY: the failure threshold, recovery window and half-open
probe count are read from the SAME settings every named breaker uses
(``circuit_breaker_failure_threshold`` / ``_recovery_seconds`` /
``_half_open_successes``), so one operator tuning changes Redis too.
"""

import threading
import time
from collections.abc import Callable

from redis.asyncio import Redis, from_url

from app.core.config import get_settings

_client: Redis | None = None

# Injectable clock so tests fast-forward the recovery window without sleeping.
_monotonic: Callable[[], float] = time.monotonic

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class _ProcessLocalBreaker:
    """Synchronous closed / open / half-open gate with config-driven thresholds.

    The state machine mirrors ``app.core.circuit_breaker.CircuitBreaker`` exactly
    (fail-closed → open for ``recovery`` seconds → half-open admitting probes →
    ``half_open_successes`` clean probes close, any probe failure re-opens), but
    as a plain-thread gate rather than an asyncio one, because the callers below
    are synchronous.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = CLOSED
        self._failures = 0
        self._probe_successes = 0
        self._opened_at = 0.0

    @staticmethod
    def _thresholds() -> tuple[int, float, int]:
        s = get_settings()
        return (
            s.circuit_breaker_failure_threshold,
            s.circuit_breaker_recovery_seconds,
            s.circuit_breaker_half_open_successes,
        )

    def available(self) -> bool:
        """True when a call may proceed (closed or half-open), False when open."""
        _, recovery, _ = self._thresholds()
        with self._lock:
            self._resolve_half_open(recovery)
            return self._state != OPEN

    def record_failure(self) -> None:
        threshold, recovery, _ = self._thresholds()
        with self._lock:
            self._resolve_half_open(recovery)
            if self._state == HALF_OPEN:
                self._trip(recovery)  # a failed probe re-opens with a fresh timer
            elif self._state == CLOSED:
                self._failures += 1
                if self._failures >= threshold:
                    self._trip(recovery)
            # already OPEN: another path tripped, nothing to add

    def record_success(self) -> None:
        _, recovery, half_open_successes = self._thresholds()
        with self._lock:
            self._resolve_half_open(recovery)
            if self._state == HALF_OPEN:
                self._probe_successes += 1
                if self._probe_successes >= half_open_successes:
                    self._close()
            elif self._state == CLOSED:
                self._failures = 0

    # -- internals (call under self._lock) ---------------------------------

    def _resolve_half_open(self, recovery: float) -> None:
        if self._state == OPEN and _monotonic() - self._opened_at >= recovery:
            self._state = HALF_OPEN
            self._probe_successes = 0

    def _trip(self, recovery: float) -> None:
        self._state = OPEN
        self._opened_at = _monotonic()
        self._failures = 0
        self._probe_successes = 0

    def _close(self) -> None:
        self._state = CLOSED
        self._failures = 0
        self._probe_successes = 0


# §163: the shared process-local breaker.
_breaker = _ProcessLocalBreaker()


def redis_available() -> bool:
    """§163: check the circuit breaker. False when Redis is tripped."""
    return _breaker.available()


def _record_failure() -> None:
    _breaker.record_failure()


def _record_success() -> None:
    _breaker.record_success()


def get_redis() -> Redis:
    global _client
    if _client is None:
        # socket_timeout MUST exceed the workers' XREADGROUP block window,
        # otherwise idle streams raise TimeoutError on every poll.
        _client = from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_timeout=30.0,
            socket_connect_timeout=10.0,
            health_check_interval=15,
            retry_on_timeout=True,
        )
    return _client


def get_redis_or_none() -> Redis | None:
    """§163: return Redis client or None when breaker is open."""
    if not redis_available():
        return None
    return get_redis()


async def is_redis_healthy() -> bool:
    """§163: check Redis health with circuit breaker."""
    if not redis_available():
        return False
    try:
        client = get_redis()
        await client.ping()
        _record_success()
        return True
    except Exception:
        _record_failure()
        return False


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None

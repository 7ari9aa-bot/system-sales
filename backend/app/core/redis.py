"""Redis client factory.

In production, cache and streams must live on separate Redis instances: a shared
instance with an allkeys-* eviction policy can evict stream entries. The URL in
REDIS_URL should therefore point at the streams/queue instance for workers.

§163: a shared circuit breaker lets the system fail open when Redis is down
instead of stalling every request.
"""

import threading
import time

from redis.asyncio import Redis, from_url

from app.core.config import get_settings

_client: Redis | None = None

# §163: shared circuit breaker state — trips after 5 consecutive failures,
# stays open for 30 seconds before re-trying.
_breaker_failures = 0
_breaker_open_until = 0.0
_breaker_lock = threading.Lock()


def redis_available() -> bool:
    """§163: check the circuit breaker. False when Redis is tripped."""
    global _breaker_open_until
    with _breaker_lock:
        if _breaker_open_until > time.monotonic():
            return False
        return True


def _record_failure() -> None:
    global _breaker_failures, _breaker_open_until
    with _breaker_lock:
        _breaker_failures += 1
        if _breaker_failures >= 5:
            _breaker_open_until = time.monotonic() + 30.0


def _record_success() -> None:
    global _breaker_failures
    with _breaker_lock:
        _breaker_failures = 0


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

"""Redis client factory.

In production, cache and streams must live on separate Redis instances: a shared
instance with an allkeys-* eviction policy can evict stream entries. The URL in
REDIS_URL should therefore point at the streams/queue instance for workers.
"""

from redis.asyncio import Redis, from_url

from app.core.config import get_settings

_client: Redis | None = None


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


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None

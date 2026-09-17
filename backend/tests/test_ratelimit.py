"""Rate limiter tests against fakeredis (sliding window + fixed window)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fakeredis.aioredis import FakeRedis

from app.core.ratelimit import FixedWindowLimiter, RateLimiter, RateLimitResult


@pytest.fixture
async def redis_client() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_sliding_window_allows_up_to_limit_then_blocks(redis_client: FakeRedis) -> None:
    limiter = RateLimiter(redis_client, limit=3, window_seconds=10, prefix="t1")
    results = [await limiter.allow("k") for _ in range(3)]

    assert [r.allowed for r in results] == [True, True, True]
    assert [r.remaining for r in results] == [2, 1, 0]
    assert all(r.retry_after_seconds == 0.0 for r in results)

    blocked = await limiter.allow("k")
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert 0 < blocked.retry_after_seconds <= 10


async def test_sliding_window_is_per_key(redis_client: FakeRedis) -> None:
    # pinned clock so the retry_after math is exact
    limiter = RateLimiter(
        redis_client, limit=1, window_seconds=10, prefix="t2", clock=lambda: 100.0
    )
    assert (await limiter.allow("a")).allowed is True
    blocked = await limiter.allow("a")
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == pytest.approx(10.0)
    assert (await limiter.allow("b")).allowed is True  # other keys unaffected


async def test_sliding_window_allows_again_after_window_via_clock(redis_client: FakeRedis) -> None:
    now = [1_000_000.0]
    limiter = RateLimiter(
        redis_client, limit=2, window_seconds=10, prefix="t3", clock=lambda: now[0]
    )

    assert (await limiter.allow("k")).allowed is True
    assert (await limiter.allow("k")).allowed is True
    assert (await limiter.allow("k")).allowed is False

    now[0] += 10.5  # slide past the window edge
    result = await limiter.allow("k")
    assert result.allowed is True
    assert result.remaining == 1  # old members were pruned, this call filled one slot


async def test_sliding_window_purges_stale_scores(redis_client: FakeRedis) -> None:
    # seed members with long-expired scores directly; they must not count
    stale = {f"stale:{i}": 1_000.0 for i in range(5)}
    await redis_client.zadd("t4:k", stale)

    limiter = RateLimiter(redis_client, limit=3, window_seconds=10, prefix="t4")
    result = await limiter.allow("k")

    assert result.allowed is True
    assert result.remaining == 2
    assert await redis_client.zcard("t4:k") == 1  # only the new member remains


async def test_fixed_window_allows_up_to_limit_then_blocks(redis_client: FakeRedis) -> None:
    limiter = FixedWindowLimiter(redis_client, limit=2, window_seconds=5, prefix="t5")
    first = await limiter.allow("k")
    second = await limiter.allow("k")
    third = await limiter.allow("k")

    assert (first.allowed, first.remaining) == (True, 1)
    assert (second.allowed, second.remaining) == (True, 0)
    assert third.allowed is False
    assert third.remaining == 0
    assert 0 < third.retry_after_seconds <= 5


async def test_fixed_window_resets_in_next_window(redis_client: FakeRedis) -> None:
    limiter = FixedWindowLimiter(redis_client, limit=1, window_seconds=5, prefix="t6")
    assert (await limiter.allow("k")).allowed is True
    assert (await limiter.allow("k")).allowed is False

    await redis_client.delete("t6:k")  # simulate the window rolling over
    result = await limiter.allow("k")
    assert result.allowed is True
    assert result.remaining == 0


async def test_limiters_share_result_interface(redis_client: FakeRedis) -> None:
    limiters = [
        RateLimiter(redis_client, limit=1, window_seconds=1, prefix="t7a"),
        FixedWindowLimiter(redis_client, limit=1, window_seconds=1, prefix="t7b"),
    ]
    for limiter in limiters:
        result = await limiter.allow("shared")
        assert isinstance(result, RateLimitResult)
        assert result.allowed is True
        assert result.remaining == 0
        assert result.retry_after_seconds == 0.0

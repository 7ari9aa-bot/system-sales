"""Meta's 20-messages-per-second ceiling for one WhatsApp number, enforced where sends happen.

Nothing enforced it before, so a campaign or a burst of AI replies could push a number past the cap
and collect 130429s that the merchant saw as failures. Two properties matter and both are tested
here:

* the budget is PER NUMBER (two numbers do not share one), and it is shared across processes — it
  lives in Redis, not in memory;
* the caller PACES (waits for the next slot) rather than failing, and only hands back a retryable
  error when the wait would be longer than the worker's backoff should cover.

The limiter is injected, so the arithmetic is tested without sleeping for real seconds.
"""

from __future__ import annotations

import pytest

from app.core.errors import ExternalProviderError
from app.core.ratelimit import RateLimitResult
from app.applications.apparel.modules.conversations.gateway import whatsapp_throughput as throughput

pytestmark = pytest.mark.asyncio


class _FakeLimiter:
    """Records the key it was asked about and answers from a script."""

    def __init__(self, results: list[RateLimitResult]) -> None:
        self.results = list(results)
        self.keys: list[str] = []

    async def allow(self, key: str) -> RateLimitResult:
        self.keys.append(key)
        return self.results.pop(0) if self.results else RateLimitResult(True, 19, 0.0)


class _FakeRedis:
    pass


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(throughput.asyncio, "sleep", fake_sleep)
    return recorded


def _patch_limiter(monkeypatch, limiter: _FakeLimiter) -> None:
    monkeypatch.setattr(throughput, "_limiter", lambda client: limiter)


async def test_a_slot_inside_the_cap_costs_nothing(monkeypatch, sleeps) -> None:
    limiter = _FakeLimiter([RateLimitResult(True, 19, 0.0)])
    _patch_limiter(monkeypatch, limiter)
    waited = await throughput.acquire("456", client=_FakeRedis())
    assert waited == 0.0 and sleeps == []


async def test_a_full_second_is_waited_out_instead_of_failing(monkeypatch, sleeps) -> None:
    limiter = _FakeLimiter([RateLimitResult(False, 0, 0.25), RateLimitResult(True, 19, 0.0)])
    _patch_limiter(monkeypatch, limiter)
    waited = await throughput.acquire("456", client=_FakeRedis())
    assert sleeps == [0.25]
    assert waited == 0.25


async def test_a_wait_longer_than_the_budget_goes_back_to_the_worker(monkeypatch, sleeps) -> None:
    """The message is not lost: the worker's own backoff retries it."""
    limiter = _FakeLimiter([RateLimitResult(False, 0, throughput.MAX_WAIT_SECONDS + 1)])
    _patch_limiter(monkeypatch, limiter)
    with pytest.raises(ExternalProviderError) as exc_info:
        await throughput.acquire("456", client=_FakeRedis())
    assert exc_info.value.retryable is True
    assert sleeps == []


async def test_the_budget_is_per_number(monkeypatch, sleeps) -> None:
    """Two numbers have 20 each; one busy number must not slow the other."""
    limiter = _FakeLimiter([RateLimitResult(True, 19, 0.0), RateLimitResult(True, 19, 0.0)])
    _patch_limiter(monkeypatch, limiter)
    await throughput.acquire("456", client=_FakeRedis())
    await throughput.acquire("789", client=_FakeRedis())
    assert limiter.keys == ["456", "789"]


async def test_without_redis_the_send_is_not_blocked(monkeypatch) -> None:
    """Meta enforces the same cap and says so; a missing limiter costs a 130429, not a message."""
    monkeypatch.setattr("app.core.redis.get_redis_or_none", lambda: None, raising=True)
    assert await throughput.acquire("456") == 0.0


async def test_a_limiter_fault_never_stops_a_legal_send(monkeypatch, sleeps) -> None:
    class _Broken:
        async def allow(self, key: str):
            raise RuntimeError("redis down")

    monkeypatch.setattr(throughput, "_limiter", lambda client: _Broken())
    assert await throughput.acquire("456", client=_FakeRedis()) == 0.0


async def test_the_documented_cap_is_twenty_a_second() -> None:
    assert throughput.MESSAGES_PER_SECOND == 20
    assert throughput.WINDOW_SECONDS == 1.0


# ---------------------------------------------------------------- against real Redis


async def test_twenty_one_sends_in_a_second_are_paced(monkeypatch) -> None:
    """The real limiter, the real budget: the 21st send waits for the window to move."""
    aioredis = pytest.importorskip("redis.asyncio")
    try:
        client = aioredis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
        await client.ping()
    except Exception:  # noqa: BLE001 - no Redis in this environment
        pytest.skip("no Redis available")

    key_number = "mps-test-number"
    await client.delete(f"wa-mps:{key_number}")
    # MAX_WAIT must not fire: the 21st send only waits for the tail of one window.
    monkeypatch.setattr(throughput, "MAX_WAIT_SECONDS", 2.0)

    import time

    started = time.monotonic()
    for _ in range(throughput.MESSAGES_PER_SECOND + 1):
        await throughput.acquire(key_number, client=client)
    elapsed = time.monotonic() - started

    assert elapsed >= throughput.WINDOW_SECONDS * 0.5, "the cap was not enforced"
    await client.delete(f"wa-mps:{key_number}")

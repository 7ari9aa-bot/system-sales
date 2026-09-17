"""CircuitBreaker state machine tests using a fake clock (no sleeps)."""

from __future__ import annotations

import pytest

from app.core.circuit_breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker
from app.core.errors import CircuitOpenError


class FakeClock:
    """Injectable monotonic clock; tests advance ``now`` instead of sleeping."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def failing() -> None:
    raise RuntimeError("boom")


async def ok() -> int:
    return 42


async def test_opens_after_failure_threshold() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=3,
        recovery_timeout_seconds=10,
        half_open_successes=2,
        time_fn=clock,
    )
    assert breaker.state == CLOSED

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await breaker.call(failing)

    assert breaker.state == OPEN
    assert breaker.failure_count == 3
    assert breaker.opened_at == clock.now
    assert breaker.last_failure == "RuntimeError: boom"


async def test_open_breaker_raises_circuit_open_error_without_calling_fn() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=10, time_fn=clock)
    with pytest.raises(RuntimeError):
        await breaker.call(failing)

    calls = {"n": 0}

    async def probe() -> None:
        calls["n"] += 1

    with pytest.raises(CircuitOpenError):
        await breaker.call(probe)
    assert calls["n"] == 0  # fn never runs while the breaker is open


async def test_half_open_after_recovery_timeout_then_closes_after_successes() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=30,
        half_open_successes=2,
        time_fn=clock,
    )
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(failing)
    assert breaker.state == OPEN

    clock.now += 30  # recovery timeout has just elapsed

    assert await breaker.call(ok) == 42
    assert breaker.state == HALF_OPEN  # one probe success is not enough yet
    assert await breaker.call(ok) == 42
    assert breaker.state == CLOSED
    assert breaker.failure_count == 0


async def test_half_open_still_open_before_timeout_elapsed() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=10, time_fn=clock)
    with pytest.raises(RuntimeError):
        await breaker.call(failing)

    clock.now += 9.5  # not yet past the recovery timeout
    with pytest.raises(CircuitOpenError) as excinfo:
        await breaker.call(ok)
    assert breaker.state == OPEN
    assert excinfo.value.details["retry_after_seconds"] == pytest.approx(0.5)
    assert excinfo.value.http_status == 503


async def test_reopens_on_half_open_failure_with_fresh_timer() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout_seconds=5, time_fn=clock)
    with pytest.raises(RuntimeError):
        await breaker.call(failing)
    assert breaker.state == OPEN

    clock.now += 5  # probe phase
    with pytest.raises(RuntimeError):
        await breaker.call(failing)
    assert breaker.state == OPEN
    assert breaker.opened_at == clock.now  # timer restarted at the failure

    # still rejecting immediately after the re-trip
    with pytest.raises(CircuitOpenError):
        await breaker.call(ok)


async def test_success_in_closed_state_resets_failure_count() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=10, time_fn=clock)
    with pytest.raises(RuntimeError):
        await breaker.call(failing)
    assert breaker.failure_count == 1

    assert await breaker.call(ok) == 42
    assert breaker.failure_count == 0
    assert breaker.state == CLOSED

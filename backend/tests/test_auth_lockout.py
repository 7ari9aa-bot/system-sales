"""Progressive login lockout (core.auth_lockout) — Redis-backed, fakeredis.

The helper is the per-ACCOUNT half of brute-force protection: the §25 auth
bucket caps request VOLUME per IP window, but a distributed attacker spreads
attempts across addresses. This locks the (ip, email) PAIR after 5 consecutive
failures — 15 minutes, doubling per escalation, capped at 24 hours — and the
counter resets only on a successful login (reset) or after the failure window
expires.

DB-free: runs against fakeredis everywhere, unchanged in CI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fakeredis.aioredis import FakeRedis

from app.core.auth_lockout import (
    DEFAULT_BASE_LOCK_SECONDS,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_MAX_LOCK_SECONDS,
    check,
    lockout_key,
    record_failure,
    reset,
)

#: Deterministic clock every test advances explicitly.
T0 = 1_000_000.0


@pytest.fixture
async def redis_client() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


def _clock(at: list[float]):
    return lambda: at[0]


async def test_below_the_threshold_nothing_locks(redis_client: FakeRedis) -> None:
    clock = _clock([T0])
    for _ in range(DEFAULT_FAILURE_THRESHOLD - 1):
        status = await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
        assert status.locked is False

    state = await check(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
    assert state.locked is False
    assert state.failures == DEFAULT_FAILURE_THRESHOLD - 1
    assert state.retry_after_seconds == 0.0


async def test_the_threshold_failure_locks_for_fifteen_minutes(redis_client: FakeRedis) -> None:
    clock = _clock([T0])
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        status = await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)

    assert status.locked is True
    assert status.retry_after_seconds == pytest.approx(DEFAULT_BASE_LOCK_SECONDS)
    state = await check(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
    assert state.locked is True


async def test_an_active_lock_is_reported_but_not_extended(redis_client: FakeRedis) -> None:
    clock = _clock([T0])
    for _ in range(DEFAULT_FAILURE_THRESHOLD + 3):
        status = await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)

    # Failures DURING the lock keep the original expiry — the user waiting
    # out the timer must not see it pushed further away.
    assert status.retry_after_seconds == pytest.approx(DEFAULT_BASE_LOCK_SECONDS)


async def test_the_lock_escalates_after_each_expiry(redis_client: FakeRedis) -> None:
    at = [T0]
    clock = _clock(at)

    # The threshold failure locks for the base duration…
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        status = await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
    assert status.locked is True
    assert status.retry_after_seconds == pytest.approx(DEFAULT_BASE_LOCK_SECONDS)

    # …and the FIRST failure after the lock expires doubles it (escalation is
    # per failure past the threshold, and the counter survived the lock).
    at[0] += DEFAULT_BASE_LOCK_SECONDS + 1
    status = await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
    assert status.locked is True
    assert status.retry_after_seconds == pytest.approx(DEFAULT_BASE_LOCK_SECONDS * 2)

    at[0] += DEFAULT_BASE_LOCK_SECONDS * 2 + 1
    status = await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
    assert status.locked is True
    assert status.retry_after_seconds == pytest.approx(DEFAULT_BASE_LOCK_SECONDS * 4)


async def test_the_escalation_is_capped_at_twenty_four_hours(redis_client: FakeRedis) -> None:
    at = [T0]
    clock = _clock(at)

    async def _one_failure() -> float:
        status = await record_failure(
            redis_client, ip="1.2.3.4", email="a@x.com", clock=clock
        )
        assert status.locked
        return status.retry_after_seconds

    # Drive past the threshold, then step one failure at a time to the cap.
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)

    duration = 0.0
    rounds = 0
    while True:
        duration = await _one_failure()
        rounds += 1
        assert duration <= DEFAULT_MAX_LOCK_SECONDS + 0.001
        if duration >= DEFAULT_MAX_LOCK_SECONDS:
            break
        at[0] += duration + 1
        assert rounds < 30, "escalation never reached the cap"

    # And it stays at the cap.
    at[0] += duration + 1
    assert await _one_failure() == pytest.approx(DEFAULT_MAX_LOCK_SECONDS)


async def test_a_successful_login_resets_the_counter(redis_client: FakeRedis) -> None:
    clock = _clock([T0])
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
    await reset(redis_client, ip="1.2.3.4", email="a@x.com")

    state = await check(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
    assert state.locked is False
    assert state.failures == 0

    # Starting over means starting at the base duration, not the escalated one.
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        status = await record_failure(redis_client, ip="1.2.3.4", email="a@x.com", clock=clock)
    assert status.retry_after_seconds == pytest.approx(DEFAULT_BASE_LOCK_SECONDS)


async def test_pairs_are_independent(redis_client: FakeRedis) -> None:
    clock = _clock([T0])
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        await record_failure(redis_client, ip="1.2.3.4", email="victim@x.com", clock=clock)

    other_email = await check(redis_client, ip="1.2.3.4", email="other@x.com", clock=clock)
    other_ip = await check(redis_client, ip="5.6.7.8", email="victim@x.com", clock=clock)
    assert other_email.locked is False
    assert other_ip.locked is False


async def test_the_email_is_normalized_in_the_key(redis_client: FakeRedis) -> None:
    clock = _clock([T0])
    for _ in range(DEFAULT_FAILURE_THRESHOLD):
        await record_failure(redis_client, ip="1.2.3.4", email="User@X.com", clock=clock)

    state = await check(redis_client, ip="1.2.3.4", email="  user@x.com ", clock=clock)
    assert state.locked is True
    assert lockout_key("1.2.3.4", "USER@x.com ") == lockout_key("1.2.3.4", "user@x.com")


async def test_the_key_never_carries_the_raw_email(redis_client: FakeRedis) -> None:
    key = lockout_key("1.2.3.4", "victim@x.com")
    assert "victim@x.com" not in key
    assert key.startswith("auth_lockout:1.2.3.4:")


async def test_a_hostile_email_cannot_escape_the_key_namespace(redis_client: FakeRedis) -> None:
    """The identifier is hashed before it touches the key: a ":" or newline
    in the email cannot forge a different key shape."""
    forged = lockout_key("1.2.3.4", "x:{other}:key")
    assert forged.startswith("auth_lockout:1.2.3.4:")
    assert len(forged.split(":")) == 3


# -------------------------------------------- service-layer fail-open wiring --
#
# The lockout is only a NARROWING layer: the §25 auth bucket in front of login
# fails closed, so a Redis outage must degrade to "no lockout this try" and
# never take sign-in down. `_lockout_op` (identity.service) is the single
# choke point where login's check / record_failure / reset meet Redis; these
# tests pin its fail-open contract DB-free.


@pytest.fixture
async def service_redis(monkeypatch) -> AsyncIterator[FakeRedis]:
    """Point identity.service at a fakeredis the way get_redis_or_none would."""
    from app.modules.identity import service as identity_service

    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        identity_service, "get_redis_or_none", lambda: client
    )
    yield client
    await client.aclose()


async def test_service_lockout_ops_flow_through_a_present_redis(
    service_redis: FakeRedis,
) -> None:
    """With Redis reachable, check/record_failure/reset execute for real."""
    from app.modules.identity import service as identity_service

    status = await identity_service._lockout_op(
        check, ip="9.9.9.9", email="flow@x.com"
    )
    assert status is not None
    assert status.locked is False

    recorded = await identity_service._lockout_op(
        record_failure, ip="9.9.9.9", email="flow@x.com"
    )
    assert recorded is not None and recorded.failures == 1

    # reset returns None by contract — the point is that it did not degrade.
    assert await identity_service._lockout_op(
        reset, ip="9.9.9.9", email="flow@x.com"
    ) is None


async def test_service_lockout_ops_fail_open_when_redis_is_missing(
    monkeypatch,
) -> None:
    """No Redis at all ⇒ every op degrades to None and sign-in proceeds."""
    from app.modules.identity import service as identity_service

    monkeypatch.setattr(
        identity_service, "get_redis_or_none", lambda: None
    )
    for op in (check, record_failure, reset):
        assert await identity_service._lockout_op(
            op, ip="9.9.9.9", email="down@x.com"
        ) is None


async def test_service_lockout_ops_fail_open_when_redis_raises(
    monkeypatch,
) -> None:
    """A live outage (first connection failure, breaker still closed) too.

    get_redis_or_none only reflects the breaker's OPEN state; on the first
    failed dial the raw client raises instead. The ops must still degrade to
    None rather than turn a login into a 500.
    """
    from app.modules.identity import service as identity_service

    class _DeadRedis:
        async def hmget(self, *args, **kwargs):
            raise ConnectionError("redis is down")

        async def eval(self, *args, **kwargs):
            raise ConnectionError("redis is down")

        async def delete(self, *args, **kwargs):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(
        identity_service, "get_redis_or_none", lambda: _DeadRedis()
    )
    for op in (check, record_failure, reset):
        assert await identity_service._lockout_op(
            op, ip="9.9.9.9", email="outage@x.com"
        ) is None

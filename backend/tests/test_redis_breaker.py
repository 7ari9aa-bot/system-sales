"""G-13 — Redis's process-local breaker reads the SAME thresholds as every other.

`app/core/redis.py` §163 kept a *second*, hand-rolled breaker with a hardcoded
"5 consecutive failures / 30 seconds" while `app/core/config.py` exposes
``circuit_breaker_failure_threshold`` / ``circuit_breaker_recovery_seconds`` /
``circuit_breaker_half_open_successes`` — the exact knobs every named breaker in
``app/core/circuit_breaker.py`` reads. Tuning the threshold for the AI provider
and Telegram changed nothing for Redis: two sources of truth for one policy.

Redis's gate is legitimately process-local (you cannot store "is Redis down" in
Redis, and the probe/`redis_available()` path is synchronous, so the async
canonical ``get_breaker().call()`` routing does not fit). What is NOT legitimate
is the numbers being hardcoded. These tests pin that the counts and windows now
come from ``get_settings()``.
"""

from __future__ import annotations

import pytest

from app.core import redis as redis_mod


class _Settings:
    def __init__(self, *, threshold=2, recovery=30.0, half_open=1):
        self.circuit_breaker_failure_threshold = threshold
        self.circuit_breaker_recovery_seconds = recovery
        self.circuit_breaker_half_open_successes = half_open


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(redis_mod, "_monotonic", c, raising=False)
    proc = getattr(redis_mod, "_ProcessLocalBreaker", None)
    if proc is not None:
        monkeypatch.setattr(redis_mod, "_breaker", proc(), raising=False)
    else:  # old hand-rolled module globals
        monkeypatch.setattr(redis_mod, "_breaker_failures", 0, raising=False)
        monkeypatch.setattr(redis_mod, "_breaker_open_until", 0.0, raising=False)
    return c


def _settings(monkeypatch, **kwargs) -> None:
    monkeypatch.setattr(redis_mod, "get_settings", lambda: _Settings(**kwargs))


def test_breaker_opens_at_the_configured_failure_threshold(monkeypatch):
    """Two configured failures trip it — not the five the code used to hardcode."""
    _settings(monkeypatch, threshold=2, recovery=30.0)

    redis_mod._record_failure()
    assert redis_mod.redis_available() is True  # 1 < 2, still closed

    redis_mod._record_failure()
    assert redis_mod.redis_available() is False  # 2 >= 2, now open


def test_recovery_window_comes_from_config(monkeypatch, clock):
    """The open duration is ``circuit_breaker_recovery_seconds``, not a constant 30."""
    _settings(monkeypatch, threshold=1, recovery=5.0)

    redis_mod._record_failure()
    assert redis_mod.redis_available() is False

    clock.now += 4.0
    assert redis_mod.redis_available() is False  # window not elapsed yet

    clock.now += 1.5  # total 5.5 > recovery=5.0 → half-open admits a probe
    assert redis_mod.redis_available() is True


def test_half_open_successes_come_from_config(monkeypatch, clock):
    """Closing needs ``circuit_breaker_half_open_successes`` clean probes, not one."""
    _settings(monkeypatch, threshold=1, recovery=5.0, half_open=2)

    redis_mod._record_failure()
    clock.now += 6.0  # into the half-open window
    assert redis_mod.redis_available() is True

    redis_mod._record_success()  # 1 of 2 required probe successes
    redis_mod._record_failure()  # a failed probe re-opens immediately
    assert redis_mod.redis_available() is False

    clock.now += 6.0
    assert redis_mod.redis_available() is True
    redis_mod._record_success()
    redis_mod._record_success()  # 2 of 2 → closed
    assert redis_mod.redis_available() is True

    redis_mod._record_failure()  # truly closed: threshold=1 trips again on one failure
    assert redis_mod.redis_available() is False

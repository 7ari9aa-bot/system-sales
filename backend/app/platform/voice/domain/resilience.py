"""When a provider starts failing, stop paying for it and use the other one.

A dead realtime provider does not raise one clean error: it accepts the connection, then stops
sending audio, and every caller keeps holding a session that sounds like silence. The breaker counts
consecutive failures per provider, opens, and hands the router an `unavailable` set it already
understands, so failover needs no new routing logic. It closes itself only after a real success in
the half-open probe.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Final

from app.core.errors import CircuitOpenError


class BreakerState(enum.StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


DEFAULT_FAILURE_THRESHOLD: Final[int] = 3
DEFAULT_RECOVERY_SECONDS: Final[int] = 30


@dataclass(slots=True)
class _ProviderBreaker:
    consecutive_failures: int = 0
    state: BreakerState = BreakerState.CLOSED
    opened_at: dt.datetime | None = None
    probes: int = 0


@dataclass(slots=True)
class CircuitBreaker:
    """Per-provider failure counting with a timed, single-probe recovery."""

    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    recovery_seconds: int = DEFAULT_RECOVERY_SECONDS
    clock: object = field(default=lambda: dt.datetime.now(dt.UTC))
    _breakers: dict[str, _ProviderBreaker] = field(default_factory=dict)

    def _breaker(self, provider: str) -> _ProviderBreaker:
        return self._breakers.setdefault(provider, _ProviderBreaker())

    def state(self, provider: str) -> BreakerState:
        breaker = self._breaker(provider)
        if breaker.state is BreakerState.OPEN and breaker.opened_at is not None:
            if (self.clock() - breaker.opened_at).total_seconds() >= self.recovery_seconds:
                # The wait is over: let exactly one call through to find out if it recovered.
                breaker.state = BreakerState.HALF_OPEN
                breaker.probes = 0
        return breaker.state

    def allow(self, provider: str) -> bool:
        state = self.state(provider)
        if state is BreakerState.CLOSED:
            return True
        if state is BreakerState.OPEN:
            return False
        breaker = self._breaker(provider)
        if breaker.probes >= 1:
            return False
        breaker.probes += 1
        return True

    def unavailable(self) -> frozenset[str]:
        """The names to hand the router, so it picks a provider that is not currently failing."""
        return frozenset(name for name in self._breakers if not self.allow(name))

    def record_success(self, provider: str) -> None:
        breaker = self._breaker(provider)
        breaker.consecutive_failures = 0
        breaker.state = BreakerState.CLOSED
        breaker.opened_at = None
        breaker.probes = 0

    def record_failure(self, provider: str) -> None:
        breaker = self._breaker(provider)
        breaker.consecutive_failures += 1
        breaker.probes = 0
        if (
            breaker.consecutive_failures >= self.failure_threshold
            or breaker.state is BreakerState.HALF_OPEN
        ):
            breaker.state = BreakerState.OPEN
            breaker.opened_at = self.clock()


class NoHealthyProvider(CircuitOpenError):
    """Every candidate is open. This is an outage, not a routing preference."""

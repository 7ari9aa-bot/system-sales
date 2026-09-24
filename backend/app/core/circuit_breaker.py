"""Async circuit breaker with closed / open / half-open states.

The breaker wraps a call to a single downstream dependency (e.g. an external
provider). Failures in the closed state count against ``failure_threshold``;
once exceeded the breaker opens and rejects calls with CircuitOpenError until
``recovery_timeout_seconds`` elapse. It then admits probe calls (half-open):
``half_open_successes`` consecutive successes close the breaker, any failure
re-opens it with a fresh timer.

The clock is injectable (``time_fn``) so tests can fast-forward time without
sleeping. Concurrency safety is per-instance via asyncio.Lock — the state
check, success recording and failure recording each run under the lock, while
the wrapped call itself executes outside it.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from app.core.errors import CircuitOpenError

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


def _loop_time() -> float:
    """Default clock: the running event loop's monotonic time."""
    try:
        return asyncio.get_running_loop().time()
    except RuntimeError:  # no running loop (e.g. sync introspection)
        return asyncio.get_event_loop().time()


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
        half_open_successes: int = 2,
        time_fn: Callable[[], float] | None = None,
        name: str = "circuit",
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if half_open_successes < 1:
            raise ValueError("half_open_successes must be >= 1")
        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._half_open_successes = half_open_successes
        self._time_fn = time_fn or _loop_time
        self._name = name
        self._lock = asyncio.Lock()
        self._state: str = CLOSED
        self._failure_count = 0
        self._success_count = 0  # consecutive probe successes recorded in half-open
        self._opened_at = 0.0
        self._last_failure: str | None = None

    # -- introspection -----------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> str:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def opened_at(self) -> float:
        return self._opened_at

    @property
    def last_failure(self) -> str | None:
        return self._last_failure

    @property
    def is_open(self) -> bool:
        return self._state == OPEN

    @property
    def seconds_until_half_open(self) -> float:
        """Seconds until the breaker admits a probe call (0 unless open)."""
        if self._state != OPEN:
            return 0.0
        remaining = self._recovery_timeout_seconds - (self._time_fn() - self._opened_at)
        return max(0.0, remaining)

    # -- call routing --------------------------------------------------------

    async def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Invoke ``fn`` through the breaker state machine.

        Sync callables are also accepted and executed as-is.
        """
        async with self._lock:
            self._before_call()
        try:
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            async with self._lock:
                self._record_failure(exc)
            raise
        async with self._lock:
            self._record_success()
        return result

    # -- state machine (every helper below runs under self._lock) -----------

    def _before_call(self) -> None:
        if self._state != OPEN:
            return
        if self._time_fn() - self._opened_at >= self._recovery_timeout_seconds:
            self._state = HALF_OPEN
            self._success_count = 0
            return
        raise CircuitOpenError(
            f"circuit '{self._name}' is open",
            details={
                "circuit": self._name,
                "retry_after_seconds": round(self.seconds_until_half_open, 3),
            },
        )

    def _record_success(self) -> None:
        if self._state == HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._half_open_successes:
                self._state = CLOSED
                self._failure_count = 0
                self._success_count = 0
        elif self._state == CLOSED:
            self._failure_count = 0

    def _record_failure(self, exc: Exception) -> None:
        self._last_failure = f"{type(exc).__name__}: {exc}"
        if self._state == OPEN:
            return  # another task tripped the breaker while this call ran
        if self._state == HALF_OPEN:
            self._trip_open()
            return
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._trip_open()

    def _trip_open(self) -> None:
        self._state = OPEN
        self._opened_at = self._time_fn()
        self._success_count = 0


# --------------------------------------------------------------- registry ---
#
# A process-wide breaker PER DOWNSTREAM DEPENDENCY. This exists because the
# module was complete, unit-tested and — measured 2026-09-20 — imported by
# nothing except its own test. Each call site building its own breaker would be
# the same bug in a new shape: N breakers for one provider means the provider
# must fail N times before anyone backs off.
#
# The registry is deliberately NOT gated on settings at import: `get_breaker`
# reads them on first use, so importing this module stays free (the same rule
# `app/core/db.py` had to learn).

_BREAKERS: dict[str, CircuitBreaker] = {}


def get_breaker(name: str, **overrides: Any) -> CircuitBreaker:
    """The breaker for a named dependency, created on first use.

    No `await` in here, so the get-then-set is atomic under asyncio's
    single-threaded scheduler.
    """
    existing = _BREAKERS.get(name)
    if existing is not None:
        return existing

    from app.core.config import get_settings

    settings = get_settings()
    breaker = CircuitBreaker(
        name=name,
        failure_threshold=overrides.pop(
            "failure_threshold", settings.circuit_breaker_failure_threshold
        ),
        recovery_timeout_seconds=overrides.pop(
            "recovery_timeout_seconds", settings.circuit_breaker_recovery_seconds
        ),
        half_open_successes=overrides.pop(
            "half_open_successes", settings.circuit_breaker_half_open_successes
        ),
        **overrides,
    )
    _BREAKERS[name] = breaker
    return breaker


def breaker_states() -> dict[str, str]:
    """Snapshot of every breaker this process has created. For diagnostics."""
    return {name: breaker.state for name, breaker in _BREAKERS.items()}


def open_breakers() -> list[str]:
    """Names of the currently OPEN breakers."""
    return [name for name, breaker in _BREAKERS.items() if breaker.is_open]


def reset_breakers() -> None:
    """Drop every breaker. For tests, so one case cannot leak state into the next."""
    _BREAKERS.clear()


# Names of the downstreams that go through a breaker. Defined here, not at the
# call sites, so a typo cannot silently create a second breaker for the same
# provider — the failure mode the registry exists to prevent.
PROVIDER_AI = "provider.ai"
PROVIDER_WHATSAPP = "provider.whatsapp"
PROVIDER_TELEGRAM = "provider.telegram"
PROVIDER_MESSENGER = "provider.messenger"
PROVIDER_INSTAGRAM = "provider.instagram"
PROVIDER_EMAIL = "provider.email"
STORAGE_OBJECTS = "storage.objects"

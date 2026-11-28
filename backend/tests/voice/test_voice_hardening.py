"""Phase 6: a failing provider stops billing, a budget stops a call, and quality fails loudly."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.core.errors import ValidationError
from app.platform.voice.application.hardening import (
    BudgetExceeded,
    CostGuard,
    ResilientChooser,
    RuntimeSnapshot,
    ScaleAction,
    TenantBudget,
    TurnSample,
    autoscale_action,
    evaluate_quality,
)
from app.platform.voice.domain.contracts import AudioPath, ProviderCapabilities
from app.platform.voice.domain.resilience import BreakerState, CircuitBreaker
from app.platform.voice.runtime.providers import FakeRealtimeProvider, ProviderRouter

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
T0 = dt.datetime(2026, 11, 27, 10, 0, tzinfo=dt.UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += dt.timedelta(seconds=seconds)


def _breaker(clock: Clock | None = None) -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=3, recovery_seconds=30, clock=clock or Clock())


class TestCircuitBreaker:
    def test_it_opens_only_after_the_threshold(self) -> None:
        breaker = _breaker()
        breaker.record_failure("a")
        breaker.record_failure("a")
        assert breaker.state("a") is BreakerState.CLOSED
        assert breaker.allow("a") is True
        breaker.record_failure("a")
        assert breaker.state("a") is BreakerState.OPEN
        assert breaker.allow("a") is False

    def test_an_open_breaker_reports_the_provider_as_unavailable(self) -> None:
        breaker = _breaker()
        for _ in range(3):
            breaker.record_failure("primary")
        assert "primary" in breaker.unavailable()

    def test_after_the_wait_one_probe_is_allowed_and_success_closes_it(self) -> None:
        clock = Clock()
        breaker = _breaker(clock)
        for _ in range(3):
            breaker.record_failure("a")
        clock.advance(31)
        assert breaker.state("a") is BreakerState.HALF_OPEN
        assert breaker.allow("a") is True
        assert breaker.allow("a") is False
        breaker.record_success("a")
        assert breaker.state("a") is BreakerState.CLOSED

    def test_a_failed_probe_reopens_it_immediately(self) -> None:
        clock = Clock()
        breaker = _breaker(clock)
        for _ in range(3):
            breaker.record_failure("a")
        clock.advance(31)
        assert breaker.allow("a") is True
        breaker.record_failure("a")
        assert breaker.state("a") is BreakerState.OPEN


class TestFailover:
    def _router(self) -> ProviderRouter:
        router = ProviderRouter()
        caps = ProviderCapabilities(
            name="rt", paths=frozenset({AudioPath.SPEECH_TO_SPEECH}), languages=frozenset({"ar"})
        )
        router.register("primary", caps, FakeRealtimeProvider())
        router.register("backup", caps, FakeRealtimeProvider())
        return router

    def test_the_open_primary_is_skipped_and_the_backup_serves(self) -> None:
        clock = Clock()
        breaker = _breaker(clock)
        for _ in range(3):
            breaker.record_failure("primary")
        chooser = ResilientChooser(router=self._router(), breaker=breaker)
        entry = chooser.choose(path=AudioPath.SPEECH_TO_SPEECH, language="ar-EG", prefer="primary")
        assert entry.name == "backup"

    def test_when_every_provider_is_open_it_says_so(self) -> None:
        breaker = _breaker()
        router = self._router()
        for name in ("primary", "backup"):
            for _ in range(3):
                breaker.record_failure(name)
        chooser = ResilientChooser(router=router, breaker=breaker)
        with pytest.raises(Exception) as caught:
            chooser.choose(path=AudioPath.SPEECH_TO_SPEECH, language="ar-EG")
        assert "no provider" in str(caught.value).lower() or "open" in str(caught.value).lower()


class TestCostGuard:
    def test_a_call_is_authorized_inside_the_budget(self) -> None:
        guard = CostGuard()
        ceiling = guard.authorize_call(TENANT, estimated_seconds=300)
        assert ceiling == 300

    def test_the_call_ceiling_clamps_a_long_call(self) -> None:
        guard = CostGuard(budgets={TENANT: TenantBudget(call_ceiling_seconds=120)})
        assert guard.authorize_call(TENANT, estimated_seconds=900) == 120

    def test_an_exhausted_budget_refuses_before_any_audio(self) -> None:
        guard = CostGuard(budgets={TENANT: TenantBudget(monthly_minor=10, minute_price_minor=6)})
        guard.record(TENANT, seconds=60)
        assert guard.remaining_minor(TENANT) == 4
        with pytest.raises(BudgetExceeded):
            guard.authorize_call(TENANT, estimated_seconds=60)
        assert guard.authorize_call(TENANT, estimated_seconds=30) == 30

    def test_an_overrun_is_visible_and_never_reads_as_credit(self) -> None:
        guard = CostGuard(budgets={TENANT: TenantBudget(monthly_minor=10, minute_price_minor=6)})
        guard.record(TENANT, seconds=600)
        assert guard.remaining_minor(TENANT) < 0
        with pytest.raises(BudgetExceeded):
            guard.authorize_call(TENANT, estimated_seconds=10)

    def test_spending_is_counted_per_tenant(self) -> None:
        other = uuid.uuid4()
        guard = CostGuard()
        guard.record(TENANT, seconds=600)
        assert guard.remaining_minor(TENANT) < guard.remaining_minor(other)

    def test_a_zero_estimate_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            CostGuard().authorize_call(TENANT, estimated_seconds=0)


class TestAutoscale:
    def test_a_full_worker_sheds_new_calls_instead_of_dropping_live_ones(self) -> None:
        snapshot = RuntimeSnapshot(active_sessions=40, capacity=40, p95_turn_ms=900, failure_rate=0)
        assert autoscale_action(snapshot) is ScaleAction.SHED

    def test_pressure_scales_up(self) -> None:
        full = RuntimeSnapshot(active_sessions=32, capacity=40, p95_turn_ms=900, failure_rate=0)
        slow = RuntimeSnapshot(active_sessions=4, capacity=40, p95_turn_ms=3_000, failure_rate=0)
        assert autoscale_action(full) is ScaleAction.SCALE_UP
        assert autoscale_action(slow) is ScaleAction.SCALE_UP

    def test_a_calm_worker_holds(self) -> None:
        calm = RuntimeSnapshot(active_sessions=5, capacity=40, p95_turn_ms=800, failure_rate=0.01)
        assert autoscale_action(calm) is ScaleAction.HOLD

    def test_zero_capacity_is_not_read_as_idle(self) -> None:
        broken = RuntimeSnapshot(active_sessions=1, capacity=0, p95_turn_ms=0, failure_rate=0)
        assert autoscale_action(broken) is ScaleAction.SCALE_UP


class TestQuality:
    def _rows(
        self, n: int, *, ms: int, completed: bool = True, dropped: int = 0
    ) -> list[TurnSample]:
        return [
            TurnSample(turn_ms=ms, completed=completed, dropped_results=dropped) for _ in range(n)
        ]

    def test_a_healthy_run_passes(self) -> None:
        report = evaluate_quality(self._rows(20, ms=900))
        assert report.passed is True
        assert report.p95_turn_ms == 900
        assert report.completion_rate == 1.0

    def test_slow_turns_fail_the_run(self) -> None:
        report = evaluate_quality(self._rows(20, ms=4_000))
        assert report.passed is False
        assert any("p95" in reason for reason in report.reasons)

    def test_dropped_results_fail_the_run(self) -> None:
        rows = self._rows(10, ms=800) + self._rows(10, ms=800, dropped=1)
        report = evaluate_quality(rows)
        assert report.passed is False
        assert any("dropped" in reason for reason in report.reasons)

    def test_incomplete_turns_fail_the_run(self) -> None:
        rows = self._rows(5, ms=800) + self._rows(5, ms=800, completed=False)
        report = evaluate_quality(rows)
        assert report.passed is False
        assert any("completion" in reason for reason in report.reasons)

    def test_no_samples_is_a_failure_not_a_zero(self) -> None:
        report = evaluate_quality([])
        assert report.passed is False
        assert report.reasons == ("no turns to evaluate",)

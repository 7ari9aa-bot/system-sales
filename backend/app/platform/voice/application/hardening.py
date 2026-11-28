"""The three numbers that keep voice from being expensive, slow, or quietly bad.

Cost: a tenant gets a budget for the month and a per-call ceiling, checked before the first second
of audio, because a runaway agent is billed by the minute and a refusal costs nothing.
Load: the runtime reports what autoscaling actually needs (live sessions, turn latency, failures),
not CPU.
Quality: a call that finished is not a call that worked. The evaluation scores the turns it has
and fails the run when p95 latency or the drop rate crosses the line.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from app.core.errors import ValidationError
from app.platform.voice.domain.resilience import CircuitBreaker, NoHealthyProvider
from app.platform.voice.runtime.providers import ProviderRouter

DEFAULT_MONTHLY_BUDGET_MINOR: Final[int] = 50_000
DEFAULT_CALL_CEILING_SECONDS: Final[int] = 900
DEFAULT_MINUTE_PRICE_MINOR: Final[int] = 6


class BudgetExceeded(ValidationError):
    """The shop cannot afford this call, and saying so now is cheaper than saying it later."""


@dataclass(slots=True)
class TenantBudget:
    monthly_minor: int = DEFAULT_MONTHLY_BUDGET_MINOR
    call_ceiling_seconds: int = DEFAULT_CALL_CEILING_SECONDS
    minute_price_minor: int = DEFAULT_MINUTE_PRICE_MINOR


@dataclass(slots=True)
class CostGuard:
    """A hard ceiling per shop, spent in audio seconds, checked before audio starts."""

    budgets: dict[uuid.UUID, TenantBudget] = field(default_factory=dict)
    spent_minor: dict[uuid.UUID, int] = field(default_factory=dict)
    spent_seconds: dict[uuid.UUID, int] = field(default_factory=dict)
    period_start: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def budget(self, tenant_id: uuid.UUID) -> TenantBudget:
        return self.budgets.setdefault(tenant_id, TenantBudget())

    def remaining_minor(self, tenant_id: uuid.UUID) -> int:
        return self.budget(tenant_id).monthly_minor - self.spent_minor.get(tenant_id, 0)

    def authorize_call(self, tenant_id: uuid.UUID, *, estimated_seconds: int) -> int:
        """Return the ceiling this call may spend, or refuse before any audio is billed."""
        budget = self.budget(tenant_id)
        if estimated_seconds <= 0:
            raise ValidationError("an estimated call length must be positive")
        ceiling = min(estimated_seconds, budget.call_ceiling_seconds)
        projected = -(-ceiling * budget.minute_price_minor // 60)
        if projected > self.remaining_minor(tenant_id):
            raise BudgetExceeded(
                f"this shop has {self.remaining_minor(tenant_id)} minor units left this period"
            )
        return ceiling

    def record(self, tenant_id: uuid.UUID, *, seconds: int) -> None:
        budget = self.budget(tenant_id)
        self.spent_seconds[tenant_id] = self.spent_seconds.get(tenant_id, 0) + seconds
        self.spent_minor[tenant_id] = self.spent_minor.get(tenant_id, 0) + (
            -(-seconds * budget.minute_price_minor // 60)
        )


class ScaleAction(enum.StrEnum):
    SCALE_UP = "scale_up"
    HOLD = "hold"
    SHED = "shed"


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """What a realtime worker can see about itself, in the units autoscaling cares about."""

    active_sessions: int
    capacity: int
    p95_turn_ms: int
    failure_rate: float

    def utilization(self) -> float:
        return 0.0 if self.capacity <= 0 else self.active_sessions / self.capacity


def autoscale_action(
    snapshot: RuntimeSnapshot,
    *,
    scale_at: float = 0.75,
    shed_at: float = 1.0,
    slow_turn_ms: int = 2_500,
    bad_failure_rate: float = 0.1,
) -> ScaleAction:
    """One decision, from measured pressure: too full sheds new calls before it drops live ones."""
    if snapshot.capacity <= 0:
        # A worker that cannot state its capacity is not idle, it is unmeasurable. Treat it as
        # pressure rather than as free room, or a broken worker looks like the calmest one.
        return ScaleAction.SCALE_UP
    if snapshot.utilization() >= shed_at:
        return ScaleAction.SHED
    if (
        snapshot.utilization() >= scale_at
        or snapshot.p95_turn_ms >= slow_turn_ms
        or snapshot.failure_rate >= bad_failure_rate
    ):
        return ScaleAction.SCALE_UP
    return ScaleAction.HOLD


@dataclass(frozen=True, slots=True)
class TurnSample:
    turn_ms: int
    completed: bool
    dropped_results: int = 0
    interrupted: bool = False


@dataclass(frozen=True, slots=True)
class QualityReport:
    samples: int
    p50_turn_ms: int
    p95_turn_ms: int
    completion_rate: float
    drop_rate: float
    passed: bool
    reasons: tuple[str, ...]


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def evaluate_quality(
    samples: Iterable[TurnSample],
    *,
    max_p95_ms: int = 2_500,
    min_completion_rate: float = 0.95,
    max_drop_rate: float = 0.05,
) -> QualityReport:
    """Score the turns, and fail the run rather than reporting a green number nobody checked."""
    rows = list(samples)
    if not rows:
        return QualityReport(
            samples=0,
            p50_turn_ms=0,
            p95_turn_ms=0,
            completion_rate=0.0,
            drop_rate=0.0,
            passed=False,
            reasons=("no turns to evaluate",),
        )
    latencies = [row.turn_ms for row in rows]
    completion = sum(1 for row in rows if row.completed) / len(rows)
    dropped = sum(row.dropped_results for row in rows)
    calls = sum(max(1, row.dropped_results) for row in rows)
    drop_rate = dropped / calls
    p95 = _percentile(latencies, 0.95)

    reasons: list[str] = []
    if p95 > max_p95_ms:
        reasons.append(f"p95 turn {p95}ms over {max_p95_ms}ms")
    if completion < min_completion_rate:
        reasons.append(f"completion {completion:.0%} under {min_completion_rate:.0%}")
    if drop_rate > max_drop_rate:
        reasons.append(f"dropped results {drop_rate:.0%} over {max_drop_rate:.0%}")

    return QualityReport(
        samples=len(rows),
        p50_turn_ms=_percentile(latencies, 0.50),
        p95_turn_ms=p95,
        completion_rate=completion,
        drop_rate=drop_rate,
        passed=not reasons,
        reasons=tuple(reasons),
    )


@dataclass(slots=True)
class ResilientChooser:
    """Pick a provider through the router, and let the breaker decide who is even a candidate."""

    router: ProviderRouter
    breaker: CircuitBreaker

    def choose(self, *, path, language: str, prefer: str | None = None):
        entry = self.router.choose(
            path=path,
            language=language,
            prefer=prefer,
            unavailable=self.breaker.unavailable(),
        )
        if not self.breaker.allow(entry.name):
            raise NoHealthyProvider(f"{entry.name} is open and no other provider serves {path}")
        return entry

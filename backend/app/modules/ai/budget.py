"""AI budget management — monthly spending caps, reservations, and alerts.

Implements the financial guardrails for AI usage (§42):
- Hard monthly budget cap per tenant and per agent
- Pre-flight budget reservation with bounded advisory lock
- Daily cost cap enforcement (defaults to monthly_cap / 30)
- Spend alerts when approaching thresholds (50%, 80%, 90%, 100%)
- Exact decimal cost estimation for input/output tokens
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import RateLimitExceededError
from app.modules.ai.models import AIBudgetReservation, AIUsage, BudgetPolicy

logger = logging.getLogger(__name__)

# Monthly AI spend cap per tenant (USD, estimated) — the fallback when a tenant
# has no BudgetPolicy row. Read from settings so a deployment can raise or lower
# it without a code change; the default keeps the previous behaviour exactly.
MONTHLY_BUDGET_CAP = 50.0

# §42: the thresholds an operator must hear about BEFORE the cap bites.
# `BudgetPolicy.warning_threshold` existed on the model and was never read, so
# no alert was raised at any percentage — a tenant could hit the hard cap with
# no warning at all.
BUDGET_ALERT_THRESHOLDS: tuple[int, ...] = (50, 80, 90, 100)

# Flat per-token estimates, used when a tenant has no per-model pricing row.
# Both DIRECTIONS are priced: charging only output under-counts real spend,
# because the prompt (history + knowledge + tools) is usually the larger half
# of the tokens on a conversational turn.
_COST_PER_INPUT_TOKEN = Decimal("0.0000005")  # $0.50 / 1M tokens
_COST_PER_OUTPUT_TOKEN = Decimal("0.000002")  # $2.00 / 1M tokens

# Token floor charged per image in the vision paths (embed_vision/rerank_vision).
# The providers bill per image with an opaque internal count; the budget cap
# only needs a positive, roughly-honest estimate to bite.
_IMAGE_TOKEN_FLOOR = 258

# How long a reservation is held before a sweep may reclaim it. A run that
# crashes between reserve and settle must not hold budget forever.
RESERVATION_TTL_MINUTES = 30

# The per-tenant reservation lock is taken as a TRY-lock with a bounded wait —
# the same contract as the conversation lease. The lock is transaction-scoped,
# so it lives until the CALLER's transaction ends — i.e. across the provider
# HTTP call. A blocking pg_advisory_xact_lock here would hang a second worker
# for as long as the first run's LLM call takes (unbounded, no lock_timeout);
# the bounded expiry converts that hang into a retryable 429 and the event
# goes back to the queue instead of stalling the worker pool.
BUDGET_LOCK_WAIT_SECONDS = 5.0
_BUDGET_LOCK_POLL_SECONDS = 0.05

_CENT = Decimal("0.00000001")


def _tenant_budget_lock_id(tenant_id: UUID) -> int:
    """Deterministic 63-bit advisory-lock key for a tenant's budget."""
    return int.from_bytes(tenant_id.bytes[:8], byteorder="big", signed=False) & 0x7FFFFFFFFFFFFFFF


def estimate_cost(tokens_in: int, tokens_out: int) -> Decimal:
    """Exact cost of a call, in Decimal.

    Returns Decimal rather than float on purpose: the column is Numeric(18,8)
    and float arithmetic would reintroduce exactly the rounding the column was
    widened to avoid (a float cost of 0.001 was being stored as 0.00, so the
    monthly total was always zero and the hard cap was unenforceable).
    """
    total = (
        Decimal(max(int(tokens_in or 0), 0)) * _COST_PER_INPUT_TOKEN
        + Decimal(max(int(tokens_out or 0), 0)) * _COST_PER_OUTPUT_TOKEN
    )
    return total.quantize(_CENT)


async def _month_spend(
    session: AsyncSession, tenant_id: UUID, *, agent_id: UUID | None = None
) -> Decimal:
    """Sum of ai_usage cost for the current calendar month, for this tenant.

    With ``agent_id`` the sum is THAT agent's spend only — the measurement
    scope of an agent-specific cap (see ``_resolve_cap``'s third element)."""
    month_start = datetime.now(UTC).date().replace(day=1)
    conditions = [
        AIUsage.tenant_id == tenant_id,
        AIUsage.period_date >= month_start,
    ]
    if agent_id is not None:
        conditions.append(AIUsage.agent_id == agent_id)
    total = (
        await session.execute(select(func.coalesce(func.sum(AIUsage.cost), 0)).where(*conditions))
    ).scalar_one()
    return Decimal(total or 0)


async def _day_spend(
    session: AsyncSession, tenant_id: UUID, *, agent_id: UUID | None = None
) -> Decimal:
    """§42: sum of ai_usage cost for today (UTC), for this tenant."""
    today = datetime.now(UTC).date()
    conditions = [
        AIUsage.tenant_id == tenant_id,
        AIUsage.period_date == today,
    ]
    if agent_id is not None:
        conditions.append(AIUsage.agent_id == agent_id)
    total = (
        await session.execute(select(func.coalesce(func.sum(AIUsage.cost), 0)).where(*conditions))
    ).scalar_one()
    return Decimal(total or 0)


def _daily_cap(monthly_cap: Decimal) -> Decimal:
    """§42: the daily cost cap — defaults to monthly_cap / 30."""
    if monthly_cap <= 0:
        return Decimal(0)
    return (monthly_cap / Decimal(30)).quantize(Decimal("0.01"))


async def _reserved_spend(
    session: AsyncSession, tenant_id: UUID, *, agent_id: UUID | None = None
) -> Decimal:
    """Budget already committed to in-flight runs (not yet settled)."""
    conditions = [
        AIBudgetReservation.tenant_id == tenant_id,
        AIBudgetReservation.status == "active",
        AIBudgetReservation.expires_at > datetime.now(UTC),
    ]
    if agent_id is not None:
        conditions.append(AIBudgetReservation.agent_id == agent_id)
    total = (
        await session.execute(
            select(func.coalesce(func.sum(AIBudgetReservation.amount), 0)).where(*conditions)
        )
    ).scalar_one()
    return Decimal(total or 0)


async def expire_stale_reservations(
    session: AsyncSession, tenant_id: UUID, *, now: datetime | None = None
) -> int:
    """Release reservations held by runs that never settled (crash/restart)."""
    from sqlalchemy import update

    result = await session.execute(
        update(AIBudgetReservation)
        .where(
            AIBudgetReservation.tenant_id == tenant_id,
            AIBudgetReservation.status == "active",
            AIBudgetReservation.expires_at <= (now or datetime.now(UTC)),
        )
        .values(status="expired")
    )
    return result.rowcount or 0


async def settle_reservation(
    session: AsyncSession,
    reservation_id: UUID | None,
    *,
    now: datetime | None = None,
) -> None:
    """Mark a reservation settled once its run has finished (success or not)."""
    if reservation_id is None:
        return
    from sqlalchemy import update

    await session.execute(
        update(AIBudgetReservation)
        .where(
            AIBudgetReservation.id == reservation_id,
            AIBudgetReservation.status == "active",
        )
        .values(status="settled", settled_at=now or datetime.now(UTC))
    )


def _default_cap() -> Decimal:
    """The deployment's default monthly cap when a tenant has no policy row.

    Read from settings so the ceiling can be changed without a deploy; the
    setting's default preserves the previous constant exactly.
    """
    configured = getattr(get_settings(), "ai_monthly_budget_cap_default", MONTHLY_BUDGET_CAP)
    try:
        return Decimal(str(configured))
    except (ArithmeticError, ValueError):
        return Decimal(str(MONTHLY_BUDGET_CAP))


def _resolve_cap(policies: list, agent_id: UUID | None) -> tuple[Decimal, str, bool]:
    """Agent-scoped policy wins over tenant-scoped; falls back to the default.

    "No policy" must never mean "no limit": a tenant without a BudgetPolicy row
    still gets the deployment default, so a misconfigured (or never-configured)
    tenant cannot spend without bound.
    """
    for scope_policy in policies:
        if scope_policy.agent_id is not None and scope_policy.agent_id != agent_id:
            continue
        agent_scoped = scope_policy.agent_id is not None
        return Decimal(scope_policy.hard_cap), scope_policy.on_exceed, agent_scoped
    return _default_cap(), "block", False


async def _raise_budget_alerts(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    cap: Decimal,
    committed: Decimal,
) -> None:
    """Notify the tenant's owners when spend crosses a §42 threshold."""
    if cap <= 0:
        return
    ratio = (committed / cap) * Decimal(100)
    crossed = [threshold for threshold in BUDGET_ALERT_THRESHOLDS if ratio >= threshold]
    if not crossed:
        return
    threshold = max(crossed)

    from app.modules.notifications.service import NotificationService

    owner_ids = (
        (
            await session.execute(
                text(
                    "SELECT tu.user_id FROM tenant_users tu "
                    "JOIN roles r ON r.id = tu.role_id "
                    "WHERE tu.tenant_id = :tenant_id AND r.code = 'owner'"
                ),
                {"tenant_id": str(tenant_id)},
            )
        )
        .scalars()
        .all()
    )
    if not owner_ids:
        return

    period_key = datetime.now(UTC).strftime("%Y-%m")
    for owner_id in owner_ids:
        await NotificationService.create(
            session,
            tenant_id,
            owner_id,
            kind="ai_budget_threshold",
            title="AI budget threshold reached",
            body=(f"AI spend has reached {ratio:.0f}% of the monthly cap ({committed} of {cap})."),
            payload={
                "threshold": threshold,
                "ratio": str(ratio.quantize(Decimal("0.01"))),
                "cap": str(cap),
                "committed": str(committed),
                "period": period_key,
            },
            dedup_key=f"ai_budget:{tenant_id}:{period_key}:{threshold}",
        )


class AIBudgetFallbackRequested(Exception):
    """§42: the cap is exhausted and the policy says DOWNGRADE, not die.

    Raised instead of RateLimitExceededError when BudgetPolicy.on_exceed ==
    "fallback". The runner catches it and retries the same step on the
    "fallback" alias; if the fallback alias is the one that just failed it
    hands the conversation to a human instead of looping.
    """

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class AIBudgetExhaustedError(RateLimitExceededError):
    """§42: a spend ceiling was reached — monthly cap, daily cap or fairness."""

    code = "ai_budget_exhausted"
    retryable = False


def _on_budget_exceeded(on_exceed: str, message: str, *, details: dict) -> None:
    """§42 mode dispatch when committed spend crosses the cap."""
    if on_exceed == "fallback":
        raise AIBudgetFallbackRequested(message, details=details)
    if on_exceed == "warn":
        logger.warning("ai.budget_exceeded_warn %s %s", message, details)
        return
    raise AIBudgetExhaustedError(message, details=details)


async def reserve_budget(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    agent_id: UUID | None = None,
    estimated_cost: Decimal | float = 0,
) -> UUID | None:
    """Spec §42 reserve half: take budget BEFORE the provider call."""
    from sqlalchemy import select as sa_select

    lock_id = _tenant_budget_lock_id(tenant_id)
    deadline = time.monotonic() + BUDGET_LOCK_WAIT_SECONDS
    while True:
        acquired = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id) AS acquired"),
                {"lock_id": lock_id},
            )
        ).scalar()
        if acquired:
            break
        if time.monotonic() >= deadline:
            raise RateLimitExceededError(
                "AI budget reservation timed out waiting for another run of "
                "this tenant to release the budget lock"
            )
        await asyncio.sleep(_BUDGET_LOCK_POLL_SECONDS)

    await expire_stale_reservations(session, tenant_id)

    policies = (
        (
            await session.execute(
                sa_select(BudgetPolicy)
                .where(
                    BudgetPolicy.tenant_id == tenant_id,
                    BudgetPolicy.period == "monthly",
                )
                .order_by(BudgetPolicy.agent_id.is_(None))
            )
        )
        .scalars()
        .all()
    )
    cap, on_exceed, agent_scoped = _resolve_cap(list(policies), agent_id)

    if cap <= 0:
        return None

    scope_agent_id = agent_id if agent_scoped else None
    spend = await _month_spend(session, tenant_id, agent_id=scope_agent_id)
    reserved = await _reserved_spend(session, tenant_id, agent_id=scope_agent_id)
    estimate = Decimal(str(estimated_cost or 0))
    committed = spend + reserved

    await _raise_budget_alerts(session, tenant_id, cap=cap, committed=committed)

    day_spend = await _day_spend(session, tenant_id, agent_id=scope_agent_id)
    daily_cap = _daily_cap(cap)
    if committed + estimate >= cap:
        _on_budget_exceeded(
            on_exceed,
            "monthly AI budget exceeded",
            details={
                "spend": str(spend),
                "reserved": str(reserved),
                "cap": str(cap),
            },
        )

    if daily_cap > 0 and day_spend + estimate >= daily_cap:
        _on_budget_exceeded(
            on_exceed,
            "daily AI budget exceeded",
            details={
                "day_spend": str(day_spend),
                "daily_cap": str(daily_cap),
                "estimate": str(estimate),
            },
        )

    reservation = AIBudgetReservation(
        tenant_id=tenant_id,
        agent_id=agent_id,
        amount=estimate,
        status="active",
        expires_at=datetime.now(UTC) + timedelta(minutes=RESERVATION_TTL_MINUTES),
    )
    session.add(reservation)
    await session.flush()
    return reservation.id


async def enforce_budget(
    session: AsyncSession, tenant_id: UUID, *, agent_id: UUID | None = None
) -> dict:
    """Read-only budget view (spend, cap, ratio) without taking a reservation."""
    from sqlalchemy import select as sa_select

    policies = (
        (
            await session.execute(
                sa_select(BudgetPolicy)
                .where(
                    BudgetPolicy.tenant_id == tenant_id,
                    BudgetPolicy.period == "monthly",
                )
                .order_by(BudgetPolicy.agent_id.is_(None))
            )
        )
        .scalars()
        .all()
    )
    cap, on_exceed, agent_scoped = _resolve_cap(list(policies), agent_id)

    spend = await _month_spend(session, tenant_id, agent_id=agent_id if agent_scoped else None)
    ratio = float(spend / cap * 100) if cap > 0 else 0.0
    if spend >= cap and on_exceed == "block":
        raise AIBudgetExhaustedError(
            "monthly AI budget exceeded",
            details={"spend": str(spend), "cap": str(cap)},
        )
    return {
        "spend": str(spend),
        "cap": str(cap),
        "ratio": ratio,
        "on_exceed": on_exceed,
    }

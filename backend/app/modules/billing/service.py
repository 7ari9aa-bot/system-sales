"""BILLING service — plans, subscriptions, entitlements, usage metering.

Gating rule: features with entitlements are enforced at the API/service layer
(require_entitlement); Stripe integration activates once keys exist — until
then subscriptions run in trial/manual mode without blocking the core.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    NotFoundError,
    RateLimitExceededError,
    ValidationError,
)
from app.modules.billing.models import (
    Entitlement,
    Invoice,
    Plan,
    Subscription,
    UsageRecord,
)

# Capability (what a caller asks for) -> plan feature (what the plan stores).
#
# These are DIFFERENT namespaces and must be mapped explicitly. `can()` used to
# pass the capability straight through as the feature name, so a lookup for
# `Entitlement.feature == "CanAddUser"` never matched a plan row that stores
# `max_users` — every capability check silently returned True. Adding a seat
# limit to a plan had no effect at all.
#
# Only the features the seeded plans actually define are mapped. A capability
# with no mapping is intentionally unrestricted (the documented
# "unknown capabilities are allowed by default" rule).
_CAPABILITY_FEATURE: dict[str, str] = {
    "CanAddUser": "max_users",
    "CanUseAI": "ai_agents",
    # `channels` is an ALLOWLIST of channel names, not a numeric limit, so it
    # cannot go through check_entitlement (which compares a limit against a
    # usage counter). Use EntitlementService.ensure_channel_allowed instead.
    "CanCreateChannel": "channels",
}

# Features whose "usage" is a live row count, not a period accumulator.
#
# Nothing writes a UsageRecord for seats: seats are a state, not something you
# consume per period. Reading the counter reported 0 forever, so a plan limit of
# 3 users could never be reached. Count the memberships instead.
_DERIVED_USAGE: dict[str, str] = {
    "max_users": "tenant_users",
    "seats": "tenant_users",
}


class BillingService:
    @staticmethod
    async def start_trial(
        session: AsyncSession, tenant_id: uuid.UUID, *, plan_code: str = "starter", days: int = 14
    ) -> Subscription:
        plan = (
            await session.execute(select(Plan).where(Plan.code == plan_code))
        ).scalar_one_or_none()
        if plan is None:
            raise NotFoundError(f"unknown plan: {plan_code}")
        existing = (
            await session.execute(
                select(Subscription).where(
                    Subscription.tenant_id == tenant_id,
                    Subscription.status.in_(["trialing", "active", "past_due"]),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValidationError("tenant already has an active subscription")
        subscription = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status="trialing",
            current_period_start=datetime.now(UTC),
            current_period_end=datetime.now(UTC) + timedelta(days=days),
        )
        session.add(subscription)
        await session.flush()
        # copy plan features as entitlements (None limit = unlimited flag off)
        features = plan.features or {}
        for feature, limit in features.items():
            if feature in ("channels", "custom"):
                continue
            session.add(
                Entitlement(
                    tenant_id=tenant_id,
                    subscription_id=subscription.id,
                    feature=feature,
                    limit_value=int(limit) if isinstance(limit, int) else None,
                    is_unlimited=limit is None,
                )
            )
        await session.flush()
        return subscription

    @staticmethod
    async def get_subscription(session: AsyncSession, tenant_id: uuid.UUID) -> Subscription | None:
        return (
            await session.execute(
                select(Subscription)
                .where(
                    Subscription.tenant_id == tenant_id,
                    Subscription.status.in_(["trialing", "active", "past_due"]),
                )
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def check_entitlement(
        session: AsyncSession, tenant_id: uuid.UUID, feature: str, *, requested: int = 1
    ) -> bool:
        """True when usage within limit; raises RateLimitExceededError otherwise.
        Features without an entitlement row are unrestricted by default."""
        subscription = await BillingService.get_subscription(session, tenant_id)
        if subscription is None:
            return True
        entitlement = (
            await session.execute(
                select(Entitlement).where(
                    Entitlement.tenant_id == tenant_id,
                    Entitlement.subscription_id == subscription.id,
                    Entitlement.feature == feature,
                )
            )
        ).scalar_one_or_none()
        if entitlement is None or entitlement.is_unlimited or entitlement.limit_value is None:
            return True
        used = await BillingService.used_this_period(session, tenant_id, feature)
        if used + requested > entitlement.limit_value:
            raise RateLimitExceededError(
                f"plan limit reached for {feature}",
                details={"used": used, "limit": entitlement.limit_value},
            )
        return True

    @staticmethod
    async def used_this_period(session: AsyncSession, tenant_id: uuid.UUID, feature: str) -> int:
        derived = _DERIVED_USAGE.get(feature)
        if derived == "tenant_users":
            # Lazy import: identity.models is imported by the same routers that
            # import this module.
            from app.modules.identity.models import TenantUser

            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(TenantUser)
                        .where(TenantUser.tenant_id == tenant_id)
                    )
                ).scalar_one()
                or 0
            )

        subscription = await BillingService.get_subscription(session, tenant_id)
        start = subscription.current_period_start if subscription else None
        stmt = select(UsageRecord.quantity).where(
            UsageRecord.tenant_id == tenant_id, UsageRecord.feature == feature
        )
        if start is not None:
            stmt = stmt.where(UsageRecord.period_date >= start.date())
        rows = (await session.execute(stmt)).scalars().all()
        return int(sum(rows))

    @staticmethod
    async def record_usage(
        session: AsyncSession, tenant_id: uuid.UUID, *, feature: str, quantity: Decimal
    ) -> None:
        """Append one metering row.

        `quantity` is Decimal, not float: `UsageRecord.quantity` is
        Numeric(14,2), and handing a binary float to a Numeric column is how a
        total drifts by a cent.
        """
        session.add(
            UsageRecord(
                tenant_id=tenant_id,
                feature=feature,
                quantity=quantity,
                period_date=datetime.now(UTC).date(),
            )
        )
        await session.flush()


class EntitlementService:
    """Spec §165: centralized CanX enforcement — one place, not per-module.

    Flow: Auth → Tenant → Permission → Entitlement → Domain rule.
    """

    @staticmethod
    async def plan_channels(session: AsyncSession, tenant_id: uuid.UUID):
        """The plan's `channels` value: a list of allowed names, or "*".

        Returns None when there is no active subscription or the plan does not
        mention channels — meaning "unrestricted".
        """
        subscription = await BillingService.get_subscription(session, tenant_id)
        if subscription is None:
            return None
        plan = (
            await session.execute(select(Plan).where(Plan.id == subscription.plan_id))
        ).scalar_one_or_none()
        if plan is None:
            return None
        return (plan.features or {}).get("channels")

    @staticmethod
    async def channel_allowed(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str | None
    ) -> bool:
        """Whether the plan includes `channel` (None = "any channel at all").

        `channels` is stored as an allowlist of names (starter: whatsapp +
        webchat, pro: five channels, enterprise: "*"), so it cannot be expressed
        as the numeric limit `check_entitlement` compares against a usage
        counter — which is why it was skipped entirely and the channel gate was
        decorative.
        """
        allowed = await EntitlementService.plan_channels(session, tenant_id)
        if allowed is None or allowed == "*":
            return True
        if not isinstance(allowed, list):
            # Unrecognised shape: do not block on a value we cannot read.
            return True
        if channel is None:
            return len(allowed) > 0
        return channel in allowed

    @staticmethod
    async def ensure_channel_allowed(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str | None
    ) -> None:
        if not await EntitlementService.channel_allowed(session, tenant_id, channel):
            raise RateLimitExceededError(
                "plan does not include this channel",
                details={"channel": channel},
            )

    @staticmethod
    async def can(session: AsyncSession, tenant_id: uuid.UUID, capability: str) -> bool:
        """Canonical capability checks. Unknown capabilities are allowed by
        default; known ones consult plan entitlements + tenant status.

        This is a PREDICATE and must never raise. BillingService.check_entitlement
        raises RateLimitExceededError when a limit is exceeded, so it is caught
        here: a caller writing `if not await can(...)` would otherwise crash
        instead of taking the "not allowed" branch. Use ensure() when the error
        is what you want.
        """
        from app.core.errors import RateLimitExceededError
        from app.modules.identity.models import Tenant

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None or not tenant.is_active:
            return False

        if capability in (
            "CanUseAI",
            "CanSendCampaign",
            "CanUseVoice",
            "CanUseAPI",
            "CanCreateChannel",
            "CanAddUser",
        ):
            feature = _CAPABILITY_FEATURE.get(capability)
            if feature is None:
                # Unmapped capability -> unrestricted. Documented default, but
                # note this is also how the seat limit silently passed for so
                # long: the capability was never in the map at all, so
                # `Entitlement.feature == "CanAddUser"` matched nothing.
                return True
            if feature == "channels":
                # An allowlist, not a numeric limit. "Can this tenant add a
                # channel" = does the plan list any channel.
                return await EntitlementService.channel_allowed(session, tenant_id, None)
            try:
                return await BillingService.check_entitlement(
                    session, tenant_id, feature, requested=1
                )
            except RateLimitExceededError:
                return False
        return True

    @staticmethod
    async def ensure(session: AsyncSession, tenant_id: uuid.UUID, capability: str) -> None:
        from app.core.errors import RateLimitExceededError

        if not await EntitlementService.can(session, tenant_id, capability):
            raise RateLimitExceededError(
                f"plan does not allow: {capability}",
                details={"capability": capability},
            )


# ------------------------------------------------------- period metering ---

#: Canonical feature name for AI token usage. `UsageRecord` documents
#: `ai_tokens` as its AI feature, and the AI runtime's own rollup is folded into
#: the same key so a tenant sees ONE number for "AI tokens this period" rather
#: than two rows meaning the same thing.
_AI_TOKENS_FEATURE = "ai_tokens"

#: Money is never a float (ADR-001). Numeric(14,2) columns are quantized with an
#: explicit mode; `round()` would route the value through a binary float first.
_MONEY_QUANTUM = Decimal("0.01")


def _as_decimal(value: object) -> Decimal:
    """Exact Decimal from a Numeric column — never `float()`.

    asyncpg already returns Decimal for Numeric; this only normalises None and
    the occasional integer. `Decimal(str(x))` rather than `Decimal(x)` so a
    stray float is read as the decimal it was printed as, not its exact binary
    expansion.
    """
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize_money(value: Decimal) -> Decimal:
    """Exact 2dp rounding for a MONEY column.

    ROUND_HALF_UP, not Python's default ROUND_HALF_EVEN: a half-cent on a
    customer-facing invoice rounds away from zero, which is what an invoice
    reader expects. Half-even can round a total DOWN by a cent.
    """
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _validate_period(period_start: date, period_end: date) -> None:
    """Reject an empty or inverted period BEFORE any database access.

    A bad range must be a 400, not a zero-filled invoice that silently bills
    nobody.
    """
    if period_start >= period_end:
        raise ValidationError(
            "period_start must be before period_end",
            details={
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )


#: Tag for the two-argument advisory-lock space used by period closes.
#:
#: The two-argument form `pg_advisory_xact_lock(int, int)` lives in a lock space
#: DISJOINT from the one-argument `bigint` form, so a billing close can never
#: block on — or be blocked by — the conversation lease in app/core/lease.py.
_BILLING_CLOSE_LOCK_NAMESPACE = 531


def _tenant_lock_key(tenant_id: uuid.UUID) -> int:
    """31 bits of tenant id, inside int4 range, for the 2-arg advisory lock."""
    return uuid.UUID(str(tenant_id)).int & 0x7FFFFFFF


class PeriodUsage(NamedTuple):
    """One tenant's metered usage over one period.

    `features` holds per-feature QUANTITY totals (tokens, messages, orders).
    `ai_cost` is money and is deliberately kept out of `features`: summing a
    currency amount into a map of counts is how units get silently mixed.
    """

    features: dict[str, Decimal]
    ai_cost: Decimal


class BillingSnapshotService:
    """Spec §53–54: period metering + IMMUTABLE period snapshots.

    A snapshot is a correctness artefact, not a cache. Once a period is closed
    its totals are frozen forever: a usage record that arrives late for that
    period must not move the invoice, which is the entire point of the spec
    item. Re-reading a snapshot never re-aggregates.

    Two rules have to hold, and they need different mechanisms:

    **(a) A period is closed at most once** — enforced by
    ``uq_invoices_tenant_period``, a UNIQUE constraint on
    (tenant_id, period_start, period_end). This is a declarative guarantee that
    holds against any writer.

    **(b) Closed periods never OVERLAP** — ``[Aug 1, Sep 1)`` then
    ``[Aug 15, Sep 15)`` would bill the overlapping days twice, and the unique
    constraint above does not stop it (the triples differ).

    (b) is enforced by ``pg_advisory_xact_lock`` taken BEFORE the check, which
    serialises every close for a tenant, followed by an overlap query. The lock
    is what makes it correct: the check alone is a check-then-insert race, and
    two concurrent overlapping closes would both read "no overlap" and both
    insert — the exact defect this fix is for.

    **Why a lock rather than an ``EXCLUDE USING gist`` constraint.** The
    declarative form needs ``btree_gist`` for ``tenant_id WITH =``, and that is
    a contrib extension. CI and local both run ``pgvector/pgvector:pg17``, which
    is ``FROM postgres:17-bookworm`` — and that Dockerfile installs only
    ``postgresql-17``, never ``postgresql-contrib``. Whether the module is
    present could not be confirmed from here, and a migration that fails at
    ``alembic upgrade head`` blocks the entire deploy, so the guard uses core
    PostgreSQL only. ``pg_advisory_xact_lock`` is the same primitive
    ``app/core/lease.py`` already relies on for ADR-006, and it is
    transaction-scoped, so it cannot leak.

    This is sound because ``close_period`` is the ONLY writer of ``Invoice``:
    the lock therefore covers every writer that exists. A future writer that
    inserts invoices directly (a Stripe webhook, say — ``Invoice.provider``
    exists for exactly that) must take the same lock; that is recorded here as
    the known limit of this mechanism.

    A second close is REFUSED, not idempotent-return. Returning the existing
    snapshot would need a caught IntegrityError plus a re-read, and it could not
    distinguish "already closed, same inputs" from "an operator trying to
    recompute with corrected data" — which is precisely the recompute path
    immutability exists to forbid. There is deliberately NO ``recompute_period``.

    Nothing in this class ever UPDATEs a snapshot row.
    """

    @staticmethod
    async def aggregate_period(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> PeriodUsage:
        """Live per-feature totals for [period_start, period_end).

        Half-open — `period_end` is exclusive — so consecutive periods never
        double-count the boundary day.

        Reads two sources, because there are two:

        * `usage_records` — billing's own metering ledger (manual `POST
          /billing/usage` writes here).
        * `ai_usage` — the REAL source of AI usage. `ai.usage.record_usage` is
          called from the model runtime and NOTHING ever writes a UsageRecord
          for AI, so metering only `usage_records` would report zero AI tokens
          for every tenant, forever.

        `ai_usage` is read with SQL rather than `app.modules.ai.models` because
        `ai` already imports `billing.service` (the entitlement gate). Importing
        its models here would close a NEW `ai <-> billing` cycle AND push the
        cross-module ratchet in tests/test_module_boundaries.py from 82 to 83 —
        both hard failures. This is the same trade
        `ai.gateway._raise_budget_alerts` makes for its owner lookup, and the
        query runs under the same tenant GUC as the ORM version would.
        """
        _validate_period(period_start, period_end)

        features: dict[str, Decimal] = {}
        rows = (
            await session.execute(
                select(UsageRecord.feature, func.sum(UsageRecord.quantity))
                .where(
                    UsageRecord.tenant_id == tenant_id,
                    UsageRecord.period_date >= period_start,
                    UsageRecord.period_date < period_end,
                )
                .group_by(UsageRecord.feature)
            )
        ).all()
        for feature, quantity in rows:
            features[feature] = _as_decimal(quantity)

        ai_tokens, ai_cost = await BillingSnapshotService._ai_usage(
            session, tenant_id, period_start=period_start, period_end=period_end
        )
        if ai_tokens:
            features[_AI_TOKENS_FEATURE] = (
                features.get(_AI_TOKENS_FEATURE, Decimal(0)) + ai_tokens
            )

        return PeriodUsage(features=features, ai_cost=ai_cost)

    @staticmethod
    async def _ai_usage(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> tuple[Decimal, Decimal]:
        """(tokens_in + tokens_out, cost) for the period. See aggregate_period."""
        row = (
            await session.execute(
                text(
                    "SELECT coalesce(sum(tokens_in + tokens_out), 0) AS tokens, "
                    "coalesce(sum(cost), 0) AS cost "
                    "FROM ai_usage "
                    "WHERE tenant_id = :tenant_id "
                    "AND period_date >= :period_start "
                    "AND period_date < :period_end"
                ),
                {
                    # The UUID OBJECT, not str(tenant_id): a `uuid` column wants
                    # asyncpg's native uuid codec input, and handing it the object
                    # removes any dependence on text->uuid coercion that could
                    # only ever surface at runtime. (str() is used against uuid
                    # columns elsewhere in this codebase and appears to work, but
                    # it is not worth carrying an unverifiable assumption in a
                    # query nothing exercises outside CI.)
                    "tenant_id": tenant_id,
                    "period_start": period_start,
                    "period_end": period_end,
                },
            )
        ).one()
        return _as_decimal(row.tokens), _as_decimal(row.cost)

    @staticmethod
    async def _acquire_close_lock(session: AsyncSession, tenant_id: uuid.UUID) -> None:
        """Serialise period closes for one tenant for the rest of the transaction.

        Taken BEFORE the duplicate/overlap checks, which is the whole point: it
        turns those two check-then-insert races into a critical section. The
        lock is transaction-scoped and released at COMMIT/ROLLBACK, so it cannot
        leak on an error path.

        Per-tenant, not global: closing tenant A's period must not block tenant
        B's. Two tenants whose ids collide in the low 31 bits merely serialise,
        which costs throughput and never correctness.
        """
        await session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "CAST(:namespace AS integer), CAST(:tenant AS integer))"
            ),
            {
                "namespace": _BILLING_CLOSE_LOCK_NAMESPACE,
                "tenant": _tenant_lock_key(tenant_id),
            },
        )

    @staticmethod
    async def find_snapshot(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> Invoice | None:
        """The frozen snapshot for a period, or None. Always tenant-scoped."""
        return (
            await session.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.period_start == period_start,
                    Invoice.period_end == period_end,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def find_overlapping_snapshot(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> Invoice | None:
        """Any closed period that shares at least one day with this one.

        Half-open interval overlap: ``existing.start < new.end AND
        existing.end > new.start``. Touching periods (``[Aug 1, Sep 1)`` and
        ``[Sep 1, Oct 1)``) do NOT overlap — the boundary day belongs to exactly
        one of them.

        Rows with a NULL period are skipped: they predate period snapshots and
        cannot overlap anything.

        Only correct when called inside the lock — see `_acquire_close_lock`.
        """
        return (
            (
                await session.execute(
                    select(Invoice)
                    .where(
                        Invoice.tenant_id == tenant_id,
                        Invoice.period_start.is_not(None),
                        Invoice.period_end.is_not(None),
                        Invoice.period_start < period_end,
                        Invoice.period_end > period_start,
                    )
                    .order_by(Invoice.period_start)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

    @staticmethod
    async def get_snapshot(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> Invoice:
        """Read a closed period. Never re-aggregates — that is the guarantee."""
        invoice = await BillingSnapshotService.find_snapshot(
            session, tenant_id, period_start=period_start, period_end=period_end
        )
        if invoice is None:
            raise NotFoundError(
                "no snapshot for this period",
                details={
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                },
            )
        return invoice

    @staticmethod
    async def close_period(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> Invoice:
        """Freeze a period: aggregate its usage into an immutable Invoice row.

        Raises ConflictError when the period is already closed, or when it
        overlaps a period that is. See the class docstring for why refusing
        beats returning the existing snapshot, and for the overlap mechanism.
        """
        _validate_period(period_start, period_end)

        # Everything below is one critical section per tenant. The lock MUST
        # come before the two checks, not after: without it, two concurrent
        # closes each read "no snapshot" and both insert.
        await BillingSnapshotService._acquire_close_lock(session, tenant_id)

        existing = await BillingSnapshotService.find_snapshot(
            session, tenant_id, period_start=period_start, period_end=period_end
        )
        if existing is not None:
            raise ConflictError(
                "billing period is already closed",
                details={
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "invoice_id": str(existing.id),
                },
            )

        overlapping = await BillingSnapshotService.find_overlapping_snapshot(
            session, tenant_id, period_start=period_start, period_end=period_end
        )
        if overlapping is not None:
            # Overlapping periods would bill the shared days twice. Refused
            # rather than merged: silently absorbing the overlap would produce
            # an invoice whose total does not match any single stated period.
            raise ConflictError(
                "billing period overlaps an already closed period",
                details={
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "overlaps_invoice_id": str(overlapping.id),
                    "overlaps_period_start": (
                        overlapping.period_start.isoformat()
                        if overlapping.period_start
                        else None
                    ),
                    "overlaps_period_end": (
                        overlapping.period_end.isoformat()
                        if overlapping.period_end
                        else None
                    ),
                },
            )

        usage = await BillingSnapshotService.aggregate_period(
            session, tenant_id, period_start=period_start, period_end=period_end
        )
        subscription = await BillingService.get_subscription(session, tenant_id)
        # Only the money-denominated usage can populate a MONEY column. There is
        # no per-unit price catalogue in this system (Plan.price is the flat
        # recurring fee), so metered quantity cannot be turned into money here.
        money = _quantize_money(usage.ai_cost)

        invoice = Invoice(
            tenant_id=tenant_id,
            subscription_id=subscription.id if subscription is not None else None,
            number=BillingSnapshotService._invoice_number(period_start),
            status="open",
            subtotal=money,
            tax=Decimal("0.00"),
            total=money,
            currency="EGP",
            issued_at=datetime.now(UTC),
            period_start=period_start,
            period_end=period_end,
            extra={
                "snapshot": BillingSnapshotService.snapshot_lines(usage),
                # The exact 8dp cost, so quantizing for the MONEY column above
                # does not lose the precision the snapshot is supposed to keep.
                "ai_cost": str(usage.ai_cost),
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        try:
            async with session.begin_nested():
                session.add(invoice)
                await session.flush()
        except IntegrityError as exc:
            # uq_invoices_tenant_period. The advisory lock above already
            # serialises service closes, so this is the backstop for a writer
            # that bypassed the lock — the constraint is declarative and holds
            # regardless of code path, which is why it stays.
            raise ConflictError(
                "billing period is already closed",
                details={
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                },
            ) from exc
        return invoice

    @staticmethod
    def snapshot_lines(usage: PeriodUsage) -> list[dict[str, str]]:
        """Frozen per-feature lines, sorted, quantities as exact strings.

        Quantities are serialized as STRINGS, not JSON numbers: every Python
        JSON path decodes a number to an IEEE float, so a Numeric(14,2) total
        would be silently degraded on the way into JSONB. Strings round-trip
        exactly and are re-read as Decimal.
        """
        return [
            {"feature": feature, "quantity": str(quantity)}
            for feature, quantity in sorted(usage.features.items())
        ]

    @staticmethod
    def snapshot_view(invoice: Invoice) -> dict:
        """Serializable snapshot, read from the frozen row and never recomputed."""
        extra = invoice.extra or {}
        return {
            "invoice_id": str(invoice.id),
            "number": invoice.number,
            "status": invoice.status,
            "currency": invoice.currency,
            "period_start": (
                invoice.period_start.isoformat() if invoice.period_start else None
            ),
            "period_end": (
                invoice.period_end.isoformat() if invoice.period_end else None
            ),
            "features": extra.get("snapshot", []),
            "ai_cost": extra.get("ai_cost"),
            # str(), not float(): the money contract is Decimal end to end.
            "total": str(invoice.total),
        }

    @staticmethod
    def _invoice_number(period_start: date) -> str:
        return f"INV-{period_start.strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"

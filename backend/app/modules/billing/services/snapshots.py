"""Spec §53–54: period metering + IMMUTABLE period snapshots.

A snapshot is a correctness artefact, not a cache. Once a period is closed
its totals are frozen forever: a usage record that arrives late for that
period must not move the invoice, which is the entire point of the spec
item. Re-reading a snapshot never re-aggregates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.currency import PLATFORM_BILLING_CURRENCY
from app.core.errors import ConflictError, NotFoundError
from app.modules.billing.models import Invoice, UsageRecord
from ._common import (
    _AI_TOKENS_FEATURE,
    _BILLING_CLOSE_LOCK_NAMESPACE,
    PeriodUsage,
    _as_decimal,
    _quantize_money,
    _tenant_lock_key,
    _validate_period,
)
from .subscriptions import BillingService


class BillingSnapshotService:
    """Spec §53–54: period metering + IMMUTABLE period snapshots."""

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
            features[_AI_TOKENS_FEATURE] = features.get(_AI_TOKENS_FEATURE, Decimal(0)) + ai_tokens

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
                    "tenant_id": tenant_id,
                    "period_start": period_start,
                    "period_end": period_end,
                },
            )
        ).one()
        return _as_decimal(row.tokens), _as_decimal(row.cost)

    @staticmethod
    async def _acquire_close_lock(session: AsyncSession, tenant_id: uuid.UUID) -> None:
        """Serialise period closes for one tenant for the rest of the transaction."""
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
        """Any closed period that shares at least one day with this one."""
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
        """Freeze a period: aggregate its usage into an immutable Invoice row."""
        _validate_period(period_start, period_end)

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
            raise ConflictError(
                "billing period overlaps an already closed period",
                details={
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "overlaps_invoice_id": str(overlapping.id),
                    "overlaps_period_start": (
                        overlapping.period_start.isoformat() if overlapping.period_start else None
                    ),
                    "overlaps_period_end": (
                        overlapping.period_end.isoformat() if overlapping.period_end else None
                    ),
                },
            )

        usage = await BillingSnapshotService.aggregate_period(
            session, tenant_id, period_start=period_start, period_end=period_end
        )
        subscription = await BillingService.get_subscription(session, tenant_id)
        money = _quantize_money(usage.ai_cost)
        invoice_currency = PLATFORM_BILLING_CURRENCY

        invoice = Invoice(
            tenant_id=tenant_id,
            subscription_id=subscription.id if subscription is not None else None,
            number=BillingSnapshotService._invoice_number(period_start),
            status="open",
            subtotal=money,
            tax=Decimal("0.00"),
            total=money,
            currency=invoice_currency,
            issued_at=datetime.now(UTC),
            period_start=period_start,
            period_end=period_end,
            extra={
                "snapshot": BillingSnapshotService.snapshot_lines(usage),
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
        """Frozen per-feature lines, sorted, quantities as exact strings."""
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
            "period_start": (invoice.period_start.isoformat() if invoice.period_start else None),
            "period_end": (invoice.period_end.isoformat() if invoice.period_end else None),
            "features": extra.get("snapshot", []),
            "ai_cost": extra.get("ai_cost"),
            "total": str(invoice.total),
        }

    @staticmethod
    def _invoice_number(period_start: date) -> str:
        return f"INV-{period_start.strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"

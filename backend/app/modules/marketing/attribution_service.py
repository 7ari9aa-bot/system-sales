"""§167 + §175 — Attribution service.

Attribution MODELS are alternative views over the same money, not addends. A
single conversion credited 100.00 under first_touch and 100.00 under last_touch is
100.00 of revenue seen twice, and §167 ("METRIC DEFINITIONS") forbids a metric
having more than one number per surface: exactly one figure in a report is
canonical, every other model is a labelled alternative view that a consumer may
not add to it. The multi-touch models (linear / time_decay / position_based)
partition the value instead, and this module guarantees the partition sums to the
conversion value EXACTLY — in Decimal, with the rounding residual placed on the
last row so pence are neither invented nor lost.

The Attribution model already exists in marketing/models.py; this service
computes and stores those rows and shapes the report.

The report is a JSON payload, so it obeys the same boundary rule as
``marketing/analytics.wire_money``: a credited AMOUNT leaves as a Decimal STRING
(ADR-001/§47 — the shape ``orders/router.py`` ships for ``grand_total``), while
``conversions`` (a count) and ``weight`` (a share of one whole) stay numbers.
Floats appear in this file only as SHARES — ``compute_weights`` returns them and
``split_credited_value`` turns them back into Decimal money; no amount is ever
cast to float here.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.marketing.analytics import wire_money
from app.modules.marketing.models import (
    Attribution,
    Conversion,
    Touchpoint,
)

# Attribution models supported
_ATTRIBUTION_MODELS = frozenset({
    "first_touch", "last_touch", "linear", "time_decay", "position_based",
})

#: The one model a money figure is quoted from (analytics revenue uses it too).
CANONICAL_MODEL = "last_touch"

#: Each of these credits the WHOLE value of a conversion — two of them are the
#: same money, never twice the money.
FULL_CREDIT_MODELS = frozenset({"first_touch", "last_touch"})

#: These split the value; their shares sum to 1.
VALUE_PARTITION_MODELS = _ATTRIBUTION_MODELS - FULL_CREDIT_MODELS

_CENT = Decimal("0.01")
_WEIGHT_SCALE = Decimal("0.0001")


class AttributionService:
    """Compute and store attribution for conversions (§167, §175).

    The service is called after a conversion is recorded. It finds all
    touchpoints for the customer before the conversion, applies the
    selected attribution model, and writes Attribution rows.
    """

    @staticmethod
    async def compute_for_conversion(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversion_id: uuid.UUID,
        *,
        model: str = CANONICAL_MODEL,
    ) -> list[Attribution]:
        if model not in _ATTRIBUTION_MODELS:
            raise ValueError(
                f"attribution model must be one of {sorted(_ATTRIBUTION_MODELS)}"
            )

        conversion = (
            await session.execute(
                select(Conversion).where(
                    Conversion.tenant_id == tenant_id,
                    Conversion.id == conversion_id,
                )
            )
        ).scalar_one_or_none()
        if conversion is None:
            raise NotFoundError("conversion not found")

        # Get all touchpoints before the conversion
        touchpoints = list(
            (
                await session.execute(
                    select(Touchpoint)
                    .where(
                        Touchpoint.tenant_id == tenant_id,
                        Touchpoint.customer_id == conversion.customer_id,
                    )
                    .order_by(Touchpoint.created_at.asc())
                )
            ).scalars().all()
        )

        if not touchpoints:
            return []

        # Filter to touchpoints before the conversion occurred_at
        if conversion.occurred_at:
            touchpoints = [
                tp for tp in touchpoints
                if tp.created_at <= conversion.occurred_at
            ]

        if not touchpoints:
            return []

        already_credited = set(
            (
                await session.execute(
                    select(Attribution.touchpoint_id).where(
                        Attribution.tenant_id == tenant_id,
                        Attribution.conversion_id == conversion.id,
                        Attribution.model == model,
                    )
                )
            ).scalars().all()
        )

        weights = AttributionService.compute_weights(len(touchpoints), model)
        credited_parts = AttributionService.split_credited_value(
            conversion.value or Decimal("0.00"), weights
        )

        results: list[Attribution] = []
        for tp, weight, credited in zip(touchpoints, weights, credited_parts, strict=False):
            if tp.id in already_credited:
                continue
            if weight == 0 and credited == 0:
                continue  # a view that credits nothing adds no row
            attr = Attribution(
                tenant_id=tenant_id,
                conversion_id=conversion.id,
                touchpoint_id=tp.id,
                model=model,
                weight=Decimal(str(weight)).quantize(_WEIGHT_SCALE),
                credited_value=credited,
            )
            session.add(attr)
            results.append(attr)

        if not results:
            return []

        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            # Lost the (conversion, model, touchpoint) race — the other writer
            # credited the same money, so there is nothing to add.
            raise ConflictError(
                f"attribution for conversion {conversion_id} under {model} is being computed"
            ) from None
        return results

    @staticmethod
    async def get_campaign_attribution(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        *,
        days: int = 30,
    ) -> dict:
        """Roll up attribution for a campaign over a time range."""
        since = datetime.now(UTC) - timedelta(days=days)

        rows = (
            await session.execute(
                select(
                    Attribution.model,
                    func.count(func.distinct(Attribution.conversion_id)).label("conversions"),
                    func.coalesce(func.sum(Attribution.credited_value), 0).label("credited"),
                )
                .join(Touchpoint, Attribution.touchpoint_id == Touchpoint.id)
                .where(
                    Attribution.tenant_id == tenant_id,
                    Touchpoint.tenant_id == tenant_id,
                    Touchpoint.campaign_id == campaign_id,
                    Attribution.created_at >= since,
                )
                .group_by(Attribution.model)
            )
        ).all()

        return AttributionService.attribution_report(
            campaign_id=campaign_id,
            days=days,
            model_rows=[(r.model, int(r.conversions), Decimal(str(r.credited))) for r in rows],
        )

    @staticmethod
    def attribution_report(
        *,
        campaign_id: uuid.UUID,
        days: int,
        model_rows: Sequence[tuple[str, int, Decimal]],
    ) -> dict:
        """Shape per-model figures so they cannot be added together (§167).

        The only unlabelled money figure is the canonical one. Everything else
        sits under ``alternative_views`` carrying ``never_sum_with_other_views``,
        so a rollup can quote one Revenue number without a reader having to know
        which models exist.

        Both of those figures are AMOUNTS, so both leave through ``wire_money``
        as Decimal strings (ADR-001/§47) — a client that parsed a credited
        revenue as a float64 could not sum campaign rows and still trust the
        cents. ``conversions`` and ``days`` are counts and a window length, not
        money, and stay numbers; stringifying them would be its own bug.
        """
        ordered = sorted(model_rows, key=lambda row: row[0])
        by_model = {model: (conversions, credited) for model, conversions, credited in ordered}
        canonical = CANONICAL_MODEL if CANONICAL_MODEL in by_model else (
            ordered[0][0] if ordered else None
        )
        conversions, credited = by_model.get(canonical, (0, Decimal("0.00")))

        return {
            "campaign_id": str(campaign_id),
            "days": days,
            "canonical_model": canonical,
            "revenue": wire_money(credited),
            "conversions": conversions,
            "views_are_alternative": True,
            "alternative_views": [
                {
                    "model": model,
                    "conversions": view_conversions,
                    "credited_revenue": wire_money(view_credited),
                    "credits_full_value_of_each_conversion": model in FULL_CREDIT_MODELS,
                    "never_sum_with_other_views": True,
                }
                for model, view_conversions, view_credited in ordered
            ],
        }

    @staticmethod
    def split_credited_value(value: Decimal, weights: Sequence[float]) -> list[Decimal]:
        """Partition ``value`` across ``weights`` so the parts sum to exactly it.

        Float weights are only ever a share of one whole, so the money itself is
        computed in Decimal and the rounding residual lands on the last row — the
        alternative is a penny silently appearing or disappearing per row.
        """
        if not weights:
            return []
        amount = Decimal(str(value))
        total = sum((Decimal(str(w)) for w in weights), Decimal("0"))
        if total <= 0:
            raise ValueError("attribution weights must sum above zero")
        parts = [
            (amount * Decimal(str(w)) / total).quantize(_CENT, rounding=ROUND_HALF_UP)
            for w in weights[:-1]
        ]
        parts.append(amount - sum(parts, Decimal("0.00")))
        return parts

    @staticmethod
    def compute_weights(count: int, model: str) -> list[float]:
        """Attribution weights for ``count`` touchpoints under one model.

        Every model returns shares summing to 1: the value is moved around, never
        multiplied.
        """
        if count <= 0:
            return []
        n = count

        if model == "first_touch":
            weights = [0.0] * n
            weights[0] = 1.0
            return weights

        if model == "last_touch":
            weights = [0.0] * n
            weights[-1] = 1.0
            return weights

        if model == "linear":
            w = 1.0 / n
            return [w] * n

        if model == "time_decay":
            # More recent touchpoints get higher weight
            # Exponential decay: weight[i] = exp(-lambda * (n - 1 - i))
            decay = 0.5
            raw = [math.exp(-decay * (n - 1 - i)) for i in range(n)]
            total = sum(raw)
            return [r / total for r in raw]

        if model == "position_based":
            # 40% first, 40% last, 20% distributed across middle
            if n == 1:
                return [1.0]
            if n == 2:
                return [0.5, 0.5]
            first = 0.4
            last = 0.4
            middle = 0.2 / (n - 2)
            weights = [middle] * n
            weights[0] = first
            weights[-1] = last
            return weights

        # Fallback: equal weights
        return [1.0 / n] * n

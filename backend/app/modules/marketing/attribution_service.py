"""Spec §82 + §175 — Attribution service.

Computes first-touch, last-touch, and multi-touch attribution for
conversions, crediting touchpoints according to the selected model.

The Attribution model already exists in marketing/models.py; this service
provides the business logic to compute and store attribution records.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.marketing.models import (
    Attribution,
    Conversion,
    Touchpoint,
)

# Attribution models supported
_ATTRIBUTION_MODELS = frozenset({
    "first_touch", "last_touch", "linear", "time_decay", "position_based",
})


class AttributionService:
    """Compute and store attribution for conversions (§82, §175).

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
        model: str = "last_touch",
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
        touchpoints = (
            await session.execute(
                select(Touchpoint)
                .where(
                    Touchpoint.tenant_id == tenant_id,
                    Touchpoint.customer_id == conversion.customer_id,
                )
                .order_by(Touchpoint.created_at.asc())
            )
        ).scalars().all()

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

        weights = AttributionService._compute_weights(
            touchpoints, model
        )

        results: list[Attribution] = []
        conversion_value = conversion.value or Decimal("0")

        for tp, weight in zip(touchpoints, weights, strict=False):
            credited = (conversion_value * Decimal(str(weight))).quantize(
                Decimal("0.01")
            )
            attr = Attribution(
                tenant_id=tenant_id,
                conversion_id=conversion.id,
                touchpoint_id=tp.id,
                model=model,
                weight=weight,
                credited_value=credited,
            )
            session.add(attr)
            results.append(attr)

        await session.flush()
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
                    func.count(Attribution.id).label("conversions"),
                    func.coalesce(
                        func.sum(Attribution.credited_value), 0
                    ).label("credited_revenue"),
                )
                .join(Touchpoint, Attribution.touchpoint_id == Touchpoint.id)
                .where(
                    Attribution.tenant_id == tenant_id,
                    Touchpoint.campaign_id == campaign_id,
                    Attribution.created_at >= since,
                )
                .group_by(Attribution.model)
            )
        ).all()

        return {
            "campaign_id": str(campaign_id),
            "days": days,
            "by_model": [
                {
                    "model": r.model,
                    "conversions": r.conversions,
                    "credited_revenue": float(r.credited_revenue),
                }
                for r in rows
            ],
        }

    @staticmethod
    def _compute_weights(
        touchpoints: list, model: str
    ) -> list[float]:
        """Compute attribution weights for touchpoints under a model."""
        n = len(touchpoints)

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
            import math
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

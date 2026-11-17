"""Inventory Reporting Centre and Deterministic Analytics (D9, §4 Phase 6, 6.3).

Provides deterministic calculations for:
- Stock summary across conditions (on_hand, available, reserved, quarantined, in_transit)
- Valuation totals
- Dead stock detection (stock with no outward movement for N days)
- Stock turnover and days of supply
- Low stock and stockout risk alerts
- Apparel-specific cuts (size/color distribution and velocity)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import (
    InventoryBalance,
    InventoryCostLayer,
    InventoryMovement,
    InventoryPolicy,
    InventoryTransfer,
    InventoryTransferLine,
)


class InventoryReportingService:
    """Deterministic reporting and analytics computations."""

    @staticmethod
    async def stock_summary(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Aggregate stock summary across all operational positions."""
        q_bal = select(
            func.coalesce(func.sum(InventoryBalance.on_hand), 0).label("total_on_hand"),
            func.coalesce(func.sum(InventoryBalance.reserved), 0).label("total_reserved"),
            func.coalesce(func.sum(InventoryBalance.quarantined), 0).label("total_quarantined"),
        ).where(InventoryBalance.tenant_id == tenant_id)

        if warehouse_id:
            q_bal = q_bal.where(InventoryBalance.warehouse_id == warehouse_id)

        bal_row = (await session.execute(q_bal)).one()
        on_hand = int(bal_row.total_on_hand)
        reserved = int(bal_row.total_reserved)
        quarantined = int(bal_row.total_quarantined)
        available = max(0, on_hand - quarantined - reserved)

        # In-transit stock from active transfers
        q_trans = (
            select(
                func.coalesce(
                    func.sum(
                        InventoryTransferLine.quantity_shipped
                        - InventoryTransferLine.quantity_received
                    ),
                    0,
                )
            )
            .join(
                InventoryTransfer,
                InventoryTransfer.id == InventoryTransferLine.transfer_id,
            )
            .where(
                InventoryTransferLine.tenant_id == tenant_id,
                InventoryTransfer.status == "in_transit",
            )
        )
        if warehouse_id:
            q_trans = q_trans.where(InventoryTransfer.to_warehouse_id == warehouse_id)

        in_transit = int((await session.execute(q_trans)).scalar() or 0)

        # Valuation from active cost layers
        q_val = select(
            func.coalesce(
                func.sum(InventoryCostLayer.remaining_quantity * InventoryCostLayer.unit_cost), 0
            )
        ).where(
            InventoryCostLayer.tenant_id == tenant_id,
            InventoryCostLayer.remaining_quantity > 0,
        )
        if warehouse_id:
            q_val = q_val.where(InventoryCostLayer.warehouse_id == warehouse_id)

        valuation = Decimal((await session.execute(q_val)).scalar() or 0).quantize(
            Decimal("0.0001")
        )

        return {
            "on_hand": on_hand,
            "sellable": max(0, on_hand - quarantined),
            "available": available,
            "reserved": reserved,
            "quarantined": quarantined,
            "in_transit": in_transit,
            "total_valuation": valuation,
        }

    @staticmethod
    async def dead_stock(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        days_inactive: int = 90,
        warehouse_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Identify variants with stock on hand but no sales in the last `days_inactive` days."""
        cutoff = datetime.now(UTC) - timedelta(days=days_inactive)

        # Active stock variants
        q_bal = select(
            InventoryBalance.variant_id,
            InventoryBalance.warehouse_id,
            InventoryBalance.on_hand,
        ).where(
            InventoryBalance.tenant_id == tenant_id,
            InventoryBalance.on_hand > 0,
        )
        if warehouse_id:
            q_bal = q_bal.where(InventoryBalance.warehouse_id == warehouse_id)

        candidates = (await session.execute(q_bal)).all()

        dead = []
        for var_id, wh_id, on_hand_qty in candidates:
            # Check for sales since cutoff
            recent_moves = (
                await session.execute(
                    select(func.count(InventoryMovement.id)).where(
                        InventoryMovement.tenant_id == tenant_id,
                        InventoryMovement.variant_id == var_id,
                        InventoryMovement.warehouse_id == wh_id,
                        InventoryMovement.direction == "out",
                        InventoryMovement.reason == "sale",
                        InventoryMovement.created_at >= cutoff,
                    )
                )
            ).scalar() or 0

            if recent_moves == 0:
                dead.append(
                    {
                        "variant_id": str(var_id),
                        "warehouse_id": str(wh_id),
                        "on_hand": on_hand_qty,
                        "days_inactive": days_inactive,
                    }
                )

        return dead

    @staticmethod
    async def low_stock_alerts(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Find variants where sellable stock is below or at the policy min_stock."""
        q_pol = select(InventoryPolicy).where(InventoryPolicy.tenant_id == tenant_id)
        if warehouse_id:
            q_pol = q_pol.where(InventoryPolicy.warehouse_id == warehouse_id)

        policies = list((await session.execute(q_pol)).scalars())

        alerts = []
        for pol in policies:
            bal = (
                await session.execute(
                    select(InventoryBalance).where(
                        InventoryBalance.tenant_id == tenant_id,
                        InventoryBalance.variant_id == pol.variant_id,
                        InventoryBalance.warehouse_id == pol.warehouse_id,
                    )
                )
            ).scalar_one_or_none()

            on_hand = bal.on_hand if bal else 0
            quarantined = bal.quarantined if bal else 0
            reserved = bal.reserved if bal else 0
            available = max(0, on_hand - quarantined - reserved)

            if available <= pol.min_stock:
                alerts.append(
                    {
                        "variant_id": str(pol.variant_id),
                        "warehouse_id": str(pol.warehouse_id),
                        "available": available,
                        "min_stock": pol.min_stock,
                        "deficit": pol.min_stock - available,
                        "reorder_quantity": max(0, pol.max_stock - available)
                        if pol.max_stock
                        else pol.min_stock - available,
                    }
                )

        return alerts

    @staticmethod
    async def apparel_insights(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Apparel-specific velocity, stockout risks, and branch rebalancing (§4 Phase 6, 6.3)."""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        # 1. Top-selling variants by sales velocity
        q_sales = select(
            InventoryMovement.variant_id,
            func.sum(InventoryMovement.quantity).label("units_sold"),
        ).where(
            InventoryMovement.tenant_id == tenant_id,
            InventoryMovement.direction == "out",
            InventoryMovement.reason == "sale",
            InventoryMovement.created_at >= cutoff,
        )
        if warehouse_id:
            q_sales = q_sales.where(InventoryMovement.warehouse_id == warehouse_id)

        q_sales = (
            q_sales.group_by(InventoryMovement.variant_id)
            .order_by(func.sum(InventoryMovement.quantity).desc())
            .limit(10)
        )
        sales_rows = (await session.execute(q_sales)).all()
        top_selling = [
            {"variant_id": str(r.variant_id), "units_sold": int(r.units_sold)} for r in sales_rows
        ]

        # 2. High-demand / low-stock variants (stockout risk)
        top_var_ids = [r.variant_id for r in sales_rows]
        stockout_risks = []
        if top_var_ids:
            q_bal = select(
                InventoryBalance.variant_id,
                InventoryBalance.warehouse_id,
                InventoryBalance.on_hand,
                InventoryBalance.quarantined,
                InventoryBalance.reserved,
            ).where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.variant_id.in_(top_var_ids),
            )
            if warehouse_id:
                q_bal = q_bal.where(InventoryBalance.warehouse_id == warehouse_id)

            for b in (await session.execute(q_bal)).all():
                avail = max(0, b.on_hand - b.quarantined - b.reserved)
                if avail <= 5:
                    stockout_risks.append(
                        {
                            "variant_id": str(b.variant_id),
                            "warehouse_id": str(b.warehouse_id),
                            "available": avail,
                            "on_hand": b.on_hand,
                        }
                    )

        # 3. Multi-branch rebalancing opportunities
        q_all_bals = select(
            InventoryBalance.variant_id,
            InventoryBalance.warehouse_id,
            InventoryBalance.on_hand,
            InventoryBalance.quarantined,
            InventoryBalance.reserved,
        ).where(InventoryBalance.tenant_id == tenant_id)

        all_bals = (await session.execute(q_all_bals)).all()
        bals_by_var: dict[UUID, list[Any]] = {}
        for b in all_bals:
            bals_by_var.setdefault(b.variant_id, []).append(b)

        rebalance_ops = []
        for var_id, var_bals in bals_by_var.items():
            if len(var_bals) < 2:
                continue
            starved = [b for b in var_bals if (b.on_hand - b.quarantined - b.reserved) <= 2]
            surplus = [b for b in var_bals if (b.on_hand - b.quarantined - b.reserved) >= 10]
            for s_wh in starved:
                for src_wh in surplus:
                    avail_src = src_wh.on_hand - src_wh.quarantined - src_wh.reserved
                    avail_tgt = s_wh.on_hand - s_wh.quarantined - s_wh.reserved
                    sugg_qty = max(1, (avail_src - 5) // 2)
                    rebalance_ops.append(
                        {
                            "variant_id": str(var_id),
                            "from_warehouse_id": str(src_wh.warehouse_id),
                            "to_warehouse_id": str(s_wh.warehouse_id),
                            "source_available": avail_src,
                            "target_available": avail_tgt,
                            "suggested_transfer_quantity": sugg_qty,
                        }
                    )

        return {
            "top_selling_variants": top_selling,
            "stockout_risk_variants": stockout_risks,
            "branch_rebalance_opportunities": rebalance_ops,
        }

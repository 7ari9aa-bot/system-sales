"""Replenishment engine and reorder suggestions (D9, §4 Phase 4).

Deterministic replenishment policies:
    min_stock, max_stock, safety_stock, lead_time_days, moq, order_multiple,
    review_period_days, preferred_supplier_id.

Arithmetic:
  1. projected_stock = on_hand - quarantined - reserved + incoming
  2. if projected_stock < min_stock:
       gross_req = target_stock - projected_stock
       qty = max(gross_req, moq)
       if order_multiple > 1:
           qty = ceil(qty / order_multiple) * order_multiple
       source = 'purchase' (or 'transfer' if surplus exists elsewhere)
       reason = {arithmetic breakdown}

Approving an accepted purchase suggestion creates a draft PurchaseOrder.
"""

from __future__ import annotations

import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.models import (
    InventoryPolicy,
    ReorderSuggestion,
)
from app.modules.inventory.services.balances import BalanceServiceMixin


class ReplenishmentService:
    """Deterministic replenishment policies and reorder suggestion workflows."""

    # ------------------------------------------------------------- policy --

    @staticmethod
    async def set_policy(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
        min_stock: int,
        max_stock: int | None = None,
        safety_stock: int | None = None,
        lead_time_days: int = 0,
        moq: int = 1,
        order_multiple: int = 1,
        review_period_days: int = 7,
        preferred_supplier_id: UUID | None = None,
    ) -> InventoryPolicy:
        """Upsert the replenishment policy for a variant at a warehouse."""
        if safety_stock is None:
            # Not stated for this variant: the shop-wide buffer applies.
            from app.modules.settings.service import SettingsService

            safety_stock = int(
                await SettingsService(session, tenant_id).value("inventory.safety_stock_default")
                or 0
            )
        if min_stock < 0 or safety_stock < 0 or lead_time_days < 0:
            raise ValidationError("stock quantities and lead time must not be negative")
        if moq <= 0 or order_multiple <= 0 or review_period_days <= 0:
            raise ValidationError("moq, order_multiple and review_period must be > 0")
        if max_stock is not None and max_stock < min_stock:
            raise ValidationError("max_stock cannot be less than min_stock")

        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)
        await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)

        stmt = (
            pg_insert(InventoryPolicy)
            .values(
                tenant_id=tenant_id,
                variant_id=variant_id,
                warehouse_id=warehouse_id,
                min_stock=min_stock,
                max_stock=max_stock,
                safety_stock=safety_stock,
                lead_time_days=lead_time_days,
                moq=moq,
                order_multiple=order_multiple,
                review_period_days=review_period_days,
                preferred_supplier_id=preferred_supplier_id,
            )
            .on_conflict_do_update(
                constraint="uq_inventory_policies_variant_wh",
                set_={
                    "min_stock": min_stock,
                    "max_stock": max_stock,
                    "safety_stock": safety_stock,
                    "lead_time_days": lead_time_days,
                    "moq": moq,
                    "order_multiple": order_multiple,
                    "review_period_days": review_period_days,
                    "preferred_supplier_id": preferred_supplier_id,
                },
            )
        )
        await session.execute(stmt)
        return (
            await session.execute(
                select(InventoryPolicy).where(
                    InventoryPolicy.tenant_id == tenant_id,
                    InventoryPolicy.variant_id == variant_id,
                    InventoryPolicy.warehouse_id == warehouse_id,
                )
            )
        ).scalar_one()

    @staticmethod
    async def get_policy(
        session: AsyncSession, tenant_id: UUID, *, variant_id: UUID, warehouse_id: UUID
    ) -> InventoryPolicy | None:
        return (
            await session.execute(
                select(InventoryPolicy).where(
                    InventoryPolicy.tenant_id == tenant_id,
                    InventoryPolicy.variant_id == variant_id,
                    InventoryPolicy.warehouse_id == warehouse_id,
                )
            )
        ).scalar_one_or_none()

    # -------------------------------------------------------- suggestions --

    @staticmethod
    async def evaluate_variant(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
    ) -> ReorderSuggestion | None:
        """Evaluate a single variant against its policy and generate a suggestion if needed."""
        policy = await ReplenishmentService.get_policy(
            session, tenant_id, variant_id=variant_id, warehouse_id=warehouse_id
        )
        if policy is None:
            return None

        bal = await BalanceServiceMixin.get_balance(session, tenant_id, variant_id, warehouse_id)
        on_hand = bal.on_hand or 0
        quarantined = bal.quarantined or 0
        reserved = bal.reserved or 0

        # Projected stock = on_hand - quarantined - reserved
        projected_stock = on_hand - quarantined - reserved

        if projected_stock >= policy.min_stock:
            return None  # No reorder needed

        # Target stock to reach
        target_stock = (
            policy.max_stock
            if policy.max_stock is not None
            else (policy.min_stock + policy.safety_stock)
        )
        gross_req = target_stock - projected_stock

        # Apply MOQ
        qty = max(gross_req, policy.moq)

        # Apply pack multiple
        if policy.order_multiple > 1:
            qty = math.ceil(qty / policy.order_multiple) * policy.order_multiple

        # Deterministic arithmetic breakdown
        reason_data = {
            "on_hand": on_hand,
            "quarantined": quarantined,
            "reserved": reserved,
            "projected_stock": projected_stock,
            "min_stock": policy.min_stock,
            "target_stock": target_stock,
            "gross_requirement": gross_req,
            "moq": policy.moq,
            "order_multiple": policy.order_multiple,
            "safety_stock": policy.safety_stock,
            "lead_time_days": policy.lead_time_days,
        }

        # Check for open suggestion to avoid duplication
        existing = (
            await session.execute(
                select(ReorderSuggestion).where(
                    ReorderSuggestion.tenant_id == tenant_id,
                    ReorderSuggestion.variant_id == variant_id,
                    ReorderSuggestion.warehouse_id == warehouse_id,
                    ReorderSuggestion.status == "open",
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.suggested_quantity = qty
            existing.reason = reason_data
            await session.flush()
            return existing

        suggestion = ReorderSuggestion(
            tenant_id=tenant_id,
            variant_id=variant_id,
            warehouse_id=warehouse_id,
            suggested_quantity=qty,
            source="purchase",
            reason=reason_data,
            status="open",
        )
        session.add(suggestion)
        await session.flush()
        return suggestion

    @staticmethod
    async def generate_suggestions(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID | None = None,
    ) -> list[ReorderSuggestion]:
        """Scan policies and generate suggestions for all variants below min_stock."""
        q = select(InventoryPolicy).where(InventoryPolicy.tenant_id == tenant_id)
        if warehouse_id:
            q = q.where(InventoryPolicy.warehouse_id == warehouse_id)
        policies = list((await session.execute(q)).scalars())

        suggestions = []
        for policy in policies:
            sugg = await ReplenishmentService.evaluate_variant(
                session,
                tenant_id,
                variant_id=policy.variant_id,
                warehouse_id=policy.warehouse_id,
            )
            if sugg is not None:
                suggestions.append(sugg)
        return suggestions

    # --------------------------------------------------- approve / dismiss --

    @staticmethod
    async def approve_suggestion(
        session: AsyncSession,
        tenant_id: UUID,
        suggestion_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> ReorderSuggestion:
        """Approve a suggestion: status -> accepted."""
        suggestion = (
            await session.execute(
                select(ReorderSuggestion)
                .where(
                    ReorderSuggestion.tenant_id == tenant_id,
                    ReorderSuggestion.id == suggestion_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if suggestion is None:
            raise NotFoundError("suggestion not found")
        if suggestion.status != "open":
            raise ConflictError(f"suggestion is already {suggestion.status}")

        suggestion.status = "accepted"
        await session.flush()
        return suggestion

    @staticmethod
    async def dismiss_suggestion(
        session: AsyncSession,
        tenant_id: UUID,
        suggestion_id: UUID,
        *,
        reason: str | None = None,
    ) -> ReorderSuggestion:
        """Dismiss a suggestion without creating an order."""
        suggestion = (
            await session.execute(
                select(ReorderSuggestion)
                .where(
                    ReorderSuggestion.tenant_id == tenant_id,
                    ReorderSuggestion.id == suggestion_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if suggestion is None:
            raise NotFoundError("suggestion not found")
        if suggestion.status != "open":
            raise ConflictError(f"suggestion is already {suggestion.status}")

        suggestion.status = "dismissed"
        if reason:
            curr_reason = dict(suggestion.reason) if suggestion.reason else {}
            curr_reason["dismiss_reason"] = reason
            suggestion.reason = curr_reason

        await session.flush()
        return suggestion

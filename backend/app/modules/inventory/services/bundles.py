"""Inventory Bundle Service: availability, reservations, and sales (§4 Phase 6, M2).

Ensures:
- A bundle can never sell past its components' availability.
- Selling a bundle decrements each component exactly once.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InsufficientStockError
from app.modules.errors import NotFoundError, ValidationError
from app.modules.inventory.models import InventoryBalance, InventoryMovement
from app.modules.inventory.services.balances import BalanceServiceMixin
from app.modules.inventory.services.movements import MovementServiceMixin


class InventoryBundleService:
    """Stock availability and fulfillment logic for bundles and kits."""

    @staticmethod
    async def get_bundle_availability(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        bundle_id: UUID,
        warehouse_id: UUID,
    ) -> int:
        """Calculate how many units of a bundle can be sold based on component stock.

        available = min(component_sellable_available // line.quantity for each component)
        """
        cat = BalanceServiceMixin._catalog()
        bundle = await cat.get_bundle(session, tenant_id, bundle_id)
        if bundle is None:
            raise NotFoundError("bundle not found")
        if not bundle.is_active:
            return 0

        lines = await cat.get_bundle_lines(session, tenant_id, bundle_id)
        if not lines:
            return 0

        max_bundles: int | None = None
        for line in lines:
            bal = await BalanceServiceMixin._locked_balance(
                session, tenant_id, line.variant_id, warehouse_id
            )
            # sellable available = on_hand - quarantined - reserved
            avail = max(0, bal.on_hand - (bal.quarantined or 0) - (bal.reserved or 0))
            possible = avail // line.quantity
            if max_bundles is None or possible < max_bundles:
                max_bundles = possible

        return max_bundles or 0

    @staticmethod
    async def sell_bundle(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        bundle_id: UUID,
        warehouse_id: UUID,
        quantity: int,
        reference_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> list[InventoryMovement]:
        """Sell `quantity` units of a bundle, decrementing each component line exactly once.

        Refuses if quantity exceeds bundle availability.
        """
        if quantity <= 0:
            raise ValidationError("bundle quantity must be positive")

        cat = BalanceServiceMixin._catalog()
        bundle = await cat.get_bundle(session, tenant_id, bundle_id)
        if bundle is None:
            raise NotFoundError("bundle not found")
        if not bundle.is_active:
            raise ValidationError("cannot sell an inactive bundle")

        lines = await cat.get_bundle_lines(session, tenant_id, bundle_id)
        if not lines:
            raise ValidationError("bundle has no component lines")

        # Lock and verify each component balance before moving anything
        for line in sorted(lines, key=lambda item: str(item.variant_id)):
            bal = await BalanceServiceMixin._locked_balance(
                session, tenant_id, line.variant_id, warehouse_id
            )
            needed = quantity * line.quantity
            avail = bal.on_hand - (bal.quarantined or 0) - (bal.reserved or 0)
            if avail < needed:
                raise InsufficientStockError(
                    f"insufficient stock for component variant {line.variant_id} of bundle "
                    f"{bundle.name}: need {needed}, available {avail}"
                )

        # Decrement each component exactly once
        movements = []
        for line in sorted(lines, key=lambda item: str(item.variant_id)):
            mov = await MovementServiceMixin.move(
                session,
                tenant_id,
                variant_id=line.variant_id,
                warehouse_id=warehouse_id,
                direction="out",
                quantity=quantity * line.quantity,
                reason="sale",
                reference_type="bundle_sale",
                reference_id=reference_id or bundle_id,
                actor_user_id=actor_user_id,
            )
            movements.append(mov)

        return movements

    @staticmethod
    async def reserve_bundle(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        bundle_id: UUID,
        warehouse_id: UUID,
        quantity: int,
    ) -> list[InventoryBalance]:
        """Reserve components for `quantity` units of a bundle."""
        if quantity <= 0:
            raise ValidationError("bundle quantity must be positive")

        cat = BalanceServiceMixin._catalog()
        lines = await cat.get_bundle_lines(session, tenant_id, bundle_id)
        if not lines:
            raise ValidationError("bundle has no component lines")

        balances = []
        for line in sorted(lines, key=lambda item: str(item.variant_id)):
            bal = await MovementServiceMixin.reserve(
                session,
                tenant_id,
                variant_id=line.variant_id,
                warehouse_id=warehouse_id,
                quantity=quantity * line.quantity,
            )
            balances.append(bal)
        return balances

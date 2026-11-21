"""The expiry report: which batches have expired and which will soon.

A pharmacy-like shop has to act on dates: return what the supplier takes back, discount what is
about to go, throw away what is past. The window that counts as "soon" is the owner's setting
(``inventory.expiry_alert_days``), and the whole report exists only for a shop whose
``lot_expiry`` capability is on, so a clothes shop is never shown an empty pharmacy screen.

A batch holds what is left of the cost layers that name it, so each row says how many units are
still in it. A batch no layer names reports ``None``: its quantity is unknown, not zero.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import InventoryCostLayer, InventoryLot
from app.modules.settings.capabilities import shop_capabilities


def _row(
    lot: InventoryLot, sku: str | None, product: str, variant: str, now: datetime, qty: int | None
) -> dict:
    assert lot.expires_at is not None
    return {
        "lot_id": str(lot.id),
        "lot_code": lot.lot_code,
        "sku": sku,
        "product": product,
        "variant": variant,
        "expires_at": lot.expires_at.isoformat(),
        "days_left": (lot.expires_at.date() - now.date()).days,
        # Units still in the batch (what its cost layers have left); None when no layer names it,
        # because "unknown" is not "empty".
        "quantity": qty,
    }


async def expiry_report(
    session: AsyncSession, tenant_id: UUID, *, now: datetime | None = None
) -> dict[str, Any]:
    """Expired and soon-to-expire batches, soonest first, for a shop that tracks expiry."""
    # Function scope on purpose: the boundary guard counts module-scope service imports across
    # modules (test_module_scope_service_imports_do_not_grow) and the cashier modules may not add.
    from app.modules.settings.service import SettingsService

    now = now or datetime.now(UTC)
    caps = await shop_capabilities(session, tenant_id)
    # The setting is a number from 1 to 730 with a default of 30, so it always resolves.
    window = int(
        (await SettingsService(session, tenant_id).resolve("inventory.expiry_alert_days")).value
    )
    empty: dict[str, Any] = {
        "enabled": False,
        "window_days": window,
        "expired": [],
        "expiring": [],
        "fine_count": 0,
        "expired_units": 0,
        "expiring_units": 0,
    }
    if not caps["capabilities"]["lot_expiry"]:  # type: ignore[index]
        return empty

    rows = (
        await session.execute(
            select(InventoryLot, ProductVariant.sku, Product.title, ProductVariant.title)
            .join(
                ProductVariant,
                (ProductVariant.id == InventoryLot.variant_id)
                & (ProductVariant.tenant_id == InventoryLot.tenant_id),
            )
            .join(
                Product,
                (Product.id == ProductVariant.product_id)
                & (Product.tenant_id == ProductVariant.tenant_id),
            )
            .where(InventoryLot.tenant_id == tenant_id, InventoryLot.expires_at.is_not(None))
            .order_by(InventoryLot.expires_at.asc(), InventoryLot.lot_code.asc())
        )
    ).all()

    held: dict[UUID, int] = {
        lot_id: int(total)
        for lot_id, total in (
            await session.execute(
                select(InventoryCostLayer.lot_id, func.sum(InventoryCostLayer.remaining_quantity))
                .where(
                    InventoryCostLayer.tenant_id == tenant_id,
                    InventoryCostLayer.lot_id.is_not(None),
                )
                .group_by(InventoryCostLayer.lot_id)
            )
        ).all()
    }

    horizon = now + timedelta(days=window)
    expired: list[dict] = []
    expiring: list[dict] = []
    fine = 0
    for lot, sku, product, variant in rows:
        item = _row(lot, sku, product, variant, now, held.get(lot.id))
        if lot.expires_at <= now:
            expired.append(item)
        elif lot.expires_at <= horizon:
            expiring.append(item)
        else:
            fine += 1
    return {
        "enabled": True,
        "window_days": window,
        "expired": expired,
        "expiring": expiring,
        "fine_count": fine,
        "expired_units": sum(r["quantity"] or 0 for r in expired),
        "expiring_units": sum(r["quantity"] or 0 for r in expiring),
    }


async def expired_quantity(
    session: AsyncSession,
    tenant_id: UUID,
    variant_id: UUID,
    warehouse_id: UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Units still on the shelf that sit in a batch that has expired.

    A batch's stock is what is left of the cost layers that name it, so a unit already sold out of
    an expired batch is not counted. Stock with no batch, or a batch with no expiry date, never
    counts as expired. A batch expiring this instant is expired.
    """
    at = now or datetime.now(UTC)
    total = (
        await session.execute(
            select(func.coalesce(func.sum(InventoryCostLayer.remaining_quantity), 0))
            .join(
                InventoryLot,
                (InventoryLot.id == InventoryCostLayer.lot_id)
                & (InventoryLot.tenant_id == InventoryCostLayer.tenant_id),
            )
            .where(
                InventoryCostLayer.tenant_id == tenant_id,
                InventoryCostLayer.variant_id == variant_id,
                InventoryCostLayer.warehouse_id == warehouse_id,
                InventoryLot.expires_at.is_not(None),
                InventoryLot.expires_at <= at,
            )
        )
    ).scalar_one()
    return int(total)


async def sellable_quantity(
    session: AsyncSession,
    tenant_id: UUID,
    variant_id: UUID,
    warehouse_id: UUID,
    *,
    on_hand: int,
    now: datetime | None = None,
) -> int:
    """How many units the till may offer: the balance minus what has expired, never below zero.

    Only a shop that tracks expiry subtracts the expired units; for every other shop the answer is
    the balance, so nothing changes for a shop that has not turned the capability on.
    """
    caps = await shop_capabilities(session, tenant_id)
    if not caps["capabilities"]["lot_expiry"]:  # type: ignore[index]
        return int(on_hand)
    expired = await expired_quantity(session, tenant_id, variant_id, warehouse_id, now=now)
    return max(int(on_hand) - expired, 0)


async def find_or_create_lot(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    variant_id: UUID,
    lot_code: str,
    expires_at: datetime | None,
) -> UUID:
    """The batch with this code for this variant, made if it is new.

    A batch is one code per variant. A second delivery of the same code joins it, but only with the
    same expiry date: two dates under one code would make the batch's expiry a guess.
    """
    existing = (
        await session.execute(
            select(InventoryLot).where(
                InventoryLot.tenant_id == tenant_id,
                InventoryLot.variant_id == variant_id,
                InventoryLot.lot_code == lot_code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.expires_at != expires_at:
            raise ValidationError(f"batch {lot_code!r} already exists with a different expiry date")
        return existing.id
    lot = InventoryLot(
        tenant_id=tenant_id, variant_id=variant_id, lot_code=lot_code, expires_at=expires_at
    )
    session.add(lot)
    await session.flush()
    return lot.id

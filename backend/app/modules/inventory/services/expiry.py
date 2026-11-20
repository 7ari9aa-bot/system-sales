"""The expiry report: which batches have expired and which will soon.

A pharmacy-like shop has to act on dates: return what the supplier takes back, discount what is
about to go, throw away what is past. The window that counts as "soon" is the owner's setting
(``inventory.expiry_alert_days``), and the whole report exists only for a shop whose
``lot_expiry`` capability is on, so a clothes shop is never shown an empty pharmacy screen.

A batch carries no quantity of its own yet (stock is per variant, not per batch), so this reports
the batches and their dates, not how many units are left in each.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import InventoryLot
from app.modules.settings.capabilities import shop_capabilities
from app.modules.settings.service import SettingsService


def _row(lot: InventoryLot, sku: str | None, product: str, variant: str, now: datetime) -> dict:
    assert lot.expires_at is not None
    return {
        "lot_id": str(lot.id),
        "lot_code": lot.lot_code,
        "sku": sku,
        "product": product,
        "variant": variant,
        "expires_at": lot.expires_at.isoformat(),
        "days_left": (lot.expires_at.date() - now.date()).days,
    }


async def expiry_report(
    session: AsyncSession, tenant_id: UUID, *, now: datetime | None = None
) -> dict[str, Any]:
    """Expired and soon-to-expire batches, soonest first, for a shop that tracks expiry."""
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

    horizon = now + timedelta(days=window)
    expired: list[dict] = []
    expiring: list[dict] = []
    fine = 0
    for lot, sku, product, variant in rows:
        item = _row(lot, sku, product, variant, now)
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
    }

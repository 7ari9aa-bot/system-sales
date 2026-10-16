"""Stock the seeded warehouse so the preview can complete a sale."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core import model_registry  # noqa: F401  (completes Base.metadata)
from app.core.db import bind_tenant, get_sessionmaker
from app.modules.catalog.models import ProductIdentifier, ProductVariant
from app.modules.inventory.service import InventoryService
from app.modules.pos.models import PosProfile

TENANT = "6cbe3d0e-93b1-4e7a-96a1-94dbabe66545"
WAREHOUSE = "80c4ceb2-f79b-48c4-b0ff-74adf92fce44"
STOCK = 100


async def main() -> None:
    async with get_sessionmaker()() as session:
        await bind_tenant(session, TENANT)

        variants = (
            await session.execute(
                select(ProductVariant).where(ProductVariant.tenant_id == TENANT)
            )
        ).scalars().all()

        for variant in variants:
            balance = await InventoryService.get_balance(session, TENANT, variant.id, WAREHOUSE)
            if balance and balance.on_hand >= STOCK:
                print(f"  {variant.sku}: already {balance.on_hand}")
                continue
            await InventoryService.move(
                session,
                TENANT,
                variant.id,
                WAREHOUSE,
                direction="in",
                quantity=STOCK,
                reason="purchase",
            )
            print(f"  {variant.sku}: stocked {STOCK}")
        await session.commit()

        profile = (
            await session.execute(select(PosProfile).where(PosProfile.tenant_id == TENANT))
        ).scalars().first()
        print(f"profile {profile.code} default_customer={profile.default_customer_id}")


if __name__ == "__main__":
    asyncio.run(main())

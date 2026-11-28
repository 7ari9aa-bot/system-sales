"""The reorder level of a variant and the rule that turns a quantity into in / low / out.

This is all the inventory module owns. The joined screen read-model (names, options, barcode,
price, cost) lives in `pos.stock_view`, where catalog / orders / purchasing are already read
together: putting it here would close an inventory <-> purchasing import cycle.

  out : on_hand <= 0
  low : 0 < on_hand <= reorder_level      (reorder_level 0 means "no alert", never "low")
  in  : otherwise
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import NotFoundError, ValidationError
from app.applications.apparel.modules.inventory.models import VariantStockSetting

MAX_REORDER_LEVEL = 1_000_000


def stock_status(on_hand: int, reorder_level: int) -> str:
    if on_hand <= 0:
        return "out"
    if on_hand <= reorder_level:
        return "low"
    return "in"


def checked_level(level: object) -> int:
    """A reorder level the shop may store: a whole number from 0 (no alert) upward."""
    # bool is an int in Python: True would silently become a level of 1.
    if isinstance(level, bool) or not isinstance(level, int):
        raise ValidationError("reorder level must be a whole number")
    if level < 0 or level > MAX_REORDER_LEVEL:
        raise ValidationError(f"reorder level must be between 0 and {MAX_REORDER_LEVEL}")
    return level


class StockLevelService:
    @staticmethod
    async def set_reorder_level(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID, level: object
    ) -> int:
        level = checked_level(level)
        # The variant must exist in THIS tenant; a bare insert would only fail on the FK, with
        # a database error instead of a clean not-found.
        exists = (
            await session.execute(
                text("SELECT 1 FROM product_variants WHERE id = :v AND tenant_id = :t"),
                {"v": variant_id, "t": tenant_id},
            )
        ).first()
        if exists is None:
            raise NotFoundError(f"variant {variant_id} not found")
        stmt = pg_insert(VariantStockSetting).values(
            tenant_id=tenant_id, variant_id=variant_id, reorder_level=level
        )
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_variant_stock_settings_variant",
                set_={"reorder_level": level, "updated_at": func.now()},
            )
        )
        return level

    @staticmethod
    async def get_reorder_level(session: AsyncSession, tenant_id: UUID, variant_id: UUID) -> int:
        """The stored level, 0 when nobody configured one (no row = no alert)."""
        stored = (
            await session.execute(
                select(VariantStockSetting.reorder_level).where(
                    VariantStockSetting.tenant_id == tenant_id,
                    VariantStockSetting.variant_id == variant_id,
                )
            )
        ).scalar_one_or_none()
        return 0 if stored is None else int(stored)

    @staticmethod
    async def set_reorder_level_for_product(
        session: AsyncSession, tenant_id: UUID, product_id: UUID, level: object
    ) -> int:
        """One reorder level for a whole model, written to every active size it comes in.

        A clothing shop restocks a size run, not a size: setting the level one variant at a time
        across eight sizes is how a model ends up with no alert at all. Variants that are inactive
        are left alone - they are not on the rail, so they cannot run low. Returns how many
        variants now carry the level.
        """
        level = checked_level(level)
        variants = list(
            (
                await session.execute(
                    text(
                        "SELECT id FROM product_variants "
                        "WHERE product_id = :p AND tenant_id = :t AND is_active IS TRUE"
                    ),
                    {"p": product_id, "t": tenant_id},
                )
            ).scalars()
        )
        if not variants:
            # Either no such model in this tenant, or every size of it is archived.
            raise NotFoundError(f"product {product_id} has no active variants")
        stmt = pg_insert(VariantStockSetting).values(
            [{"tenant_id": tenant_id, "variant_id": v, "reorder_level": level} for v in variants]
        )
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_variant_stock_settings_variant",
                set_={"reorder_level": level, "updated_at": func.now()},
            )
        )
        return len(variants)


class StocktakeGateway:
    """What `pos` may do with a physical count, behind the one inventory file it already imports.

    Every import is inside the method: a count is reached on demand, and importing the services
    package at module scope here would add a module-scope service import (and a cycle risk) for
    a feature most requests never touch.
    """

    @staticmethod
    async def open_default(session: AsyncSession, tenant_id: UUID, *, user_id, note) -> dict:
        from app.applications.apparel.modules.inventory.service import InventoryService
        from app.applications.apparel.modules.inventory.services import StocktakeService

        warehouse = await InventoryService.get_default_warehouse(session, tenant_id)
        stocktake = await StocktakeService.open(
            session, tenant_id, warehouse.id, user_id=user_id, note=note
        )
        return await StocktakeService.detail(session, tenant_id, stocktake.id)

    @staticmethod
    async def list_recent(session: AsyncSession, tenant_id: UUID, *, limit: int = 20):
        from app.applications.apparel.modules.inventory.services import StocktakeService

        return await StocktakeService.list_recent(session, tenant_id, limit=limit)

    @staticmethod
    async def detail(session: AsyncSession, tenant_id: UUID, stocktake_id: UUID) -> dict:
        from app.applications.apparel.modules.inventory.services import StocktakeService

        return await StocktakeService.detail(session, tenant_id, stocktake_id)

    @staticmethod
    async def record_counts(
        session: AsyncSession, tenant_id: UUID, stocktake_id: UUID, counts: list[dict]
    ) -> int:
        from app.applications.apparel.modules.inventory.services import StocktakeService

        return await StocktakeService.record_counts(session, tenant_id, stocktake_id, counts)

    @staticmethod
    async def approve(
        session: AsyncSession, tenant_id: UUID, stocktake_id: UUID, *, user_id
    ) -> dict:
        from app.applications.apparel.modules.inventory.services import StocktakeService

        return await StocktakeService.approve(session, tenant_id, stocktake_id, user_id=user_id)

    @staticmethod
    async def cancel(
        session: AsyncSession, tenant_id: UUID, stocktake_id: UUID, *, user_id
    ) -> None:
        from app.applications.apparel.modules.inventory.services import StocktakeService

        await StocktakeService.cancel(session, tenant_id, stocktake_id, user_id=user_id)


class VoidGateway:
    """What `pos` may do with the stock of a VOIDED sale, behind the one inventory file it imports.

    A void puts the goods back on the shelf. Putting the quantity back without its cost would leave
    the shelf holding stock worth nothing and make the next sale book a cost of zero, so the sale's
    own movement is read for what it cost and a fresh layer is created at that unit cost. Both are
    inventory's rules, so the till asks for them here instead of importing the tables.
    """

    @staticmethod
    async def restore_sold_stock(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        order_id: UUID,
        warehouse_id: UUID,
        lines: list[tuple[UUID, int]],
        actor_user_id: UUID | None = None,
    ) -> None:
        """(variant_id, quantity) pairs back on the shelf, each at the cost the sale booked."""
        from app.applications.apparel.modules.inventory.models import InventoryMovement
        from app.applications.apparel.modules.inventory.service import InventoryService
        from app.applications.apparel.modules.inventory.services.valuation import ValuationService

        for variant_id, quantity in lines:
            await InventoryService.move(
                session,
                tenant_id,
                variant_id,
                warehouse_id,
                direction="in",
                quantity=quantity,
                reason="void",
                reference_type="order",
                reference_id=order_id,
                actor_user_id=actor_user_id,
            )
            sold = (
                await session.execute(
                    select(InventoryMovement.cost_value).where(
                        InventoryMovement.tenant_id == tenant_id,
                        InventoryMovement.variant_id == variant_id,
                        InventoryMovement.reference_type == "order",
                        InventoryMovement.reference_id == order_id,
                        InventoryMovement.direction == "out",
                        InventoryMovement.reason == "sale",
                    )
                )
            ).first()
            sold_cost = Decimal(str(sold[0])) if sold is not None and sold[0] is not None else None
            if sold_cost is None or not quantity:
                continue
            await ValuationService.create_cost_layer(
                session,
                tenant_id,
                variant_id=variant_id,
                warehouse_id=warehouse_id,
                quantity=int(quantity),
                unit_cost=(sold_cost / Decimal(int(quantity))).quantize(Decimal("0.0001")),
                source_type="void",
                source_id=order_id,
            )

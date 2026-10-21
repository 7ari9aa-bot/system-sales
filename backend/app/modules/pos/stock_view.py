"""The stock screen's read model: one joined row per variant.

/inventory/balances is (variant, warehouse, on_hand, reserved): a table of numbers with no names.
The screen needs the product, its options, its scan code, its price and cost and the reorder rule
next to the quantity. They are joined HERE (pos is already the read-model adapter over
catalog / orders / inventory) and the status is decided by `inventory.stock_view.stock_status`,
once, so the grid, the CSV export and the dashboard alert count cannot drift apart.

on_hand is summed over warehouses (one shop first); reserved is reported on its own. The cost is
the moving average. An UNKNOWN cost stays null (never 0): a zero would value the shelf at nothing
and make every margin look like 100%.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Category, Product, ProductIdentifier, ProductVariant
from app.modules.errors import ValidationError
from app.modules.inventory.models import InventoryBalance, VariantStockSetting
from app.modules.inventory.stock_view import stock_status
from app.modules.orders.money import to_money

# `variant_costs` is purchasing's table. Importing its model would add a pos -> purchasing edge and
# close the {expenses, pos, purchasing} import cycle (purchasing already imports pos), so the one
# column this read needs is declared as a lightweight table instead. The schema stays owned by
# purchasing; test_the_cost_table_shape_matches_purchasing pins the two together.
VariantCost = table(  # noqa: N816
    "variant_costs",
    column("tenant_id"),
    column("variant_id"),
    column("avg_cost"),
)

# A scan code a person would print on a label: prefer a retail code over an internal token.
_BARCODE_PRIORITY = ("ean", "gtin", "upc", "barcode")


class StockViewService:
    @staticmethod
    async def list_stock(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        term: str | None = None,
        category_id: UUID | None = None,
        status: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        if status is not None and status not in {"in", "low", "out"}:
            raise ValidationError("status must be one of in, low, out")

        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))

        held = (
            select(
                InventoryBalance.variant_id.label("variant_id"),
                func.coalesce(func.sum(InventoryBalance.on_hand), 0).label("on_hand"),
                func.coalesce(func.sum(InventoryBalance.reserved), 0).label("reserved"),
            )
            .where(InventoryBalance.tenant_id == tenant_id)
            .group_by(InventoryBalance.variant_id)
            .subquery()
        )
        level = func.coalesce(VariantStockSetting.reorder_level, 0)
        on_hand = func.coalesce(held.c.on_hand, 0)
        query = (
            select(
                ProductVariant,
                Product,
                Category.name.label("category_name"),
                on_hand.label("on_hand"),
                func.coalesce(held.c.reserved, 0).label("reserved"),
                level.label("reorder_level"),
                VariantCost.c.avg_cost.label("avg_cost"),
            )
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(Category, Category.id == Product.category_id)
            .outerjoin(held, held.c.variant_id == ProductVariant.id)
            .outerjoin(
                VariantStockSetting,
                (VariantStockSetting.variant_id == ProductVariant.id)
                & (VariantStockSetting.tenant_id == tenant_id),
            )
            .outerjoin(
                VariantCost,
                (VariantCost.c.variant_id == ProductVariant.id)
                & (VariantCost.c.tenant_id == tenant_id),
            )
            .where(ProductVariant.tenant_id == tenant_id, ProductVariant.is_active.is_(True))
            .order_by(Product.title, ProductVariant.sku, ProductVariant.id)
        )
        if category_id is not None:
            query = query.where(Product.category_id == category_id)
        if term and term.strip():
            like = f"%{term.strip().lower()}%"
            codes = (
                select(ProductIdentifier.variant_id)
                .where(
                    ProductIdentifier.tenant_id == tenant_id,
                    func.lower(ProductIdentifier.value).like(like),
                )
                .scalar_subquery()
            )
            query = query.where(
                func.lower(Product.title).like(like)
                | func.lower(func.coalesce(ProductVariant.sku, "")).like(like)
                | ProductVariant.id.in_(codes)
            )
        if status == "out":
            query = query.where(on_hand <= 0)
        elif status == "low":
            query = query.where(on_hand > 0, on_hand <= level)
        elif status == "in":
            query = query.where(on_hand > 0, on_hand > level)
        rows = (await session.execute(query.limit(limit).offset(offset))).all()
        barcodes = await StockViewService._barcodes(session, tenant_id, [r[0].id for r in rows])
        return [StockViewService._row(r, barcodes.get(r[0].id)) for r in rows]

    @staticmethod
    async def _barcodes(session: AsyncSession, tenant_id: UUID, ids: list[UUID]) -> dict:
        if not ids:
            return {}
        found = (
            await session.execute(
                select(
                    ProductIdentifier.variant_id, ProductIdentifier.type, ProductIdentifier.value
                ).where(
                    ProductIdentifier.tenant_id == tenant_id, ProductIdentifier.variant_id.in_(ids)
                )
            )
        ).all()
        best: dict = {}
        for variant_id, kind, value in found:
            rank = _BARCODE_PRIORITY.index(kind) if kind in _BARCODE_PRIORITY else 99
            if variant_id not in best or rank < best[variant_id][0]:
                best[variant_id] = (rank, value)
        return {k: v[1] for k, v in best.items()}

    @staticmethod
    def _row(r, barcode: str | None) -> dict:
        variant, product, category_name, on_hand, reserved, level, avg_cost = r
        on_hand, reserved, level = int(on_hand), int(reserved), int(level)
        price = Decimal(variant.price)
        cost_value = None if avg_cost is None else to_money(Decimal(avg_cost) * on_hand)
        return {
            "variant_id": str(variant.id),
            "product_id": str(product.id),
            "product_title": product.title,
            "category_id": str(product.category_id) if product.category_id else None,
            "category": category_name,
            "sku": variant.sku,
            "options": variant.option_values or {},
            "barcode": barcode,
            "price": str(to_money(price)),
            "avg_cost": None if avg_cost is None else str(avg_cost),
            "on_hand": on_hand,
            "reserved": reserved,
            "reorder_level": level,
            "status": stock_status(on_hand, level),
            "stock_cost_value": None if cost_value is None else str(cost_value),
            "stock_retail_value": str(to_money(price * on_hand)),
        }

    @staticmethod
    async def summary(session: AsyncSession, tenant_id: UUID) -> dict:
        """Totals over EVERY active variant, not over the page the screen happens to show."""
        rows = await StockViewService.list_stock(session, tenant_id, limit=1000)
        out = low = pieces = unknown = 0
        cost_value = Decimal("0")
        retail_value = Decimal("0")
        for row in rows:
            pieces += row["on_hand"]
            out += row["status"] == "out"
            low += row["status"] == "low"
            retail_value += Decimal(row["stock_retail_value"])
            if row["stock_cost_value"] is None:
                unknown += 1
            else:
                cost_value += Decimal(row["stock_cost_value"])
        return {
            "variants": len(rows),
            "pieces": pieces,
            "out": out,
            "low": low,
            "alerts": out + low,
            "cost_value": str(to_money(cost_value)),
            "retail_value": str(to_money(retail_value)),
            "unknown_cost_variants": unknown,
        }

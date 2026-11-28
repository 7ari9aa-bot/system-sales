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

from sqlalchemy import and_, case, column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sql import arabic_regex
from app.applications.apparel.modules.catalog.models import Category, Product, ProductIdentifier, ProductVariant
from app.modules.errors import ValidationError
from app.applications.apparel.modules.inventory.stock_view import StockLevelService, StocktakeGateway, stock_status
from app.applications.apparel.modules.orders.money import to_money

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

# inventory's tables, declared light for the same reason: this read-model joins them with the
# catalog, and importing inventory.models from here would be one more pos -> inventory edge for
# four column names. inventory still owns the schema; the two tests below pin the shapes together.
InventoryBalance = table(  # noqa: N816
    "inventory_balances",
    column("tenant_id"),
    column("variant_id"),
    column("on_hand"),
    column("reserved"),
    column("quarantined"),
)
VariantStockSetting = table(  # noqa: N816
    "variant_stock_settings",
    column("tenant_id"),
    column("variant_id"),
    column("reorder_level"),
)

# A scan code a person would print on a label: prefer a retail code over an internal token.
_BARCODE_PRIORITY = ("ean", "gtin", "upc", "barcode")
# These name the item to the tax authority (Egypt's e-receipt); they are on no label and nobody
# scans them, so they must never be passed off as the item's barcode.
_NOT_A_SCAN_CODE = frozenset({"egs", "gs1"})


class StockViewService:
    @staticmethod
    async def set_reorder_level(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID, level: int
    ) -> int:
        """Save a variant's reorder level and answer with what the database now holds.

        The router goes through here so `pos` reaches `inventory.stock_view` from ONE file.
        """
        await StockLevelService.set_reorder_level(session, tenant_id, variant_id, level)
        return await StockLevelService.get_reorder_level(session, tenant_id, variant_id)

    @staticmethod
    async def set_reorder_level_for_product(
        session: AsyncSession, tenant_id: UUID, product_id: UUID, level: int
    ) -> int:
        """One reorder level for a whole model (a size run); returns how many sizes took it."""
        return await StockLevelService.set_reorder_level_for_product(
            session, tenant_id, product_id, level
        )

    # ---- physical stocktake: pos reaches inventory through THIS file only ---------------------

    @staticmethod
    async def list_stocktakes(session, tenant_id, *, limit=20):
        return await StocktakeGateway.list_recent(session, tenant_id, limit=limit)

    @staticmethod
    async def open_default_stocktake(session, tenant_id, *, user_id, note):
        return await StocktakeGateway.open_default(session, tenant_id, user_id=user_id, note=note)

    @staticmethod
    async def stocktake_detail(session, tenant_id, stocktake_id):
        return await StocktakeGateway.detail(session, tenant_id, stocktake_id)

    @staticmethod
    async def record_stocktake_counts(session, tenant_id, stocktake_id, counts):
        return await StocktakeGateway.record_counts(session, tenant_id, stocktake_id, counts)

    @staticmethod
    async def approve_stocktake(session, tenant_id, stocktake_id, *, user_id):
        return await StocktakeGateway.approve(session, tenant_id, stocktake_id, user_id=user_id)

    @staticmethod
    async def cancel_stocktake(session, tenant_id, stocktake_id, *, user_id):
        await StocktakeGateway.cancel(session, tenant_id, stocktake_id, user_id=user_id)

    @staticmethod
    def _stock_query(
        tenant_id: UUID,
        *,
        term: str | None = None,
        category_id: UUID | None = None,
        brand_id: UUID | None = None,
        season: str | None = None,
        material: str | None = None,
        status: str | None = None,
    ):
        """The filtered stock view, UNBOUNDED.

        One builder feeds the page, the count and the summary, so a filter typed on screen narrows
        the export and the totals exactly as it narrows the grid. The old summary called the page
        reader with ``limit=1000``: a shop with 2,500 variants read totals for the first 1,000 and
        exported the same 1,000, with nothing on screen saying the rest existed.
        """
        if status is not None and status not in {"in", "low", "out"}:
            raise ValidationError("status must be one of in, low, out")
        wanted_season = (season or "").strip()
        wanted_material = (material or "").strip()

        held = (
            select(
                InventoryBalance.c.variant_id.label("variant_id"),
                func.coalesce(func.sum(InventoryBalance.c.on_hand), 0).label("on_hand"),
                func.coalesce(func.sum(InventoryBalance.c.reserved), 0).label("reserved"),
                func.coalesce(func.sum(InventoryBalance.c.quarantined), 0).label("quarantined"),
            )
            .where(InventoryBalance.c.tenant_id == tenant_id)
            .group_by(InventoryBalance.c.variant_id)
            .subquery()
        )
        level = func.coalesce(VariantStockSetting.c.reorder_level, 0)
        on_hand = func.coalesce(held.c.on_hand, 0)
        quarantined = func.coalesce(held.c.quarantined, 0)
        sellable = func.greatest(0, on_hand - quarantined)
        query = (
            select(
                ProductVariant,
                Product,
                Category.name.label("category_name"),
                on_hand.label("on_hand"),
                func.coalesce(held.c.reserved, 0).label("reserved"),
                quarantined.label("quarantined"),
                sellable.label("sellable"),
                level.label("reorder_level"),
                VariantCost.c.avg_cost.label("avg_cost"),
            )
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(Category, Category.id == Product.category_id)
            .outerjoin(held, held.c.variant_id == ProductVariant.id)
            .outerjoin(
                VariantStockSetting,
                (VariantStockSetting.c.variant_id == ProductVariant.id)
                & (VariantStockSetting.c.tenant_id == tenant_id),
            )
            .outerjoin(
                VariantCost,
                (VariantCost.c.variant_id == ProductVariant.id)
                & (VariantCost.c.tenant_id == tenant_id),
            )
            .where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.is_active.is_(True),
                # Archiving sets the product's status, not its variants'. The grid and its totals
                # therefore kept counting an archived product forever, so the piece that was
                # archived away stayed on the shelf on screen. A missing status reads as draft.
                func.coalesce(Product.status, "draft") != "archived",
            )
            .order_by(Product.title, ProductVariant.sku, ProductVariant.id)
        )
        if category_id is not None:
            query = query.where(Product.category_id == category_id)
        if brand_id is not None:
            query = query.where(Product.brand_id == brand_id)
        if wanted_season:
            # Same rule as the product list: SS26, ss26 and ' SS26' are one season.
            query = query.where(func.lower(Product.season) == wanted_season.lower())
        if wanted_material:
            # Same rule again: قطن,  قطن and ' COTTON ' are one fabric.
            query = query.where(func.lower(Product.material) == wanted_material.lower())
        if term and term.strip():
            spelled = arabic_regex(term)
            codes = (
                select(ProductIdentifier.variant_id)
                .where(
                    ProductIdentifier.tenant_id == tenant_id,
                    ProductIdentifier.value.op("~*")(spelled),
                )
                .scalar_subquery()
            )
            query = query.where(
                Product.title.op("~*")(spelled)
                | func.coalesce(ProductVariant.sku, "").op("~*")(spelled)
                | ProductVariant.id.in_(codes)
            )
        if status == "out":
            query = query.where(on_hand <= 0)
        elif status == "low":
            query = query.where(on_hand > 0, on_hand <= level)
        elif status == "in":
            query = query.where(on_hand > 0, on_hand > level)
        return query

    @staticmethod
    async def list_stock(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        term: str | None = None,
        category_id: UUID | None = None,
        brand_id: UUID | None = None,
        season: str | None = None,
        material: str | None = None,
        status: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        query = StockViewService._stock_query(
            tenant_id,
            term=term,
            category_id=category_id,
            brand_id=brand_id,
            season=season,
            material=material,
            status=status,
        )
        rows = (await session.execute(query.limit(limit).offset(offset))).all()
        barcodes = await StockViewService._barcodes(session, tenant_id, [r[0].id for r in rows])
        return [StockViewService._row(r, barcodes.get(r[0].id)) for r in rows]

    @staticmethod
    async def count_stock(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        term: str | None = None,
        category_id: UUID | None = None,
        brand_id: UUID | None = None,
        season: str | None = None,
        material: str | None = None,
        status: str | None = None,
    ) -> int:
        """How many rows the SAME filters match, without reading them."""
        query = StockViewService._stock_query(
            tenant_id,
            term=term,
            category_id=category_id,
            brand_id=brand_id,
            season=season,
            material=material,
            status=status,
        )
        stmt = select(func.count()).select_from(query.order_by(None).subquery())
        return int((await session.execute(stmt)).scalar_one())

    @staticmethod
    async def list_stock_page(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        term: str | None = None,
        category_id: UUID | None = None,
        brand_id: UUID | None = None,
        season: str | None = None,
        material: str | None = None,
        status: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> dict:
        """One window of the view PLUS the total, so a screen or export can say what it left out.

        ``has_more`` is computed from the total, not guessed from the page being full: the last
        full page of a 2,000-row shop must not promise a page that does not exist.
        """
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        filters = {
            "term": term,
            "category_id": category_id,
            "brand_id": brand_id,
            "season": season,
            "material": material,
            "status": status,
        }
        total = await StockViewService.count_stock(session, tenant_id, **filters)
        items = await StockViewService.list_stock(
            session, tenant_id, limit=limit, offset=offset, **filters
        )
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(items) < total,
        }

    @staticmethod
    async def names_for(
        session: AsyncSession, tenant_id: UUID, variant_ids: list[UUID]
    ) -> dict[UUID, tuple[str | None, str | None]]:
        """``{variant_id: (product title, sku)}``: the labels a report row shows."""
        if not variant_ids:
            return {}
        found = (
            await session.execute(
                select(ProductVariant.id, Product.title, ProductVariant.sku)
                .join(Product, Product.id == ProductVariant.product_id)
                .where(ProductVariant.tenant_id == tenant_id, ProductVariant.id.in_(variant_ids))
            )
        ).all()
        return {vid: (title, sku) for vid, title, sku in found}

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
            if kind in _NOT_A_SCAN_CODE:
                continue
            rank = _BARCODE_PRIORITY.index(kind) if kind in _BARCODE_PRIORITY else 99
            if variant_id not in best or rank < best[variant_id][0]:
                best[variant_id] = (rank, value)
        return {k: v[1] for k, v in best.items()}

    @staticmethod
    def _row(r, barcode: str | None) -> dict:
        (
            variant,
            product,
            category_name,
            on_hand,
            reserved,
            quarantined,
            sellable,
            level,
            avg_cost,
        ) = r
        on_hand, reserved, quarantined, sellable, level = (
            int(on_hand),
            int(reserved),
            int(quarantined),
            int(sellable),
            int(level),
        )
        price = Decimal(variant.price)
        cost_value = None if avg_cost is None else to_money(Decimal(avg_cost) * on_hand)
        available = max(0, sellable - reserved)
        return {
            "variant_id": str(variant.id),
            "product_id": str(product.id),
            "product_title": product.title,
            "category_id": str(product.category_id) if product.category_id else None,
            "category": category_name,
            "brand_id": str(product.brand_id) if product.brand_id else None,
            "season": product.season,
            "material": product.material,
            "sku": variant.sku,
            "options": variant.option_values or {},
            "barcode": barcode,
            "price": str(to_money(price)),
            "avg_cost": None if avg_cost is None else str(avg_cost),
            "on_hand": on_hand,
            "quarantined": quarantined,
            "sellable": sellable,
            "reserved": reserved,
            "available": available,
            "reorder_level": level,
            "status": stock_status(sellable, level),
            "stock_cost_value": None if cost_value is None else str(cost_value),
            "stock_retail_value": str(to_money(price * on_hand)),
        }

    @staticmethod
    async def summary(session: AsyncSession, tenant_id: UUID) -> dict:
        """Totals over EVERY active variant, in ONE aggregate.

        This used to sum ``list_stock(limit=1000)``: the docstring said "every variant" but the
        number was the first 1,000, so a 2,500-variant shop read shelf values and alert counts for
        40% of its stock with no hint that the rest was missing. The aggregate runs over the same
        joins with no page, and the status rule is the same CASE as ``stock_status``.
        """
        held = (
            select(
                InventoryBalance.c.variant_id.label("variant_id"),
                func.coalesce(func.sum(InventoryBalance.c.on_hand), 0).label("on_hand"),
                func.coalesce(func.sum(InventoryBalance.c.quarantined), 0).label("quarantined"),
            )
            .where(InventoryBalance.c.tenant_id == tenant_id)
            .group_by(InventoryBalance.c.variant_id)
            .subquery()
        )
        on_hand = func.coalesce(held.c.on_hand, 0)
        quarantined = func.coalesce(held.c.quarantined, 0)
        sellable = func.greatest(0, on_hand - quarantined)
        level = func.coalesce(VariantStockSetting.c.reorder_level, 0)
        base = (
            select(
                ProductVariant.id.label("variant_id"),
                on_hand.label("on_hand"),
                sellable.label("sellable"),
                level.label("reorder_level"),
                VariantCost.c.avg_cost.label("avg_cost"),
                ProductVariant.price.label("price"),
            )
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(held, held.c.variant_id == ProductVariant.id)
            .outerjoin(
                VariantStockSetting,
                (VariantStockSetting.c.variant_id == ProductVariant.id)
                & (VariantStockSetting.c.tenant_id == tenant_id),
            )
            .outerjoin(
                VariantCost,
                (VariantCost.c.variant_id == ProductVariant.id)
                & (VariantCost.c.tenant_id == tenant_id),
            )
            .where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.is_active.is_(True),
                func.coalesce(Product.status, "draft") != "archived",
            )
            .subquery()
        )
        b = base.c
        out = b.sellable <= 0
        low = and_(b.sellable > 0, b.sellable <= b.reorder_level)
        row = (
            await session.execute(
                select(
                    func.count().label("variants"),
                    func.coalesce(func.sum(b.on_hand), 0).label("pieces"),
                    func.coalesce(func.sum(case((out, 1), else_=0)), 0).label("out"),
                    func.coalesce(func.sum(case((low, 1), else_=0)), 0).label("low"),
                    func.coalesce(func.sum(case((b.avg_cost.is_(None), 1), else_=0)), 0).label(
                        "unknown"
                    ),
                    func.coalesce(func.sum(b.avg_cost * b.on_hand), 0).label("cost_value"),
                    func.coalesce(func.sum(b.price * b.on_hand), 0).label("retail_value"),
                ).select_from(base)
            )
        ).one()
        out_count, low_count = int(row.out), int(row.low)
        return {
            "variants": int(row.variants),
            "pieces": int(row.pieces),
            "out": out_count,
            "low": low_count,
            "alerts": out_count + low_count,
            "cost_value": str(to_money(Decimal(row.cost_value or 0))),
            "retail_value": str(to_money(Decimal(row.retail_value or 0))),
            "unknown_cost_variants": int(row.unknown),
        }

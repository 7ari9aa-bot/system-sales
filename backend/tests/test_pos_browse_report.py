"""§189 phase 3/4 — the till's catalog grid and the shift report.

DB-free guards (routes mounted, browse validation) run everywhere; DB-backed
tests (grid pricing vs the sell price, stock column, the report's arithmetic)
run on CI and are reported UNVERIFIED when only local runs were possible.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.main import create_app

ITEMS_PATH = "/api/v1/pos/sessions/{session_id}/items"
REPORT_PATH = "/api/v1/pos/sessions/{session_id}/report"


# --------------------------------------------------------- DB-free guards --


def test_browse_and_report_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {ITEMS_PATH, REPORT_PATH} <= paths


# ----------------------------------------------------------- DB-backed -----


async def _warehouse(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService

    return await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)


async def _register(db, tenant_ctx):
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    return await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )


async def _sellable_variant(db, tenant_ctx, title="كوباية", price="25.00", stock=7):
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    warehouse = await _warehouse(db, tenant_ctx)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title=title, slug=f"p-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="سعة كبيرة", price=price
    )
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=stock,
        reason="purchase",
    )
    return variant


async def _customer(db, tenant_ctx):
    from app.modules.customers.service import CustomerService

    return await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون", source="pos"
    )


async def test_browse_shows_price_and_stock(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)

    page = await PosService.browse(db, tenant_ctx.tenant_id, pos_session.id)
    assert page["total"] >= 1
    mine = next(item for item in page["items"] if item["variant_id"] == str(variant.id))
    assert mine["unit_price"] == "25.00"
    assert mine["available"] == 7


async def test_browse_searches_by_title_and_skips_unsellable(db, tenant_ctx):
    from app.modules.catalog.service import CatalogService
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx, title="برادة قهوة")
    # A draft product never reaches the grid — the same sellability rule the
    # scan enforces.
    draft = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="برادة شاي", slug=f"d-{uuid.uuid4().hex[:10]}"
    )
    await CatalogService.add_variant(db, tenant_ctx.tenant_id, draft.id, title="علبة", price="9.00")

    found = await PosService.browse(db, tenant_ctx.tenant_id, pos_session.id, q="برادة")
    # The active product matches through its product title; the draft does not.
    assert any(item["variant_id"] == str(variant.id) for item in found["items"])
    assert found["total"] == 1

    by_scan = await PosService.browse(db, tenant_ctx.tenant_id, pos_session.id, q="برادة قهوة")
    assert any(item["variant_id"] == str(variant.id) for item in by_scan["items"])


async def test_report_reconciles_the_day(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opening_float="20.00"
    )
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        tenders=[
            {"method": "cash", "amount": "30.00"},
            {"method": "card", "amount": "20.00"},
        ],
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        restock=True,
    )
    live = await PosService.session_report(db, tenant_ctx.tenant_id, pos_session.id)
    assert live["sales"]["invoice_count"] == 1
    assert Decimal(live["sales"]["total"]) == Decimal("50.00")
    assert Decimal(live["returns"]["total"]) == Decimal("25.00")
    # The user's own example: opening 20 + invoices 50 - returns 25 = 45. One line each.
    assert Decimal(live["opening_balance"]) == Decimal("20.00")
    assert Decimal(live["net_sales"]) == Decimal("25.00")
    assert Decimal(live["closing_balance"]) == Decimal("45.00")
    assert live["returns"]["documents"][0]["total"] == "25.00"
    assert live["exchanges"]["exchange_count"] == 0
    assert "by_method" not in live and "variance_total" not in live

    await PosService.close_session(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
    )
    closed = await PosService.session_report(db, tenant_ctx.tenant_id, pos_session.id)
    assert closed["session"]["status"] == "CLOSED"
    assert Decimal(closed["closing_balance"]) == Decimal("45.00")  # same figure once closed
    assert closed["returns"]["return_count"] == 1

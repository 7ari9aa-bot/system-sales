"""Tests for Inventory and Purchasing router endpoints."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

import app.applications.apparel.modules.purchasing.models  # noqa: F401
from app.applications.apparel.modules.catalog.models import Product, ProductVariant
from app.modules.identity.deps import TenantContext
from app.applications.apparel.modules.inventory.models import Warehouse
from app.applications.apparel.modules.inventory.router import (
    InspectionCompleteRequest,
    InspectionCreateRequest,
    InspectionResultRequest,
    LandedCostCreateRequest,
    LocationCreateRequest,
    PolicySetRequest,
    TransferCreateRequest,
    TransferLineIn,
    complete_inspection,
    create_inspection,
    create_landed_cost,
    create_transfer,
    create_warehouse_location,
    get_inspection,
    get_transfer,
    get_valuation,
    list_replenishment_policies,
    list_transfers,
    list_warehouse_locations,
    record_inspection_result,
    set_replenishment_policy,
)
from app.applications.apparel.modules.purchasing.router import (
    GoodsReceiptIn,
    GoodsReceiptLineIn,
    PoIn,
    PoLineIn,
    create_goods_receipt,
    create_purchase_order,
    list_goods_receipts_for_po,
    post_goods_receipt,
)
from app.applications.apparel.modules.purchasing.service import SupplierService


def _ctx(db, tenant_ctx) -> TenantContext:
    return TenantContext(
        session=db,
        user=tenant_ctx.user,
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"inventory:read", "inventory:write"},
    )


@pytest.mark.asyncio
async def test_inventory_location_routes(db, tenant_ctx):
    ctx = _ctx(db, tenant_ctx)
    tid = tenant_ctx.tenant_id
    # A warehouse location is refused while inventory.track_locations is off (its default):
    # create_warehouse_location reads that setting and raises. This test is about the routes, so
    # it switches tracking on the way an owner does instead of meeting the gate.
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

    await SettingsService(db, tid).set("inventory.track_locations", True, scope=Scope.TENANT)

    wh = Warehouse(tenant_id=tid, name="WH-A", code="WHA", is_active=True)
    db.add(wh)
    await db.flush()

    # Create location
    req = LocationCreateRequest(name="Bin 01", code="B-01", kind="bin")
    loc = await create_warehouse_location(wh.id, req, ctx)
    assert loc.code == "B-01"
    assert loc.name == "Bin 01"

    # List locations
    locs = await list_warehouse_locations(wh.id, ctx)
    assert len(locs) == 1
    assert locs[0].id == loc.id


@pytest.mark.asyncio
async def test_inventory_inspection_routes(db, tenant_ctx):
    ctx = _ctx(db, tenant_ctx)
    tid = tenant_ctx.tenant_id

    wh = Warehouse(tenant_id=tid, name="WH-Insp", code="WHINSP", is_active=True)
    prod = Product(tenant_id=tid, title="T-Shirt", slug="t-shirt-insp", status="active")
    db.add_all([wh, prod])
    await db.flush()

    var = ProductVariant(
        tenant_id=tid, product_id=prod.id, sku="TSHIRT-WHT", title="White", price=Decimal("150")
    )
    db.add(var)
    await db.flush()

    # 1. Create inspection
    insp_req = InspectionCreateRequest(source_type="goods_receipt", warehouse_id=wh.id)
    insp = await create_inspection(insp_req, ctx)
    insp_id = uuid.UUID(insp["id"])

    # 2. Get inspection
    got = await get_inspection(insp_id, ctx)
    assert got["status"] == "open"

    # 3. Record result
    res_req = InspectionResultRequest(
        variant_id=var.id,
        quantity=10,
        verdict="pass",
    )
    await record_inspection_result(insp_id, res_req, ctx)

    # 4. Complete inspection
    comp_req = InspectionCompleteRequest(verdict="passed")
    done = await complete_inspection(insp_id, comp_req, ctx)
    assert done["status"] == "passed"


@pytest.mark.asyncio
async def test_inventory_transfers_routes(db, tenant_ctx):
    ctx = _ctx(db, tenant_ctx)
    tid = tenant_ctx.tenant_id

    wh1 = Warehouse(tenant_id=tid, name="WH-Origin", code="WHORIGIN", is_active=True)
    wh2 = Warehouse(tenant_id=tid, name="WH-Dest", code="WHDEST", is_active=True)
    prod = Product(tenant_id=tid, title="Cap", slug="cap-tr", status="active")
    db.add_all([wh1, wh2, prod])
    await db.flush()

    var = ProductVariant(
        tenant_id=tid, product_id=prod.id, sku="CAP-BLK", title="Black", price=Decimal("80")
    )
    db.add(var)
    await db.flush()

    # Create transfer
    tr_req = TransferCreateRequest(
        from_warehouse_id=wh1.id,
        to_warehouse_id=wh2.id,
        lines=[TransferLineIn(variant_id=var.id, quantity=10)],
    )
    tr = await create_transfer(tr_req, ctx)
    tr_id = uuid.UUID(tr["id"])

    # List & get transfer
    tr_list = await list_transfers(ctx)
    assert len(tr_list) >= 1
    got_tr = await get_transfer(tr_id, ctx)
    assert got_tr["status"] == "draft"


@pytest.mark.asyncio
async def test_inventory_replenishment_and_valuation_routes(db, tenant_ctx):
    ctx = _ctx(db, tenant_ctx)
    tid = tenant_ctx.tenant_id

    wh = Warehouse(tenant_id=tid, name="WH-Rep", code="WHREP", is_active=True)
    prod = Product(tenant_id=tid, title="Shoes", slug="shoes-rep", status="active")
    db.add_all([wh, prod])
    await db.flush()

    var = ProductVariant(
        tenant_id=tid, product_id=prod.id, sku="SHOE-42", title="Size 42", price=Decimal("500")
    )
    db.add(var)
    await db.flush()

    # Replenishment policy
    pol_req = PolicySetRequest(
        variant_id=var.id,
        warehouse_id=wh.id,
        min_stock=5,
        max_stock=25,
    )
    pol = await set_replenishment_policy(pol_req, ctx)
    assert pol["min_stock"] == 5

    policies = await list_replenishment_policies(ctx, warehouse_id=wh.id)
    assert len(policies) == 1

    # Valuation
    val = await get_valuation(ctx)
    assert "total_valuation" in val

    # Landed Cost
    lc_req = LandedCostCreateRequest(
        warehouse_id=wh.id,
        total=Decimal("1500.00"),
        note="Customs Clearance",
    )
    lc = await create_landed_cost(lc_req, ctx)
    assert lc["status"] == "draft"


@pytest.mark.asyncio
async def test_purchasing_goods_receipt_routes(db, tenant_ctx):
    ctx = _ctx(db, tenant_ctx)
    tid = tenant_ctx.tenant_id

    wh = Warehouse(tenant_id=tid, name="WH-GR", code="WHGR", is_active=True)
    sup = await SupplierService.create(db, tid, name="Atlas Garments")
    prod = Product(tenant_id=tid, title="Hoodie", slug="hoodie-gr", status="active")
    db.add_all([wh, prod])
    await db.flush()

    var = ProductVariant(
        tenant_id=tid, product_id=prod.id, sku="HOOD-GRY", title="Grey", price=Decimal("350")
    )
    db.add(var)
    await db.flush()

    # Create PO
    po_in = PoIn(
        supplier_id=sup.id,
        warehouse_id=wh.id,
        order_date="2026-11-17",
        lines=[PoLineIn(variant_id=var.id, quantity="50", unit_cost="100.00")],
    )
    po = await create_purchase_order(po_in, ctx)
    po_id = uuid.UUID(po.id)

    # Fetch PO line id
    from app.applications.apparel.modules.purchasing.service import PurchaseService

    po_lines = await PurchaseService._lines_in(db, tid, po_id)
    po_line_id = po_lines[0].id

    # Create Goods Receipt via router
    gr_in = GoodsReceiptIn(
        lines=[
            GoodsReceiptLineIn(
                purchase_order_line_id=po_line_id,
                variant_id=var.id,
                quantity=30,
                unit_cost="100.00",
                condition="good",
            )
        ],
        note="First delivery",
    )
    gr = await create_goods_receipt(po_id, gr_in, ctx)
    assert gr.status == "draft"
    assert gr.number.startswith("GR-")
    assert len(gr.lines) == 1
    assert gr.lines[0].quantity == 30

    gr_id = uuid.UUID(gr.id)

    # Post Goods Receipt via router
    posted_gr = await post_goods_receipt(gr_id, ctx)
    assert posted_gr.status == "posted"

    # List receipts for PO
    receipts = await list_goods_receipts_for_po(po_id, ctx)
    assert len(receipts) == 1
    assert receipts[0].id == gr.id


@pytest.mark.asyncio
async def test_apparel_insights_route(db, tenant_ctx):
    ctx = _ctx(db, tenant_ctx)
    from app.applications.apparel.modules.inventory.router import get_apparel_insights

    res = await get_apparel_insights(ctx, days=30)
    assert "top_selling_variants" in res
    assert "stockout_risk_variants" in res
    assert "branch_rebalance_opportunities" in res

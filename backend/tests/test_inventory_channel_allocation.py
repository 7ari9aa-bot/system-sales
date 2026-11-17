"""Tests for Inventory Channel Allocation (§4 Phase 7).

Ensures stock quotas per sales channel (e.g. website, pos, whatsapp) prevent overselling
and that availability accurately reflects channel limits.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.purchasing.models  # noqa: F401
from app.modules.catalog.models import Product
from app.modules.catalog.service import CatalogService
from app.modules.identity.deps import TenantContext
from app.modules.inventory.models import Warehouse
from app.modules.inventory.router import (
    ChannelAllocationIn,
    delete_channel_allocation,
    get_channel_availability,
    get_checkout_traceability,
    list_channel_allocations,
    mark_serials_returned,
    mark_serials_sold,
    set_channel_allocation,
)
from app.modules.inventory.service import (
    ChannelAllocationService,
    InsufficientStockError,
    InventoryService,
    TraceabilityService,
)
from app.modules.orders.service import OrderService


def _ctx(db, tenant_ctx) -> TenantContext:
    return TenantContext(
        session=db,
        user=tenant_ctx.user,
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"inventory:read", "inventory:write", "orders:read", "orders:write"},
    )


@pytest.mark.asyncio
async def test_channel_allocation_quota_and_exceed_limits(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh = Warehouse(tenant_id=tid, name="Central Hub", code="HUB1", is_active=True)
    db.add(wh)
    await db.flush()

    prod = await CatalogService.create_product(
        db, tid, title="Silk Shirt", slug=f"shirt-{uuid.uuid4().hex[:6]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="120.00")

    # Add 10 units of physical stock
    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=10, reason="purchase"
    )

    # Allocate 6 units to website
    alloc_web = await ChannelAllocationService.set_allocation(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website", quantity=6
    )
    assert alloc_web.channel == "website"
    assert alloc_web.allocated_quantity == 6
    assert alloc_web.reserved_in_channel == 0

    # Allocate 4 units to pos
    alloc_pos = await ChannelAllocationService.set_allocation(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="pos", quantity=4
    )
    assert alloc_pos.allocated_quantity == 4

    # Allocating 1 more to whatsapp exceeds the sellable 10
    with pytest.raises(InsufficientStockError, match="would exceed sellable stock"):
        await ChannelAllocationService.set_allocation(
            db, tid, warehouse_id=wh.id, variant_id=var.id, channel="whatsapp", quantity=1
        )

    # Reducing website allocation from 6 to 5
    alloc_web = await ChannelAllocationService.set_allocation(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website", quantity=5
    )
    assert alloc_web.allocated_quantity == 5

    # Now allocating 1 to whatsapp succeeds
    alloc_wa = await ChannelAllocationService.set_allocation(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="whatsapp", quantity=1
    )
    assert alloc_wa.allocated_quantity == 1


@pytest.mark.asyncio
async def test_channel_availability_and_reservation_flow(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh = Warehouse(tenant_id=tid, name="Store 1", code="ST1", is_active=True)
    db.add(wh)
    await db.flush()

    prod = await CatalogService.create_product(
        db, tid, title="Denim Jacket", slug=f"jacket-{uuid.uuid4().hex[:6]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="250.00")

    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=8, reason="purchase"
    )

    # Allocate 5 to website and 3 to pos
    await ChannelAllocationService.set_allocation(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website", quantity=5
    )
    await ChannelAllocationService.set_allocation(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="pos", quantity=3
    )

    # Check website availability
    avail_web = await ChannelAllocationService.get_channel_availability(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website"
    )
    assert avail_web["available_quantity"] == 5
    assert avail_web["allocated_quantity"] == 5
    assert avail_web["global_available"] == 8

    # Reserve 4 units in website
    await InventoryService.reserve(db, tid, var.id, wh.id, quantity=4, channel="website")

    # Website now has 1 available; pos still has 3 available
    avail_web2 = await ChannelAllocationService.get_channel_availability(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website"
    )
    assert avail_web2["available_quantity"] == 1
    assert avail_web2["reserved_in_channel"] == 4

    avail_pos = await ChannelAllocationService.get_channel_availability(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="pos"
    )
    assert avail_pos["available_quantity"] == 3

    # Attempting to reserve 2 in website is refused (only 1 left in website quota)
    with pytest.raises(InsufficientStockError, match="cannot reserve 2 in channel 'website'"):
        await InventoryService.reserve(db, tid, var.id, wh.id, quantity=2, channel="website")

    # But pos can reserve its 3 units
    await InventoryService.reserve(db, tid, var.id, wh.id, quantity=3, channel="pos")

    # Release 2 from website
    await InventoryService.release(db, tid, var.id, wh.id, quantity=2, channel="website")
    avail_web3 = await ChannelAllocationService.get_channel_availability(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website"
    )
    assert avail_web3["available_quantity"] == 3
    assert avail_web3["reserved_in_channel"] == 2


@pytest.mark.asyncio
async def test_channel_allocation_orders_integration(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh = Warehouse(tenant_id=tid, name="Main Store", code="MS1", is_active=True)
    db.add(wh)
    await db.flush()

    prod = Product(
        tenant_id=tid, title="Sneakers", slug=f"snk-{uuid.uuid4().hex[:6]}", status="active"
    )
    db.add(prod)
    await db.flush()
    var = await CatalogService.add_variant(db, tid, prod.id, price="500.00")

    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=10, reason="purchase"
    )

    # Allocate 2 to website, 8 to pos
    await ChannelAllocationService.set_allocation(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website", quantity=2
    )

    from app.modules.customers.service import CustomerService

    cust, _ = await CustomerService.find_or_create_by_phone(
        db, tid, phone="+201012345678", name="Online Shopper"
    )

    # Create website order for 2 pairs
    order = await OrderService.create_order(
        db,
        tid,
        customer_id=cust.id,
        items=[{"variant_id": str(var.id), "quantity": 2, "price": "500.00"}],
        channel="website",
        warehouse_id=wh.id,
    )
    assert order.status in ("pending", "created")

    # Website quota is now fully reserved (2/2)
    avail_web = await ChannelAllocationService.get_channel_availability(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website"
    )
    assert avail_web["available_quantity"] == 0

    # Cancelling order releases the channel allocation
    await OrderService.cancel_order(db, tid, order.id)

    avail_web_after = await ChannelAllocationService.get_channel_availability(
        db, tid, warehouse_id=wh.id, variant_id=var.id, channel="website"
    )
    assert avail_web_after["available_quantity"] == 2


@pytest.mark.asyncio
async def test_channel_allocation_router_endpoints(db: AsyncSession, tenant_ctx):
    ctx = _ctx(db, tenant_ctx)
    tid = tenant_ctx.tenant_id
    wh = Warehouse(tenant_id=tid, name="Router WH", code="RWH", is_active=True)
    db.add(wh)
    await db.flush()

    prod = await CatalogService.create_product(
        db, tid, title="Belt", slug=f"belt-{uuid.uuid4().hex[:6]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="50.00")

    await InventoryService.move(
        db, tid, var.id, wh.id, direction="in", quantity=15, reason="purchase"
    )

    # POST channel-allocations
    body = ChannelAllocationIn(warehouse_id=wh.id, variant_id=var.id, channel="pos", quantity=10)
    alloc = await set_channel_allocation(body, ctx)
    assert alloc.channel == "pos"
    assert alloc.allocated_quantity == 10

    # GET channel-allocations
    rows = await list_channel_allocations(ctx, warehouse_id=wh.id, variant_id=var.id)
    assert len(rows) == 1
    assert rows[0].channel == "pos"

    # GET channel-availability
    avail = await get_channel_availability(
        ctx, warehouse_id=wh.id, variant_id=var.id, channel="pos"
    )
    assert avail.available_quantity == 10
    assert avail.global_available == 15

    # DELETE channel-allocations
    del_res = await delete_channel_allocation(alloc.id, ctx)
    assert del_res == {"ok": True}

    rows_after = await list_channel_allocations(ctx, warehouse_id=wh.id, variant_id=var.id)
    assert len(rows_after) == 0


@pytest.mark.asyncio
async def test_checkout_traceability_and_serials_endpoints(db: AsyncSession, tenant_ctx):
    ctx = _ctx(db, tenant_ctx)
    tid = tenant_ctx.tenant_id

    prod = await CatalogService.create_product(
        db, tid, title="Laptop", slug=f"lap-{uuid.uuid4().hex[:6]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="15000.00")

    # Configure serial tracking
    await TraceabilityService.set_tracking_policy(db, tid, variant_id=var.id, mode="serial")
    await TraceabilityService.register_serials(
        db, tid, variant_id=var.id, serial_codes=["SN-001", "SN-002"]
    )

    # Check checkout traceability
    trace_info = await get_checkout_traceability(var.id, ctx)
    assert trace_info["mode"] == "serial"
    assert len(trace_info["serials"]) == 2
    assert trace_info["serials"][0]["serial_code"] in ("SN-001", "SN-002")

    # Mark SN-001 as sold
    from app.modules.inventory.router import MarkSerialsRequest

    sold_res = await mark_serials_sold(var.id, MarkSerialsRequest(serial_codes=["SN-001"]), ctx)
    assert sold_res["ok"] is True

    # Remaining in_stock serials should be 1
    trace_info2 = await get_checkout_traceability(var.id, ctx)
    assert len(trace_info2["serials"]) == 1
    assert trace_info2["serials"][0]["serial_code"] == "SN-002"

    # Mark returned
    ret_res = await mark_serials_returned(var.id, MarkSerialsRequest(serial_codes=["SN-001"]), ctx)
    assert ret_res["ok"] is True

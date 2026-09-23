"""§153 regression — outbox events carry the aggregate's REAL version.

W0.5: every event staged for one aggregate must carry that aggregate row's
post-mutation ``version`` (VersionMixin), so consumers can order the stream
per aggregate. Before the fix the call sites passed hardcoded literals
(1/2/3) regardless of the row's actual version — so the assertions below
fail on the literal values (e.g. a second ``order.status_changed`` was
published with ``aggregate_version=2`` while the row was already at 3).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import Order
from app.modules.orders.service import OrderService
from app.modules.platform.models import OutboxEvent
from app.modules.privacy.service import DeletionService


async def _customer_variant_stock(db: AsyncSession, tenant_id: uuid.UUID, stock: int = 10):
    """Mirror test_order_service's setup: customer + stocked variant."""
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="Test Buyer",
        phone=f"+2010{uuid.uuid4().hex[:8]}",
    )
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Version WH",
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    product = await CatalogService.create_product(
        db, tenant_id, title="Widget", slug=f"w-{uuid.uuid4().hex[:10]}"
    )
    # §M4: only an `active` product sells, so the seeded cart is a sellable one.
    # The product row is not an aggregate this test observes — the order and
    # customer versions it asserts are untouched by publishing a product.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"WGT-{uuid.uuid4().hex[:6].upper()}", price="25.50"
    )
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=stock,
        reason="purchase",
    )
    return customer, variant


async def _fresh_events(
    db: AsyncSession, aggregate_id: uuid.UUID, seen: set[uuid.UUID]
) -> list[OutboxEvent]:
    """Outbox rows for the aggregate not seen yet — emission order, tracked by
    id because every row in one transaction shares the same created_at."""
    rows = list(
        (
            await db.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == aggregate_id)
            )
        ).scalars().all()
    )
    fresh = [row for row in rows if row.id not in seen]
    seen.update(row.id for row in fresh)
    return fresh


async def test_order_events_carry_the_rows_real_increasing_versions(
    db: AsyncSession, tenant_ctx
) -> None:
    """create → mutate → mutate: the three order events must equal the order
    row's real version history (1, 2, 3), not hardcoded literals."""
    tenant_id = tenant_ctx.tenant_id
    customer, variant = await _customer_variant_stock(db, tenant_id, stock=10)
    seen: set[uuid.UUID] = set()

    # 1) create — a fresh row starts at VersionMixin's initial version.
    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 2}],
        channel="whatsapp",
        shipping_address={"city": "Cairo"},
    )
    db_version = (
        await db.execute(select(Order.version).where(Order.id == order.id))
    ).scalar_one()
    created = await _fresh_events(db, order.id, seen)
    assert [e.payload["event_type"] for e in created] == ["order.created"]
    assert [e.meta["aggregate_version"] for e in created] == [db_version]

    # 2) first state change — If-Match drives apply_versioned_update, so the
    # row really moves to the next version.
    order = await OrderService.change_status(
        db, tenant_id, order.id, "confirmed", expected_version=str(db_version)
    )
    step1 = await _fresh_events(db, order.id, seen)
    assert [e.payload["event_type"] for e in step1] == ["order.status_changed"]
    assert order.version == db_version + 1
    assert [e.meta["aggregate_version"] for e in step1] == [order.version]

    # 3) second state change — the defect shows here: the call site hardcoded
    # ``aggregate_version=2`` for EVERY status change, but the row is now at 3.
    order = await OrderService.change_status(
        db, tenant_id, order.id, "processing", expected_version=str(order.version)
    )
    step2 = await _fresh_events(db, order.id, seen)
    assert [e.payload["event_type"] for e in step2] == ["order.status_changed"]
    assert order.version == db_version + 2
    assert [e.meta["aggregate_version"] for e in step2] == [order.version]

    # The per-aggregate stream IS the row's version history: strictly
    # increasing and matching the versions the row actually held.
    versions = [e.meta["aggregate_version"] for e in [*created, *step1, *step2]]
    assert versions == [db_version, db_version + 1, db_version + 2]
    assert versions == sorted(set(versions)), "versions must strictly increase"


async def test_privacy_events_carry_the_customers_real_version(
    db: AsyncSession, tenant_ctx
) -> None:
    """Both privacy events name the customer aggregate; they must carry the
    customer row's REAL version — the tombstone path never bumps it, so the
    literal ``3`` the second call site passed was pure fiction."""
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="Erase Me",
        phone=f"+2010{uuid.uuid4().hex[:8]}",
    )

    await DeletionService.propagate_customer_deletion(
        db, tenant_id, customer.id, requested_by_user_id=tenant_ctx.user.id
    )

    db_version = (
        await db.execute(select(Customer.version).where(Customer.id == customer.id))
    ).scalar_one()
    events = list(
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "customer",
                    OutboxEvent.aggregate_id == customer.id,
                )
            )
        ).scalars().all()
    )
    assert {e.payload["event_type"] for e in events} == {
        "privacy.customer_purge_required",
        "privacy.customer_deleted",
    }
    for event in events:
        assert event.meta["aggregate_version"] == db_version

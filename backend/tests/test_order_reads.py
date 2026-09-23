"""M8 — reading an order the way staff read it.

The order write surface is closed out (shipments, returns, payments, refunds);
what was missing was the *read* half: a list you can filter by the three things
a merchant actually searches for (this customer, this number, this date range),
the payments of one order, its status timeline, and the ability to correct the
shipping details on an order that is still open.

Every filter here stays inside the tenant scope the endpoint already applies —
a filter that widened visibility would be worse than no filter.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.orders.service import OrderService
from app.modules.platform.models import AuditLog

# ------------------------------------------------------------------ fixtures ----


async def _variant(db: AsyncSession, tenant_id: uuid.UUID, *, sku: str | None = None):
    """A *sellable* product (published) with one priced variant.

    The product is activated on purpose: §M4 refuses draft/archived goods at
    checkout, so a fixture that left the row at its `draft` default would be
    testing something else entirely.
    """
    product = await CatalogService.create_product(
        db, tenant_id, title="Reads", slug=f"r-{uuid.uuid4().hex[:10]}"
    )
    await CatalogService.update_product(
        db, tenant_id, product.id, status="active"
    )
    return await CatalogService.add_variant(
        db,
        tenant_id,
        product.id,
        sku=sku or f"R-{uuid.uuid4().hex[:6].upper()}",
        price="40.00",
    )


async def _buyer(db: AsyncSession, tenant_id: uuid.UUID):
    return await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Buyer"
    )


async def _order(
    db: AsyncSession, tenant_id: uuid.UUID, *, customer=None, qty: int = 1
):
    variant = await _variant(db, tenant_id)
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        (await InventoryService.get_default_warehouse(db, tenant_id)).id,
        direction="in",
        quantity=10,
        reason="purchase",
    )
    return await OrderService.create_order(
        db,
        tenant_id,
        (customer or await _buyer(db, tenant_id)).id,
        [{"variant_id": variant.id, "quantity": qty}],
    )


async def _stamp(db: AsyncSession, order_id: uuid.UUID, when: datetime) -> None:
    """Pin created_at so a date-range filter has something to bite on."""
    await db.execute(
        text("UPDATE orders SET created_at = :when WHERE id = :id"),
        {"when": when, "id": order_id},
    )
    await db.flush()


async def _stored(db: AsyncSession, order_id: uuid.UUID) -> Order:
    """Re-read the row. `version` is a server default, so the instance checkout
    handed back may not carry it."""
    return (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()


# ------------------------------------------------------- the route surface ----


_MOUNTED = [
    ("/api/v1/orders/{order_id}/payments", ["get"]),
    ("/api/v1/orders/{order_id}/status-history", ["get"]),
    ("/api/v1/orders/{order_id}/shipping", ["patch"]),
]


@pytest.mark.parametrize("path,methods", _MOUNTED)
def test_order_read_and_correction_routes_are_mounted(path: str, methods: list[str]):
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    assert path in paths, f"{path} is not mounted"
    for method in methods:
        assert method in paths[path], f"{method.upper()} {path} is missing"


def test_the_order_list_advertises_the_staff_filters():
    """`GET /orders` without a number/date filter is not a search box."""
    from app.main import create_app

    params = {
        p["name"]
        for p in create_app().openapi()["paths"]["/api/v1/orders"]["get"]["parameters"]
    }
    assert {"status", "customer_id", "number", "created_from", "created_to"} <= params


def test_the_number_filter_escapes_like_wildcards():
    from app.modules.orders.service import like_pattern

    assert like_pattern("100%_off") == "%100\\%\\_off%"


def test_a_naive_date_bound_is_read_as_utc():
    """The column is timestamptz; a bound without an offset is UTC, not local."""
    from app.modules.orders.service import to_utc_bound

    naive = datetime(2026, 1, 2, 3, 4, 5)
    assert to_utc_bound(naive) == naive.replace(tzinfo=UTC)
    aware = naive.replace(tzinfo=timezone(timedelta(hours=-5)))
    assert to_utc_bound(aware) == aware


# ------------------------------------------------------------ list filters ----


async def test_filtering_by_customer_returns_only_that_customer(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    anna = await _buyer(db, tenant_id)
    beshoy = await _buyer(db, tenant_id)
    anna_order = await _order(db, tenant_id, customer=anna)
    await _order(db, tenant_id, customer=beshoy)

    all_rows = await OrderService.list_orders(db, tenant_id)
    assert len(all_rows) == 2  # the filter below has something to exclude

    rows = await OrderService.list_orders(db, tenant_id, customer_id=anna.id)
    assert [o.id for o in rows] == [anna_order.id]
    await db.flush()


async def test_filtering_by_number_is_partial_and_case_insensitive(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    first = await _order(db, tenant_id)
    second = await _order(db, tenant_id)
    tail = first.number.split("-")[-1]

    rows = await OrderService.list_orders(db, tenant_id, number=tail.lower())
    assert [o.id for o in rows] == [first.id]
    # The other order is really there — the empty-ish result above is the
    # filter working, not the table being empty.
    assert second.number != first.number
    assert await OrderService.list_orders(db, tenant_id, number=second.number) == [
        second
    ]
    assert await OrderService.list_orders(db, tenant_id, number="no-such-number") == []
    await db.flush()


async def test_the_date_range_bounds_are_inclusive(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    base = datetime(2026, 3, 1, tzinfo=UTC)
    old, mid, recent = await _order(db, tenant_id), await _order(db, tenant_id), await _order(
        db, tenant_id
    )
    await _stamp(db, old.id, base)
    await _stamp(db, mid.id, base + timedelta(days=10))
    await _stamp(db, recent.id, base + timedelta(days=20))

    mid_ts = base + timedelta(days=10)
    outside = base + timedelta(days=15)

    # Both bounds inclusive: the same instant on both sides still returns the
    # order that sits exactly on it.
    assert {
        o.id
        for o in await OrderService.list_orders(
            db, tenant_id, created_from=mid_ts, created_to=mid_ts
        )
    } == {mid.id}
    assert {
        o.id for o in await OrderService.list_orders(db, tenant_id, created_to=mid_ts)
    } == {old.id, mid.id}
    assert {
        o.id
        for o in await OrderService.list_orders(db, tenant_id, created_from=mid_ts)
    } == {mid.id, recent.id}
    # ... and a window that contains no stamp contains no order.
    assert (
        await OrderService.list_orders(
            db, tenant_id, created_from=outside, created_to=outside
        )
        == []
    )
    await db.flush()


async def test_a_foreign_tenant_reads_nothing_through_the_new_filters(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    stranger = uuid.uuid4()

    assert await OrderService.list_orders(db, stranger, number=order.number) == []
    assert await OrderService.list_orders(
        db, stranger, customer_id=order.customer_id
    ) == []
    assert await OrderService.list_orders(
        db, stranger, created_from=datetime.now(UTC) - timedelta(days=1)
    ) == []
    await db.flush()


# ------------------------------------------------- payments / history reads ----


async def test_list_payments_returns_the_order_s_payments(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    paid = await _order(db, tenant_id, qty=2)
    unpaid = await _order(db, tenant_id)
    payment = await OrderService.add_payment(
        db, tenant_id, paid.id, method="cash", amount=Decimal("80.00")
    )

    rows = await OrderService.list_payments(db, tenant_id, paid.id)
    assert [p.id for p in rows] == [payment.id]
    assert rows[0].status == "captured"
    assert await OrderService.list_payments(db, tenant_id, unpaid.id) == []
    await db.flush()


async def test_payments_are_not_readable_through_another_tenant(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await OrderService.add_payment(
        db, tenant_id, order.id, method="cash", amount=Decimal("40.00")
    )

    with pytest.raises(NotFoundError):
        await OrderService.list_payments(db, uuid.uuid4(), order.id)
    await db.flush()


async def test_status_history_is_the_order_s_timeline_in_order(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await OrderService.change_status(db, tenant_id, order.id, "confirmed")
    await OrderService.change_status(db, tenant_id, order.id, "processing")

    # Three transitions inside ONE transaction share now(), so the read's
    # ORDER BY is only observable once the rows carry distinct stamps.
    base = datetime(2026, 4, 1, tzinfo=UTC)
    timeline = [None, "pending", "confirmed"]
    for step, from_status in enumerate(timeline):
        row = (
            await db.execute(
                select(OrderStatusHistory).where(
                    OrderStatusHistory.order_id == order.id,
                    OrderStatusHistory.from_status.is_(None)
                    if from_status is None
                    else OrderStatusHistory.from_status == from_status,
                )
            )
        ).scalar_one()
        await db.execute(
            text("UPDATE order_status_history SET created_at = :when WHERE id = :id"),
            {"when": base + timedelta(minutes=step), "id": row.id},
        )
    await db.flush()

    rows = await OrderService.list_status_history(db, tenant_id, order.id)
    assert [(h.from_status, h.to_status) for h in rows] == [
        (None, "pending"),
        ("pending", "confirmed"),
        ("confirmed", "processing"),
    ]
    assert rows[0].changed_by_user_id is None
    await db.flush()


async def test_status_history_is_not_readable_through_another_tenant(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)

    with pytest.raises(NotFoundError):
        await OrderService.list_status_history(db, uuid.uuid4(), order.id)
    assert (
        await db.execute(
            select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
        )
    ).scalars().all() != []
    await db.flush()


# --------------------------------------------------------- shipping update ----


async def test_shipping_update_replaces_the_address_and_bumps_the_version(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    warehouse_id = order.extra["warehouse_id"]
    before = (await _stored(db, order.id)).version

    updated = await OrderService.update_shipping(
        db,
        tenant_id,
        order.id,
        shipping_address={"city": "Alexandria", "street": "Rami 12"},
        shipping_method="courier",
        by_user_id=tenant_ctx.user.id,
    )
    await db.flush()

    row = await _stored(db, order.id)
    assert updated.shipping_address == {"city": "Alexandria", "street": "Rami 12"}
    assert updated.version == before + 1
    # The claim is about the stored row, not the object handed back.
    assert row.shipping_address == {"city": "Alexandria", "street": "Rami 12"}
    assert row.version == before + 1
    # A method the model has no column for rides in `extra` — see update_shipping
    # — and merging it there must not drop what was already in that JSONB.
    assert row.extra["shipping_method"] == "courier"
    assert row.extra["warehouse_id"] == warehouse_id
    await db.flush()


async def test_shipping_update_is_written_not_merged(db: AsyncSession, tenant_ctx):
    """An address is a whole value: a second PUT cannot keep the old streets."""
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await OrderService.update_shipping(
        db, tenant_id, order.id, shipping_address={"city": "Cairo", "street": "Tahrir 9"}
    )
    updated = await OrderService.update_shipping(
        db, tenant_id, order.id, shipping_address={"city": "Suez"}
    )
    assert updated.shipping_address == {"city": "Suez"}
    await db.flush()


async def test_shipping_update_records_an_audit_entry(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    await OrderService.update_shipping(
        db,
        tenant_id,
        order.id,
        shipping_address={"city": "Giza"},
        by_user_id=tenant_ctx.user.id,
    )

    rows = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "order",
                AuditLog.resource_id == str(order.id),
                AuditLog.action == "order.shipping_updated",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_id
    assert rows[0].actor_user_id == tenant_ctx.user.id
    assert rows[0].after["shipping_address"] == {"city": "Giza"}
    await db.flush()


async def test_shipping_update_refuses_a_stale_version(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    version = (await _stored(db, order.id)).version

    with pytest.raises(ConflictError):
        await OrderService.update_shipping(
            db,
            tenant_id,
            order.id,
            shipping_address={"city": "Giza"},
            expected_version=str(version + 5),
        )
    await db.flush()


async def test_shipping_update_refuses_an_order_that_already_left(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)
    for status in ("confirmed", "processing", "shipped"):
        await OrderService.change_status(db, tenant_id, order.id, status)

    with pytest.raises(ConflictError):
        await OrderService.update_shipping(
            db, tenant_id, order.id, shipping_address={"city": "Giza"}
        )
    await db.flush()


async def test_shipping_update_requires_something_to_change(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)

    with pytest.raises(ValidationError):
        await OrderService.update_shipping(db, tenant_id, order.id)
    await db.flush()


async def test_a_foreign_tenant_cannot_touch_an_order_s_shipping(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id
    order = await _order(db, tenant_id)

    with pytest.raises(NotFoundError):
        await OrderService.update_shipping(
            db, uuid.uuid4(), order.id, shipping_address={"city": "Nowhere"}
        )
    with pytest.raises(NotFoundError):
        await OrderService.update_shipping(
            db, uuid.uuid4(), order.id, shipping_method="courier"
        )
    await db.flush()


async def test_the_shipping_write_requires_the_write_permission(
    db: AsyncSession, tenant_ctx
):
    """A write route without the gate re-dispatches a parcel for anyone."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

    ctx = TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes=set(),  # no orders:write
    )

    async def _fake_ctx() -> TenantContext:
        return ctx

    app = create_app()
    app.dependency_overrides[get_tenant_ctx] = _fake_ctx
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            f"/api/v1/orders/{uuid.uuid4()}/shipping",
            json={"shipping_address": {"city": "Cairo"}},
        )
        assert response.status_code == 403, response.text

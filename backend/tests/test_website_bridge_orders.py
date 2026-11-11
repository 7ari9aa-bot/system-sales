"""Website-platform orders, phase 3: a Fihrist Sites storefront books an order in Fihrist.

Fihrist is the source of truth, so what these tests pin is what would cost a merchant money:

- the PRICE is Fihrist's, never the storefront's (the body cannot even carry one);
- the stock is reserved here, and a cart that cannot be filled in full books NOTHING and holds
  NOTHING (no half order, no stock stuck on a refused one);
- a retried POST (a lost response) returns the first order and reserves nothing a second time;
- the customer is matched by phone, not duplicated, and a blocked customer cannot order;
- one tenant's variant can never be bought through another tenant's key.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from app.core.errors import DomainError
from app.modules.catalog.service import CatalogService
from app.modules.customers.services.customer import CustomerService
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders import website_orders as bridge
from app.modules.orders.models import Order, OrderItem


async def _stocked_variant(db, tenant_id, *, price="100.00", on_hand=10):
    product = await CatalogService.create_product(
        db, tenant_id, title="Shirt", slug=f"p-{uuid.uuid4().hex[:10]}"
    )
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price=price)
    wh = Warehouse(tenant_id=tenant_id, name="WH", code=f"WH-{uuid.uuid4().hex[:6].upper()}")
    db.add(wh)
    await db.flush()
    await InventoryService.move(
        db, tenant_id, variant.id, wh.id, direction="in", quantity=on_hand, reason="purchase"
    )
    return variant, wh


def _body(variant_id, *, qty=1, ref=None, phone="+201001234567", name="Mona"):
    return bridge.WebsiteOrderIn(
        external_ref=ref or f"web-{uuid.uuid4().hex[:8]}",
        customer={"name": name, "phone": phone},
        items=[{"variant_id": str(variant_id), "quantity": qty}],
    )


async def _place(db, tenant_id, body):
    return await bridge.website_platform_create_order(body=body, key_tenant=tenant_id, db=db)


async def _available(db, tenant_id, variant_id) -> int:
    from sqlalchemy import text

    row = (
        await db.execute(
            text(
                "SELECT COALESCE(SUM(GREATEST(on_hand - reserved, 0)), 0) FROM inventory_balances "
                "WHERE variant_id = :v"
            ),
            {"v": variant_id},
        )
    ).scalar_one()
    return int(row)


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_the_order_is_priced_from_fihrists_catalog(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t, price="125.50")
    out = await _place(db, t, _body(variant.id, qty=3))
    assert out.already_received is False
    assert out.subtotal == Decimal("376.50")  # 3 x 125.50 from OUR price, not the storefront's
    assert out.grand_total == Decimal("376.50")
    order = (await db.execute(select(Order).where(Order.id == out.order_id))).scalar_one()
    assert order.channel == "website" and order.status == "pending"


async def test_a_storefront_cannot_name_a_price(db, tenant_ctx) -> None:
    variant, _ = await _stocked_variant(db, tenant_ctx.tenant_id)
    with pytest.raises(PydanticValidationError):
        bridge.WebsiteOrderIn(
            external_ref="r1",
            customer={"name": "A", "phone": "+201001234567"},
            items=[{"variant_id": str(variant.id), "quantity": 1, "unit_price": "1.00"}],
        )
    with pytest.raises(PydanticValidationError):
        bridge.WebsiteOrderIn(
            external_ref="r2",
            customer={"name": "A", "phone": "+201001234567"},
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            grand_total="1.00",
        )


async def test_stock_is_reserved_in_fihrist(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t, on_hand=10)
    await _place(db, t, _body(variant.id, qty=4))
    assert await _available(db, t, variant.id) == 6


async def test_more_than_is_in_stock_is_refused_and_books_nothing(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t, on_hand=2)
    before = await _count(db, Order)
    with pytest.raises(DomainError):
        await _place(db, t, _body(variant.id, qty=3))
    assert await _count(db, Order) == before
    assert await _available(db, t, variant.id) == 2  # nothing held by the refused order


async def test_one_unfillable_line_refuses_the_whole_cart_and_holds_no_stock(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    plenty, _ = await _stocked_variant(db, t, on_hand=10)
    scarce, _ = await _stocked_variant(db, t, on_hand=1)
    body = bridge.WebsiteOrderIn(
        external_ref="mixed-1",
        customer={"name": "A", "phone": "+201001234567"},
        items=[
            {"variant_id": str(plenty.id), "quantity": 5},
            {"variant_id": str(scarce.id), "quantity": 2},
        ],
    )
    with pytest.raises(DomainError):
        await _place(db, t, body)
    assert await _available(db, t, plenty.id) == 10  # the fillable line was NOT kept
    assert await _available(db, t, scarce.id) == 1


async def test_a_retry_returns_the_first_order_and_reserves_nothing_twice(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t, on_hand=10)
    body = _body(variant.id, qty=3, ref="ORDER-77")
    first = await _place(db, t, body)
    second = await _place(db, t, body)
    assert second.already_received is True
    assert second.order_id == first.order_id and second.number == first.number
    assert await _available(db, t, variant.id) == 7  # 10 - 3, not 10 - 6
    assert await _count(db, Order) == 1


async def test_the_same_ref_with_a_different_cart_still_returns_the_first_order(
    db, tenant_ctx
) -> None:
    """The ref names the storefront's order. A retry that arrives with a different body is not a
    second order: it must not book more stock, and it gets the original back unchanged."""
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t, on_hand=10)
    first = await _place(db, t, _body(variant.id, qty=2, ref="R-1"))
    again = await _place(db, t, _body(variant.id, qty=9, ref="R-1"))
    assert again.order_id == first.order_id
    assert await _available(db, t, variant.id) == 8


async def test_the_customer_is_matched_by_phone_not_duplicated(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t, on_hand=10)
    await _place(db, t, _body(variant.id, phone="+201001234567", name="Mona"))
    await _place(db, t, _body(variant.id, phone="01001234567", name="Mona K"))  # same number
    orders = (await db.execute(select(Order))).scalars().all()
    assert len(orders) == 2
    assert orders[0].customer_id == orders[1].customer_id


async def test_a_blocked_customer_cannot_order_and_nothing_is_booked(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t, on_hand=10)
    customer, _ = await CustomerService.find_or_create_by_phone(
        db, t, phone="+201005550000", name="Blocked", source="test"
    )
    await CustomerService.set_blocked(db, t, customer.id, blocked=True)
    before = await _count(db, Order)
    with pytest.raises(Exception) as caught:
        await _place(db, t, _body(variant.id, phone="+201005550000"))
    assert getattr(caught.value, "status_code", None) == 422
    assert await _count(db, Order) == before
    assert await _available(db, t, variant.id) == 10


async def test_a_phone_that_is_not_a_phone_is_refused(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t)
    with pytest.raises(Exception) as caught:
        await _place(db, t, _body(variant.id, phone="not-a-number"))
    assert getattr(caught.value, "status_code", None) == 422
    assert await _count(db, Order) == 0


async def test_an_unknown_variant_is_refused(db, tenant_ctx) -> None:
    with pytest.raises(DomainError):
        await _place(db, tenant_ctx.tenant_id, _body(uuid.uuid4()))
    assert await _count(db, Order) == 0


async def test_the_order_keeps_its_lines_and_the_storefronts_reference(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    variant, _ = await _stocked_variant(db, t, price="40.00")
    out = await _place(db, t, _body(variant.id, qty=2, ref="SITE-ORDER-9"))
    order = (await db.execute(select(Order).where(Order.id == out.order_id))).scalar_one()
    assert order.external_ref == "SITE-ORDER-9"
    lines = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalars()
    lines = list(lines)
    assert len(lines) == 1 and lines[0].quantity == 2 and Decimal(str(lines[0].unit_price)) == 40


@pytest.mark.parametrize(
    "bad_ref", ["", "has space", "semi;colon", "x" * 81, "a/b", "emoji\U0001f600"]
)
def test_the_reference_is_a_plain_token(bad_ref) -> None:
    with pytest.raises(PydanticValidationError):
        bridge.WebsiteOrderIn(
            external_ref=bad_ref,
            customer={"name": "A", "phone": "+201001234567"},
            items=[{"variant_id": str(uuid.uuid4()), "quantity": 1}],
        )


@pytest.mark.parametrize("qty", [0, -1, 1001])
def test_quantity_is_bounded(qty) -> None:
    with pytest.raises(PydanticValidationError):
        bridge.WebsiteOrderIn(
            external_ref="r",
            customer={"name": "A", "phone": "+201001234567"},
            items=[{"variant_id": str(uuid.uuid4()), "quantity": qty}],
        )


def test_an_empty_cart_and_an_oversized_cart_are_refused() -> None:
    customer = {"name": "A", "phone": "+201001234567"}
    with pytest.raises(PydanticValidationError):
        bridge.WebsiteOrderIn(external_ref="r", customer=customer, items=[])
    too_many = [{"variant_id": str(uuid.uuid4()), "quantity": 1}] * 51
    with pytest.raises(PydanticValidationError):
        bridge.WebsiteOrderIn(external_ref="r", customer=customer, items=too_many)


# ---------------------------------------------------------------------------
# Real concurrency. The tests above run on ONE rolled-back connection, so they cannot show two
# requests in flight at once. A storefront retries on a timeout while the first attempt is still
# running, which is exactly the case where an application-level "have I seen this ref?" check
# passes for both and only the database can stop the second one.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.db import bind_tenant  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.modules.identity.models import Role, Tenant, TenantUser, User  # noqa: E402

_RACERS = 8


@pytest.fixture
async def committed_shop(db_url, admin_url):
    """A committed tenant with one variant holding 5 units; removed completely afterwards."""
    engine = create_async_engine(
        db_url, pool_size=_RACERS + 2, connect_args={"statement_cache_size": 0}
    )
    owner_engine = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    async with factory() as s:
        role = (await s.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()
        user = User(
            email=f"w-{uuid.uuid4().hex[:8]}@test.local",
            password_hash=hash_password("x-secret-pw"),
            full_name="W",
        )
        s.add_all([Tenant(id=tenant_id, slug=f"w-{uuid.uuid4().hex[:8]}", name="Race"), user])
        await s.flush()
        await s.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.id)})
        s.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role_id=role.id))
        await s.commit()
        user_id = user.id
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        variant, _wh = await _stocked_variant(s, tenant_id, on_hand=5)
        variant_id = variant.id
        await s.commit()
    try:
        yield factory, tenant_id, variant_id
    finally:
        # Owner role (BYPASSRLS): remove every row of this tenant from every table that has a
        # tenant_id, retrying until the foreign keys let go, then prove the tenant is gone.
        async with owner_engine.begin() as c:
            tables = [
                r[0]
                for r in (
                    await c.execute(
                        sa.text(
                            "SELECT table_name FROM information_schema.columns "
                            "WHERE table_schema='public' AND column_name='tenant_id' "
                            "AND table_name <> 'tenants'"
                        )
                    )
                ).all()
            ]
        pending = list(tables)
        for _ in range(len(tables) + 1):
            if not pending:
                break
            still = []
            for t in pending:
                try:
                    async with owner_engine.begin() as c:
                        await c.execute(
                            sa.text(f'DELETE FROM "{t}" WHERE tenant_id = :t'), {"t": tenant_id}
                        )
                except Exception:
                    still.append(t)
            pending = still
        async with owner_engine.begin() as c:
            await c.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
            gone = await c.execute(
                sa.text("DELETE FROM tenants WHERE id = :t RETURNING id"), {"t": tenant_id}
            )
            assert gone.first() is not None, "cleanup failed: the throw-away tenant is still there"
        await engine.dispose()
        await owner_engine.dispose()


async def _race(factory, tenant_id, body):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        try:
            out = await bridge.website_platform_create_order(body=body, key_tenant=tenant_id, db=s)
            await s.commit()
            return out
        except Exception as exc:
            await s.rollback()
            return exc


async def test_parallel_retries_of_one_ref_book_exactly_one_order_and_hold_stock_once(
    committed_shop,
) -> None:
    factory, tenant_id, variant_id = committed_shop
    body = _body(variant_id, qty=2, ref="RACE-SAME-REF")
    results = await asyncio.gather(*[_race(factory, tenant_id, body) for _ in range(_RACERS)])
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors
    assert len({r.order_id for r in results}) == 1  # every racer got the SAME order
    assert sum(1 for r in results if not r.already_received) == 1  # and only one created it
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        assert await _count(s, Order) == 1
        assert await _available(s, tenant_id, variant_id) == 3  # 5 - 2, held once, not 8 times


async def test_parallel_different_orders_never_oversell(committed_shop) -> None:
    """8 different customers each want 2 of a variant holding 5: at most 2 can be served."""
    factory, tenant_id, variant_id = committed_shop
    bodies = [
        _body(variant_id, qty=2, ref=f"RACE-{i}", phone=f"+2010099900{i:02d}")
        for i in range(_RACERS)
    ]
    results = await asyncio.gather(*[_race(factory, tenant_id, b) for b in bodies])
    booked = [r for r in results if not isinstance(r, Exception)]
    assert len(booked) == 2
    assert all(isinstance(r, DomainError) for r in results if isinstance(r, Exception))
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        assert await _count(s, Order) == 2
        assert await _available(s, tenant_id, variant_id) == 1  # 5 - 2*2, never negative

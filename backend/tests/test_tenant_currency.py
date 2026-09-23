"""W4-T3 (§47): money belongs to a tenant, and a total is computed.

§47 names two rules this system did not have. "كل monetary object يجب أن يخزن
amount_minor + currency، وليس floating point money", and for cross-currency
reporting the original amount is never rewritten — the rate is stored beside it.

The second half was already true here (every money column is ``NUMERIC``, every
value a ``Decimal``), so the missing substance is the first half applied to the
tenant: the currency was a literal ``"EGP"`` written into the code in eight
places, an order could not be anything else, and ``grand_total`` was a copy of
``subtotal`` — ``discount_total``, ``shipping_total`` and ``tax_total`` existed
as columns checkout always left at zero. A merchant who charges shipping
therefore invoiced it nowhere, and one who discounts it collected full price.

The decision this encodes (ADR-053): a tenant trades in ONE currency, chosen on
its own row. That is what makes a mixed currency a refusal rather than a
conversion, and why no FX table is needed — the stored amount is always the
amount the customer paid, in the only currency this tenant moves.
"""

from __future__ import annotations

import pathlib
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.events.schemas import deserialize
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError, ValidationError
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.identity.service import TenantSettingsService
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders import money as order_money
from app.modules.orders.models import Order, OrderItem
from app.modules.orders.service import OrderService

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _request(path: str = "/api/v1/orders") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


async def _stocked_variant(
    db: AsyncSession, tenant_id: uuid.UUID, *, price: str = "40.00", stock: int = 50
) -> tuple[object, Warehouse]:
    product = await CatalogService.create_product(
        db, tenant_id, title="Priced", slug=f"c-{uuid.uuid4().hex[:10]}"
    )
    # M4: only an active product sells, and this fixture is checkout's happy path.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db,
        tenant_id,
        product.id,
        price=price,
    )
    warehouse = Warehouse(
        tenant_id=tenant_id, name="Currency WH", code=f"CW-{uuid.uuid4().hex[:6].upper()}"
    )
    db.add(warehouse)
    await db.flush()
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=stock,
        reason="purchase",
    )
    return variant, warehouse


async def _buyer(db: AsyncSession, tenant_id: uuid.UUID) -> object:
    return await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Buyer"
    )


async def _lines(db: AsyncSession, order_id: uuid.UUID) -> list[tuple]:
    rows = (
        await db.execute(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.created_at, OrderItem.id)
        )
    ).scalars().all()
    return [(str(r.variant_id), r.quantity, r.unit_price, r.total) for r in rows]


# ======================================================= totals arithmetic ==
#
# Pure rules, so they run locally: the arithmetic checkout must not get wrong,
# exercised without a session (the same reason `orders/money.py` exists).


def test_grand_total_is_subtotal_minus_discount_plus_shipping_plus_tax() -> None:
    totals = order_money.compute_totals(
        subtotal="100.00", discount="15.00", shipping="20.00", tax="5.00"
    )
    assert totals["subtotal"] == Decimal("100.00")
    assert totals["grand_total"] == Decimal("110.00")


def test_grand_total_defaults_to_the_sum_of_its_parts_not_a_copy_of_subtotal() -> None:
    """The bug this replaces: checkout stored `grand_total = subtotal`."""
    totals = order_money.compute_totals(subtotal="40.00")
    assert totals["grand_total"] == Decimal("40.00")
    assert totals["discount_total"] == Decimal("0.00")
    assert totals["shipping_total"] == Decimal("0.00")
    assert totals["tax_total"] == Decimal("0.00")


def test_a_discount_larger_than_the_subtotal_is_refused() -> None:
    """A negative order total is not a refund, it is a data-entry mistake."""
    with pytest.raises(ValueError, match="discount"):
        order_money.compute_totals(subtotal="10.00", discount="25.00")


def test_a_negative_component_is_refused_rather_than_absorbed() -> None:
    for kwargs in (
        {"subtotal": "10.00", "discount": "-1.00"},
        {"subtotal": "10.00", "shipping": "-1.00"},
        {"subtotal": "10.00", "tax": "-1.00"},
    ):
        with pytest.raises(ValueError):
            order_money.compute_totals(**kwargs)


def test_every_component_is_quantized_to_the_storage_scale_before_summing() -> None:
    """The guard must reason about the number the column will actually hold."""
    totals = order_money.compute_totals(
        subtotal="10.004", discount="0.001", shipping="0.005", tax="0.0"
    )
    assert totals["subtotal"] == Decimal("10.00")
    assert totals["discount_total"] == Decimal("0.00")
    assert totals["shipping_total"] == Decimal("0.01")
    assert totals["grand_total"] == Decimal("10.01")


# ============================================================ minor units ==
#
# §47 stores minor units; this schema stores NUMERIC(14,2) and converts at the
# provider boundary (ADR-053). Both halves must agree on the currency's
# exponent, and `from_amount_minor` did not: it quantized every answer to two
# places, so a three-decimal currency came back wrong by design — the
# docstring promised `19.990` and the code returned `19.99`.


@pytest.mark.parametrize(
    "currency,exponent", [("EGP", 2), ("USD", 2), ("IQD", 3), ("JOD", 3), ("JPY", 0)]
)
def test_minor_units_round_trip_for_every_supported_exponent(
    currency: str, exponent: int
) -> None:
    quantum = Decimal(1).scaleb(-exponent)
    amount = Decimal("19.995").quantize(quantum)
    minor = order_money.amount_minor(amount, currency)
    assert minor == int(amount * (Decimal(10) ** exponent))
    assert order_money.from_amount_minor(minor, currency) == amount


def test_a_two_place_amount_is_not_inflated_by_the_minor_unit_conversion() -> None:
    """The regression guard: 19.99 EGP is 1999 piasters, not 19990."""
    assert order_money.amount_minor(Decimal("19.99"), "EGP") == 1999
    assert order_money.from_amount_minor(1999, "EGP") == Decimal("19.99")


# ================================================ the retired value object ==


def test_the_unused_money_value_object_is_gone() -> None:
    """``app/core/money.py`` had zero non-test importers for its whole life.

    Its ``Money(amount_minor)`` shape is not how this schema stores money, so
    keeping it meant two answers to "what is an amount". The rules that are
    actually used live in ``orders/money.py``.
    """
    assert not (BACKEND_ROOT / "app" / "core" / "money.py").exists()


# ============================================== one currency per tenant ====


async def test_a_tenant_row_declares_its_currency_and_defaults_to_egp(
    db: AsyncSession,
) -> None:
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Default Currency Co")
    db.add(tenant)
    await db.flush()
    assert tenant.currency == "EGP"


async def test_the_request_context_carries_the_tenant_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    """§47 read where it costs nothing.

    ``get_tenant_ctx`` already reads the tenant row for the §48 lifecycle gate,
    so the currency costs no extra round-trip and no new cross-module import —
    the module-boundary ratchet counts those.
    """
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    tenant.currency = "SAR"
    await db.flush()

    authed = AuthedUser(
        id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"
    )
    ctx = await get_tenant_ctx(_request("/api/v1/orders"), db, authed)
    assert ctx.currency == "SAR"


async def test_checkout_stamps_the_order_with_the_tenant_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    """Not "EGP" — the literal that was hard-coded at the insert."""
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    tenant.currency = "AED"
    await db.flush()

    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(db, tenant_ctx.tenant_id)
    order = await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 2}],
        warehouse_id=warehouse.id,
    )
    await db.flush()
    assert order.currency == "AED"


async def test_checkout_refuses_a_currency_the_tenant_does_not_trade_in(
    db: AsyncSession, tenant_ctx
) -> None:
    """§47 mixed-currency refusal: no rate applied, no silent rewrite."""
    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(db, tenant_ctx.tenant_id)

    with pytest.raises(ConflictError, match="USD"):
        await OrderService.create_order(
            db,
            tenant_ctx.tenant_id,
            customer.id,
            [{"variant_id": variant.id, "quantity": 1}],
            warehouse_id=warehouse.id,
            currency="USD",
        )


async def test_a_payment_in_another_currency_is_refused(
    db: AsyncSession, tenant_ctx
) -> None:
    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(db, tenant_ctx.tenant_id)
    order = await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 1}],
        warehouse_id=warehouse.id,
    )
    await db.flush()

    with pytest.raises(ConflictError, match="EUR"):
        await OrderService.add_payment(
            db,
            tenant_ctx.tenant_id,
            order.id,
            method="cash",
            amount=Decimal("40.00"),
            currency="EUR",
        )


# ================================================== the price ladder =======


async def test_checkout_prices_from_the_quantity_tier(
    db: AsyncSession, tenant_ctx
) -> None:
    """``ProductPrice`` was a table nothing read: tiers were written, ignored."""
    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(
        db, tenant_ctx.tenant_id, price="100.00"
    )
    await CatalogService.set_variant_price(
        db, tenant_ctx.tenant_id, variant.id, "85.00", min_quantity=5
    )

    order = await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 6}],
        warehouse_id=warehouse.id,
    )
    await db.flush()
    lines = await _lines(db, order.id)
    assert lines[0][2] == Decimal("85.00")
    assert order.subtotal == Decimal("510.00")


async def test_a_quantity_below_the_tier_pays_the_base_price(
    db: AsyncSession, tenant_ctx
) -> None:
    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(
        db, tenant_ctx.tenant_id, price="100.00"
    )
    await CatalogService.set_variant_price(
        db, tenant_ctx.tenant_id, variant.id, "85.00", min_quantity=5
    )

    order = await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 4}],
        warehouse_id=warehouse.id,
    )
    await db.flush()
    lines = await _lines(db, order.id)
    assert lines[0][2] == Decimal("100.00")


async def test_the_highest_applicable_tier_wins(db: AsyncSession, tenant_ctx) -> None:
    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(
        db, tenant_ctx.tenant_id, price="100.00"
    )
    await CatalogService.set_variant_price(
        db, tenant_ctx.tenant_id, variant.id, "90.00", min_quantity=3
    )
    await CatalogService.set_variant_price(
        db, tenant_ctx.tenant_id, variant.id, "75.00", min_quantity=10
    )

    order = await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 12}],
        warehouse_id=warehouse.id,
    )
    await db.flush()
    lines = await _lines(db, order.id)
    assert lines[0][2] == Decimal("75.00")


async def test_a_tier_in_another_currency_never_prices_this_tenants_order(
    db: AsyncSession, tenant_ctx
) -> None:
    """A USD tier on an EGP tenant is a different shop, not a discount.

    Inserted directly rather than through `set_variant_price`, because the write
    now refuses (§47) — this is the legacy row that already exists in a database
    written before that rule, and checkout must still ignore it.
    """
    from app.modules.catalog.models import ProductPrice

    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(
        db, tenant_ctx.tenant_id, price="100.00"
    )
    db.add(
        ProductPrice(
            tenant_id=tenant_ctx.tenant_id,
            variant_id=variant.id,
            currency="USD",
            unit_price=Decimal("1.50"),
            min_quantity=1,
        )
    )
    await db.flush()

    order = await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 2}],
        warehouse_id=warehouse.id,
    )
    await db.flush()
    lines = await _lines(db, order.id)
    assert lines[0][2] == Decimal("100.00")
    assert order.grand_total == Decimal("200.00")


async def test_a_price_tier_in_another_currency_is_refused_on_write(
    db: AsyncSession, tenant_ctx
) -> None:
    """A tier that can never be sold is not data, it is a future wrong invoice."""
    variant, _wh = await _stocked_variant(db, tenant_ctx.tenant_id, price="100.00")

    with pytest.raises(ConflictError, match="USD"):
        await CatalogService.set_variant_price(
            db, tenant_ctx.tenant_id, variant.id, "1.50", currency="USD"
        )
    await db.rollback()


# ============================== the components reach the order row =========


async def test_checkout_stores_the_components_it_was_given(
    db: AsyncSession, tenant_ctx
) -> None:
    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(db, tenant_ctx.tenant_id, price="50.00")

    order = await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 2}],
        warehouse_id=warehouse.id,
        discount_total="10.00",
        shipping_total="25.00",
        tax_total="5.00",
    )
    await db.flush()
    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.subtotal == Decimal("100.00")
    assert row.discount_total == Decimal("10.00")
    assert row.shipping_total == Decimal("25.00")
    assert row.tax_total == Decimal("5.00")
    assert row.grand_total == Decimal("120.00")


async def test_a_discount_past_the_subtotal_is_rejected_at_checkout(
    db: AsyncSession, tenant_ctx
) -> None:
    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(db, tenant_ctx.tenant_id, price="20.00")

    with pytest.raises(ValidationError):
        await OrderService.create_order(
            db,
            tenant_ctx.tenant_id,
            customer.id,
            [{"variant_id": variant.id, "quantity": 1}],
            warehouse_id=warehouse.id,
            discount_total="50.00",
        )
    await db.rollback()


async def test_the_outbox_event_carries_the_currency_that_was_stored(
    db: AsyncSession, tenant_ctx
) -> None:
    """The wire copy must not disagree with the row (§47's reporting half)."""
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    tenant.currency = "SAR"
    await db.flush()

    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(db, tenant_ctx.tenant_id, price="30.00")
    order = await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 1}],
        warehouse_id=warehouse.id,
        shipping_total="10.00",
    )
    await db.flush()

    row = (
        await db.execute(
            sa.text(
                "SELECT payload, meta FROM outbox_events WHERE aggregate_id = :oid "
                "AND payload->>'event_type' = 'order.created'"
            ),
            {"oid": str(order.id)},
        )
    ).scalar_one()
    # Read it the way a consumer does: money crosses the JSONB boundary tagged
    # with its type, so the assertion is against the decoded envelope, not the
    # raw column.
    envelope = deserialize({"payload": row.payload, "meta": row.meta})
    body = envelope.payload
    assert body["currency"] == "SAR"
    assert body["grand_total"] == Decimal("40.00")


# ============================ the tenant says what it trades in ============
#
# Every refusal above compares against `tenants.currency`, so the rule is only
# real if an owner can set that column. Before §47 the answer was a literal
# "EGP" in eight files: a Saudi shop's tiers, invoices, payments and money card
# all said Egyptian, and there was no setting anywhere to correct it.


async def test_the_owner_can_set_the_tenant_currency(db: AsyncSession, tenant_ctx) -> None:
    tenant = await TenantSettingsService.set_currency(
        db, tenant_ctx.tenant_id, "sar", actor_user_id=tenant_ctx.user.id
    )
    assert tenant.currency == "SAR"


async def test_an_unknown_currency_code_is_refused(db: AsyncSession, tenant_ctx) -> None:
    """A typo must not become a tenant that cannot be invoiced in."""
    with pytest.raises(ValidationError, match="XYZ"):
        await TenantSettingsService.set_currency(
            db, tenant_ctx.tenant_id, "XYZ", actor_user_id=tenant_ctx.user.id
        )


async def test_a_three_decimal_currency_is_refused_because_the_columns_hold_two(
    db: AsyncSession, tenant_ctx
) -> None:
    """IQD is quoted in fils, and a fil is a thousandth.

    Money is stored ``NUMERIC(14,2)`` on purpose, so accepting a three-decimal
    currency would round every price, order and refund to a fifth of its real
    minor unit — the ledger would disagree with the provider on every line. The
    refusal says so instead of quietly losing the difference.
    """
    with pytest.raises(ValidationError, match="IQD"):
        await TenantSettingsService.set_currency(
            db, tenant_ctx.tenant_id, "IQD", actor_user_id=tenant_ctx.user.id
        )


async def test_the_currency_change_leaves_an_audit_row(db: AsyncSession, tenant_ctx) -> None:
    from app.modules.platform.models import AuditLog

    await TenantSettingsService.set_currency(
        db, tenant_ctx.tenant_id, "SAR", actor_user_id=tenant_ctx.user.id
    )
    await db.flush()

    row = (
        await db.execute(
            sa.select(AuditLog)
            .where(
                AuditLog.tenant_id == tenant_ctx.tenant_id,
                AuditLog.action == "tenant.currency_changed",
            )
        )
    ).scalar_one()
    assert row.before == {"currency": "EGP"}
    assert row.after == {"currency": "SAR"}
    assert row.actor_user_id == tenant_ctx.user.id


async def test_a_tenant_that_has_traded_cannot_change_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    """Orders keep the currency they were sold in, so a switch would make every
    money aggregate a silent sum of two currencies."""
    customer = await _buyer(db, tenant_ctx.tenant_id)
    variant, warehouse = await _stocked_variant(db, tenant_ctx.tenant_id)
    await OrderService.create_order(
        db,
        tenant_ctx.tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 1}],
        warehouse_id=warehouse.id,
    )
    await db.flush()

    with pytest.raises(ConflictError, match="already traded"):
        await TenantSettingsService.set_currency(
            db, tenant_ctx.tenant_id, "SAR", actor_user_id=tenant_ctx.user.id
        )


async def test_a_tenant_may_still_set_its_own_default_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    """The guard is about CHANGING currency, not about the settings page."""
    await TenantSettingsService.set_currency(
        db, tenant_ctx.tenant_id, "EGP", actor_user_id=tenant_ctx.user.id
    )


# --------------------------------- the surface an owner actually calls --


def _settings_client(db: AsyncSession, tenant_ctx, perms: set[str]):
    """The real ASGI stack with only the auth dependency swapped, so the route,
    its gate and its contract are the things under test."""
    from app.main import create_app

    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"
            ),
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            permission_codes=perms,
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_the_settings_route_sets_the_tenants_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _settings_client(db, tenant_ctx, {"settings:read", "settings:write"}) as client:
        response = await client.put(
            f"/api/v1/tenants/{tenant_ctx.tenant_id}/currency", json={"currency": "SAR"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["currency"] == "SAR"

    stored = (
        await db.execute(select(Tenant.currency).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    assert stored == "SAR"


async def test_the_settings_route_refuses_a_writer_without_the_permission(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _settings_client(db, tenant_ctx, set()) as client:
        response = await client.put(
            f"/api/v1/tenants/{tenant_ctx.tenant_id}/currency", json={"currency": "SAR"}
        )
    assert response.status_code == 403, response.text

    stored = (
        await db.execute(select(Tenant.currency).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    assert stored == "EGP"

    stored = (
        await db.execute(select(Tenant.currency).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    assert stored == "EGP"

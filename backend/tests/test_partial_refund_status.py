"""Item B / gap M3's remaining half — an order that gave money back.

``payments`` learned ``refunded`` / ``partially_refunded`` and ``refunds`` rows
subtract the amount, but the ORDER still said ``completed`` for an order that
returned part of its price, so every screen that reads the order's own status
reported it next to one that never lost a pound.

The decision this file pins, and the reason for it: a partial refund is
DERIVED, not stored. ``status`` answers "where is this order in its life" —
the one axis ``TRANSITIONS``, ``_SAGA_ON_STATUS``, ``_SHIPPING_EDITABLE_STATUSES``
and ``RETURNABLE_STATUSES`` all read — and giving money back does not move the
goods anywhere. A partially refunded order is still ``shipped``, still
``processing``, still cancellable-or-not exactly as before; a refund is a
SECOND axis. The schema already encodes that reasoning for the other orthogonal
axis: ``status`` and ``process_state`` are two columns because one lifecycle
word cannot describe two things. ``money.net_collected`` and the payment rows
already answer "how much do we actually hold", so a stored
``partial_refunded`` status would be a derived fact with a second owner —
wrong the moment a refund is rejected, a second payment is partially refunded,
or a row is corrected by hand, and with no legal edge in ``TRANSITIONS`` back
out again.

So: the read side gets the field, ``orders/money.py`` stays the only rule set
that decides it, and analytics keeps counting the order it always counted (the
metric registry already says so: "refunds do not change an order's existence").

Structure: the first block is DB-free and runs locally; the rest is DB-backed
and runs in CI (skips locally without ``DATABASE_URL_APP_ADMIN``).
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.inventory.service import InventoryService
from app.modules.orders import money as orders_money
from app.modules.orders.models import Order
from app.modules.orders.service import TRANSITIONS, OrderService
from tests.test_order_idempotency import SessionStore, _build_app

# ------------------------------------------------- DB-free: the derivation ----


def test_the_refund_position_is_a_derived_state_not_a_status_word() -> None:
    """Three answers, from the money, with no session in sight.

    ``refunded`` on the gross side is what the state reads: the payment row is
    still money that ARRIVED (``SETTLED_PAYMENT_STATUSES`` deliberately keeps it
    there), and it is the refund rows that take it back.
    """
    assert orders_money.refund_state(Decimal("100.00"), Decimal("0.00")) == "none"
    assert orders_money.refund_state(Decimal("100.00"), Decimal("40.00")) == "partial"
    assert orders_money.refund_state(Decimal("100.00"), Decimal("100.00")) == "full"


def test_an_unpaid_order_has_not_been_refunded() -> None:
    """The zero/zero corner is the one a naive ``net <= 0`` test gets wrong: an
    order nobody has paid for holds nothing, but it gave nothing back either."""
    assert orders_money.refund_state(Decimal("0.00"), Decimal("0.00")) == "none"


def test_full_means_nothing_is_held_anymore_not_the_last_cent() -> None:
    """The boundary is the money position, quantized like every other figure."""
    assert orders_money.refund_state(Decimal("100.00"), Decimal("99.99")) == "partial"
    assert orders_money.refund_state(Decimal("100.00"), Decimal("100.01")) == "full"
    # An over-refunded ledger (a manual correction, a refund past the cap)
    # reads as fully given back — never as a negative order.
    assert orders_money.refund_state(Decimal("100.00"), Decimal("120.00")) == "full"


def test_the_refund_state_vocabulary_is_closed() -> None:
    """A read model with an open-ended field is a field every screen guesses at."""
    assert orders_money.REFUND_STATES == frozenset({"none", "partial", "full"})


def test_the_derivation_reads_net_collected_and_never_re_derives_it() -> None:
    """§47: ``net_collected`` is the only subtraction of refunds in the system.

    A second ``settled - refunded`` expression would be the bug: ``to_money``
    quantizes both sides there, and a rule that rounds differently in two places
    makes two screens disagree by a cent.
    """
    tree = ast.parse(pathlib.Path(orders_money.__file__).read_text(encoding="utf-8"))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "refund_state"
    )
    calls = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "net_collected" in calls, calls
    assert "Sub" not in _operators(fn), "refund_state re-derives the subtraction"


def test_no_order_status_was_invented_for_a_refund() -> None:
    """The machine that answers "where is this order" gains no money-only state.

    Adding ``partial_refunded`` to ``TRANSITIONS`` would make every status
    reader in the module a liar: an order could no longer say whether its
    parcel had left, and ``shipped -> partial_refunded -> shipped`` is not a
    lifecycle.
    """
    reachable = set(TRANSITIONS)
    for targets in TRANSITIONS.values():
        reachable |= targets
    assert "partial_refunded" not in reachable
    assert "partially_refunded" not in reachable
    # The lifecycle axis stays exactly the money-free vocabulary it was.
    assert reachable == {
        "pending",
        "confirmed",
        "processing",
        "shipped",
        "delivered",
        "completed",
        "cancelled",
        "returned",
        "refunded",
    }


def test_a_refunded_order_still_counts_as_an_order() -> None:
    """The registry's own words, pinned against the analytics filter it drives:
    net subtracts the money, the order's existence is untouched."""
    from app.modules.platform.metrics import MetricRegistry

    assert MetricRegistry.get("orders_count").filters["status_excluded"] == [
        "draft",
        "cancelled",
    ]
    assert MetricRegistry.get("orders_count").refund_treatment == "not_applicable"


def _operators(fn: ast.AST) -> str:
    return "".join(
        type(node.op).__name__
        for node in ast.walk(fn)
        if isinstance(node, ast.BinOp)
    )


# --------------------------------------------------------------- fixtures ----


async def _paid_order(
    db: AsyncSession, tenant_id: uuid.UUID, *, amount: str = "100.00", completed: bool = True
) -> Order:
    """A completed order with one captured payment of ``amount``."""
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Buyer"
    )
    product = await CatalogService.create_product(
        db, tenant_id, title="Refundable", slug=f"rf-{uuid.uuid4().hex[:10]}"
    )
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price=amount)
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        (await InventoryService.get_default_warehouse(db, tenant_id)).id,
        direction="in",
        quantity=5,
        reason="purchase",
    )
    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 1}],
    )
    await OrderService.add_payment(
        db, tenant_id, order.id, method="cash", amount=Decimal(amount)
    )
    if completed:
        for status in ("processing", "shipped", "delivered", "completed"):
            await OrderService.change_status(db, tenant_id, order.id, status)
    return order


async def _refund_part(
    db: AsyncSession, tenant_id: uuid.UUID, order: Order, amount: str
) -> None:
    payment = (await OrderService.list_payments(db, tenant_id, order.id))[0]
    await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount=Decimal(amount), reason="one line"
    )


# ---------------------------------------------------------------- DB tests ----


async def test_a_partially_refunded_order_reports_a_position_the_status_cannot(
    db: AsyncSession, tenant_ctx
) -> None:
    """40 back on a 100 order: still completed, and the money says 60 held."""
    tenant_id = tenant_ctx.tenant_id
    order = await _paid_order(db, tenant_id)
    await _refund_part(db, tenant_id, order, "40.00")
    await db.flush()

    position = await OrderService.refund_position(db, tenant_id, order.id)
    assert position["refund_state"] == "partial"
    assert position["order_status"] == "completed"
    assert position["gross_settled"] == Decimal("100.00")
    assert position["refunded"] == Decimal("40.00")
    assert position["net_collected"] == Decimal("60.00")
    # Never a float, and never a currency the row did not name (§47).
    assert all(
        isinstance(position[key], Decimal)
        for key in ("gross_settled", "refunded", "net_collected")
    )
    assert position["currency"] == order.currency


async def test_a_fully_refunded_and_a_partially_refunded_order_differ(
    db: AsyncSession, tenant_ctx
) -> None:
    """The whole point of the field: the two orders used to read the same."""
    tenant_id = tenant_ctx.tenant_id
    partial = await _paid_order(db, tenant_id)
    await _refund_part(db, tenant_id, partial, "40.00")
    whole = await _paid_order(db, tenant_id)
    await _refund_part(db, tenant_id, whole, "100.00")
    await db.flush()

    partial_position = await OrderService.refund_position(db, tenant_id, partial.id)
    whole_position = await OrderService.refund_position(db, tenant_id, whole.id)

    assert partial_position["refund_state"] == "partial"
    assert whole_position["refund_state"] == "full"
    assert whole_position["net_collected"] == Decimal("0.00")
    assert whole_position["refunded"] == Decimal("100.00")
    # The lifecycle half of the story is still the status's own, and the two
    # fields agree instead of one overwriting the other: a full refund on a
    # completed order closes it (that transition already exists and still fires).
    assert whole_position["order_status"] == "refunded"
    assert partial_position["order_status"] == "completed"
    assert (
        partial_position["refund_state"] != whole_position["refund_state"]
    ), "the two orders report identically"


async def test_an_unreduced_completed_order_numbers_are_untouched(
    db: AsyncSession, tenant_ctx
) -> None:
    """Nothing about an order nobody refunded moves because of this field."""
    tenant_id = tenant_ctx.tenant_id
    order = await _paid_order(db, tenant_id)
    await db.flush()

    position = await OrderService.refund_position(db, tenant_id, order.id)
    assert position["refund_state"] == "none"
    assert position["order_status"] == "completed"
    assert position["gross_settled"] == order.grand_total
    assert position["refunded"] == Decimal("0.00")
    assert position["net_collected"] == order.grand_total


async def test_a_rejected_refund_gives_nothing_back(
    db: AsyncSession, tenant_ctx
) -> None:
    """The stored-status design could not express this without a second write.

    A refund row that was rejected asserts no money left, so the position must
    read exactly as it did before the paperwork — derived, so it is always true.
    """
    tenant_id = tenant_ctx.tenant_id
    order = await _paid_order(db, tenant_id)
    payment = (await OrderService.list_payments(db, tenant_id, order.id))[0]
    await _refund_part(db, tenant_id, order, "40.00")
    await db.flush()
    assert (
        await OrderService.refund_position(db, tenant_id, order.id)
    )["refund_state"] == "partial"

    from app.modules.orders.models import Refund

    row = (
        await db.execute(
            Refund.__table__.update()
            .where(Refund.payment_id == payment.id)
            .values(status="rejected")
        )
    )
    assert row.rowcount == 1
    await db.flush()

    position = await OrderService.refund_position(db, tenant_id, order.id)
    assert position["refunded"] == Decimal("0.00")
    assert position["refund_state"] == "none"


async def test_the_order_detail_route_carries_the_derived_position(
    db: AsyncSession, tenant_ctx
) -> None:
    """A read-side field a route does not expose is a field no screen can show."""
    tenant_id = tenant_ctx.tenant_id
    order = await _paid_order(db, tenant_id)
    await _refund_part(db, tenant_id, order, "25.00")
    await db.flush()
    app = _build_app(store=SessionStore(db), tenant_id=tenant_id, session=db)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/orders/{order.id}")

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "completed"
    assert body["refund_state"] == "partial"
    assert body["refunded_total"] == "25.00"
    assert body["net_collected"] == "75.00"


@pytest.mark.parametrize(
    "path", ["/api/v1/orders/{order_id}", "/api/v1/orders/{order_id}/shipping"]
)
def test_the_reads_the_position_rides_on_are_mounted(path: str) -> None:
    from app.main import create_app

    assert path in create_app().openapi()["paths"]

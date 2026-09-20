"""ORDERS money path — the rules that decide how much money an order holds.

A bug here costs real money, so these tests pin the RULES rather than a
snapshot of the code. The four defects they were written against, all in
``orders/service.py``:

1. **The over-payment guard summed payments GROSS.** After a partial refund the
   refunded part still counted as collected, so the order read as fully paid and
   the customer could never be charged it again — a lost charge. The guard now
   compares against the order's NET position (settled minus refunds).
2. **``reconcile_payment`` downgraded a CAPTURED payment.** A stale provider
   report of ``failed`` moved the payment out of the settled balance, which let
   the same amount be captured a second time while the provider still held the
   first capture — a double charge. Money states are monotone now: captured
   money leaves the ledger only through ``register_refund``.
3. **``change_status(..., "refunded")`` needed no refund.** An operator could
   mark a completed order refunded while every captured payment stayed put and
   no ``refunds`` row existed, so the order and the ledger disagreed.
4. **Amounts were compared unquantized and written through ``float``.**
   ``0.001`` passed a ``> 0`` guard and stored as ``0.00``; three refunds of
   ``3.3333`` summed to ``9.9999`` (passing a ``<= 10.00`` cap) while the three
   stored ``NUMERIC(14,2)`` rows summed to ``9.99``, leaving a cent that no
   further refund could claim. ``order.created`` published ``grand_total`` as a
   ``Decimal`` while ``order.refunded`` published ``float(amount)``.

Structure: the first class is DB-free and runs locally; the second is
DB-backed and runs in CI (no local Postgres here).
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.schemas import deserialize
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders import service as orders_service
from app.modules.orders.models import Order, OrderPayment, Refund
from app.modules.orders.money import (
    net_collected,
    order_balance,
    positive_money,
    reconciliation_refusal,
    to_money,
)
from app.modules.orders.service import OrderService
from app.modules.platform.models import OutboxEvent

SERVICE_TREE = ast.parse(
    pathlib.Path(orders_service.__file__).read_text(encoding="utf-8")
)


# ---------------------------------------------------------------------------
# DB-free: the money rules themselves
# ---------------------------------------------------------------------------


def test_amounts_are_quantized_to_what_the_numeric_column_will_store() -> None:
    """The guard must reason about the value Postgres keeps, not a wider one."""
    assert to_money("3.3333") == Decimal("3.33")
    assert to_money("10.999") == Decimal("11.00")
    assert to_money(Decimal("25.50")) == Decimal("25.50")
    assert to_money(0) == Decimal("0.00")


def test_a_quantized_refund_can_still_claim_the_last_cent() -> None:
    """Three refunds of 3.3333 against a 10.00 capture.

    The old guard summed the UNQUANTIZED values: ``3.3333 * 3 = 9.9999``, which
    is ``<= 10.00``, so it passed — while the three stored ``NUMERIC(14,2)``
    rows held ``9.99``. The remaining cent was then unclaimable, because
    ``9.9999 + 0.01 > 10.00`` refused it forever.
    """
    refunds = [positive_money("3.3333") for _ in range(3)]
    assert refunds == [Decimal("3.33")] * 3
    total = sum(refunds, Decimal("0"))
    assert total == Decimal("9.99")
    # The cent is reachable exactly: quantized arithmetic stays inside the cap.
    assert total + Decimal("0.01") == Decimal("10.00")
    # …and this is the arithmetic that made it unreachable before.
    assert Decimal("3.3333") * 3 + Decimal("0.01") > Decimal("10.00")


def test_an_amount_that_rounds_to_zero_is_not_positive() -> None:
    """``0.001`` is > 0 but stores as ``0.00`` — a refund of nothing."""
    with pytest.raises(ValueError, match="greater than zero"):
        positive_money("0.001")
    with pytest.raises(ValueError, match="greater than zero"):
        positive_money("0.004")
    assert to_money("0.001") == Decimal("0.00")
    # A real amount is unchanged by the quantization step.
    assert positive_money("0.005") == Decimal("0.01")


def test_non_finite_amounts_are_rejected_as_a_value_error() -> None:
    """``Decimal("NaN") > 0`` raises ``InvalidOperation``; it must not escape."""
    for bad in ("NaN", "sNaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError):
            to_money(bad)
        with pytest.raises(ValueError):
            positive_money(bad)


def test_the_balance_after_a_partial_refund_is_still_collectable() -> None:
    """25.50 captured, 10.00 refunded -> 10.00 is still owed (the lost charge)."""
    assert net_collected("25.50", "10.00") == Decimal("15.50")
    assert order_balance("25.50", "25.50", "10.00") == Decimal("10.00")
    # Nothing refunded yet: the full total is still owed.
    assert order_balance("25.50", "0", "0") == Decimal("25.50")


def test_a_fully_refunded_payment_nets_to_zero_and_frees_the_whole_total() -> None:
    """``refunded`` payments stay on the GROSS side of the subtraction.

    Dropping them from the gross side while still subtracting their refunds
    counts the refund twice: net collected goes to ``-25.50``, so the order
    reads as still owing ``51.00`` — twice its total — and every further
    capture looks legal.
    """
    assert net_collected("25.50", "25.50") == Decimal("0.00")
    assert order_balance("25.50", "25.50", "25.50") == Decimal("25.50")


def test_a_captured_payment_is_never_downgraded_by_a_later_report() -> None:
    """The double-charge guard: captured money only leaves via a refund row."""
    for observed in ("failed", "pending", "unknown", "authorized", "refunded"):
        refusal = reconciliation_refusal("captured", observed)
        assert isinstance(refusal, str) and refusal, observed
    # Idempotent replay of the same capture is still fine.
    assert reconciliation_refusal("captured", "captured") is None


def test_reconcile_cannot_invent_a_refund_without_a_ledger_row() -> None:
    """A refund state with no ``refunds`` row is a ledger that disagrees."""
    for current in ("unknown", "pending", "failed", "authorized"):
        for observed in ("refunded", "partially_refunded"):
            assert reconciliation_refusal(current, observed), (current, observed)
    for current in ("refunded", "partially_refunded"):
        for observed in ("captured", "failed", "pending"):
            assert reconciliation_refusal(current, observed), (current, observed)


def test_the_legitimate_reconciliations_still_work() -> None:
    """The guard must be narrow: §141 resolution and first captures are legal."""
    for current in ("unknown", "pending", "authorized"):
        assert reconciliation_refusal(current, "captured") is None, current
        assert reconciliation_refusal(current, "failed") is None, current
        assert reconciliation_refusal(current, current) is None, current
    assert reconciliation_refusal("unknown", "authorized") is None
    assert reconciliation_refusal("failed", "captured") is not None


# ---------------------------------------------------------------------------
# DB-free: are the rules actually ON the money path?
# ---------------------------------------------------------------------------


def _calls_by_function() -> dict[str, set[str]]:
    """Map each top-level / method name to the plain names it calls."""
    found: dict[str, set[str]] = {}
    for node in ast.walk(SERVICE_TREE):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        found[node.name] = {
            call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
    return found


def test_the_orders_money_path_never_handles_money_as_float() -> None:
    """``float(...)`` must not appear in the ORDERS service at all.

    It was there six times: ``float(round(subtotal, 2))``, ``float(price)``,
    ``float(price * quantity)``, ``float(captured)``, ``float(refund_amount)``
    and ``float(refund_amount)`` again in the ``order.refunded`` payload — so
    the same field arrived as a ``Decimal`` on ``order.created`` and a ``float``
    on ``order.refunded``. Every money value in this module is a ``Decimal``
    quantized by ``orders.money``; a new ``float()`` call is a regression.
    """
    offenders = [
        (node.lineno, ast.unparse(node))
        for node in ast.walk(SERVICE_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    ]
    assert offenders == []


def test_the_money_rules_are_reached_from_the_real_service_methods() -> None:
    """A pure rule that no service method calls proves nothing.

    This repo has shipped "complete, unit-tested, and imported by nothing"
    seven times. Each rule below is asserted against the method that must use
    it, so a later rewrite back to inline arithmetic fails here even if the
    rule itself is untouched.
    """
    calls = _calls_by_function()
    wiring = {
        "create_order": {"to_money"},
        "add_payment": {"positive_money", "order_balance"},
        "reconcile_payment": {"reconciliation_refusal"},
        "register_refund": {"positive_money", "to_money"},
        "change_status": {"net_collected"},
    }
    missing = {
        method: sorted(rules - calls.get(method, set()))
        for method, rules in wiring.items()
        if rules - calls.get(method, set())
    }
    assert missing == {}


def test_the_orders_service_imports_the_money_module() -> None:
    """The rules live in ``orders.money`` and are imported, not re-implemented."""
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "app.modules.orders.money"
        for node in SERVICE_TREE.body
    )


# ---------------------------------------------------------------------------
# DB-backed (CI): the rules end to end, through the real service
# ---------------------------------------------------------------------------


async def _order_with_stock(
    db: AsyncSession, tenant_id: uuid.UUID, *, price: str = "25.50", stock: int = 10
) -> Order:
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="Money Buyer",
        phone=f"+2010{uuid.uuid4().hex[:8]}",
    )
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Money WH",
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    product = await CatalogService.create_product(
        db, tenant_id, title="Widget", slug=f"w-{uuid.uuid4().hex[:10]}"
    )
    variant = await CatalogService.add_variant(
        db,
        tenant_id,
        product.id,
        sku=f"MNY-{uuid.uuid4().hex[:6].upper()}",
        price=price,
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
    return await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )


async def _payments(db: AsyncSession, order_id: uuid.UUID) -> list[OrderPayment]:
    return list(
        (
            await db.execute(
                select(OrderPayment).where(OrderPayment.order_id == order_id)
            )
        ).scalars().all()
    )


async def test_a_partially_refunded_amount_can_still_be_collected(
    db: AsyncSession, tenant_ctx
) -> None:
    """The lost charge: 25.50 paid, 10.00 refunded, 10.00 must be collectable.

    Before the fix the guard summed payments gross, read the order as fully
    paid and refused — the refunded 10.00 could never be charged again.
    """
    tenant_id = tenant_ctx.tenant_id
    order = await _order_with_stock(db, tenant_id)
    payment = await OrderService.add_payment(
        db, tenant_id, order.id, method="cash", amount="25.50"
    )
    await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount="10.00", reason="partial return"
    )

    again = await OrderService.add_payment(
        db, tenant_id, order.id, method="cash", amount="10.00"
    )
    assert again.amount == Decimal("10.00")

    # Read the ledger back independently of the service: gross settled minus
    # refunds is exactly the order total — never more.
    payments = await _payments(db, order.id)
    refunds = (
        await db.execute(
            select(Refund)
            .join(OrderPayment, OrderPayment.id == Refund.payment_id)
            .where(OrderPayment.order_id == order.id, Refund.status != "rejected")
        )
    ).scalars().all()
    assert sorted(p.amount for p in payments) == [Decimal("10.00"), Decimal("25.50")]
    gross = sum((p.amount for p in payments), Decimal("0"))
    returned = sum((r.amount for r in refunds), Decimal("0"))
    assert gross - returned == Decimal("25.50")
    assert gross - returned == to_money(order.grand_total)

    # …and the guard still refuses the cent that would exceed the total.
    with pytest.raises(ConflictError):
        await OrderService.add_payment(
            db, tenant_id, order.id, method="cash", amount="0.01"
        )
    await db.flush()


async def test_reconcile_refuses_to_downgrade_a_capture_so_it_cannot_be_recharged(
    db: AsyncSession, tenant_ctx
) -> None:
    """The double charge: a stale ``failed`` report must not free the amount."""
    tenant_id = tenant_ctx.tenant_id
    order = await _order_with_stock(db, tenant_id)
    payment = await OrderService.add_payment(
        db, tenant_id, order.id, method="card", amount="25.50"
    )

    with pytest.raises(ConflictError):
        await OrderService.reconcile_payment(
            db, tenant_id, order.id, payment.id, provider_status="failed"
        )
    assert payment.status == "captured"

    # The order still reads as paid, so the same money cannot be taken twice.
    with pytest.raises(ConflictError):
        await OrderService.add_payment(
            db, tenant_id, order.id, method="cash", amount="25.50"
        )
    await db.flush()


async def test_reconcile_refuses_to_invent_a_refund(
    db: AsyncSession, tenant_ctx
) -> None:
    """A provider-reported refund without a ``refunds`` row is not applied."""
    tenant_id = tenant_ctx.tenant_id
    order = await _order_with_stock(db, tenant_id)
    payment = await OrderService.add_payment(
        db, tenant_id, order.id, method="card", amount="25.50"
    )

    with pytest.raises(ConflictError):
        await OrderService.reconcile_payment(
            db, tenant_id, order.id, payment.id, provider_status="refunded"
        )
    assert payment.status == "captured"
    assert (
        await db.execute(
            select(Refund).where(Refund.payment_id == payment.id)
        )
    ).scalars().all() == []
    await db.flush()


async def test_an_order_cannot_be_marked_refunded_while_money_is_held(
    db: AsyncSession, tenant_ctx
) -> None:
    """The status is a money claim: it needs the ledger, not just the operator."""
    tenant_id = tenant_ctx.tenant_id
    order = await _order_with_stock(db, tenant_id)
    payment = await OrderService.add_payment(
        db, tenant_id, order.id, method="cash", amount="25.50"
    )
    for status in ("processing", "shipped", "delivered", "completed"):
        await OrderService.change_status(db, tenant_id, order.id, status)

    with pytest.raises(ConflictError):
        await OrderService.change_status(db, tenant_id, order.id, "refunded")
    assert order.status == "completed"

    # The ledger path does move it, and only once the money is actually back.
    await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount="25.50"
    )
    assert payment.status == "refunded"
    assert order.status == "refunded"
    await db.flush()


async def test_both_money_events_reach_a_consumer_as_decimals(
    db: AsyncSession, tenant_ctx
) -> None:
    """``order.created`` and ``order.refunded`` must agree on the value's type.

    The refund event published ``float(refund_amount)`` while ``order.created``
    published a ``Decimal`` ``grand_total``: the same money arrived as ``5.25``
    on one event and ``Decimal("5.25")`` on the other. Read through
    ``deserialize``, which is what every consumer uses.
    """
    tenant_id = tenant_ctx.tenant_id
    order = await _order_with_stock(db, tenant_id)
    payment = await OrderService.add_payment(
        db, tenant_id, order.id, method="cash", amount="25.50"
    )
    await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount="5.25", reason="goodwill"
    )
    await db.flush()

    events = (
        await db.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == order.id)
        )
    ).scalars().all()
    by_type = {e.payload["event_type"]: e for e in events}

    def consumer_view(event_type: str) -> dict:
        row = by_type[event_type]
        return deserialize({"payload": row.payload, "meta": row.meta}).payload

    created = consumer_view("order.created")
    refunded = consumer_view("order.refunded")
    assert isinstance(created["grand_total"], Decimal)
    assert created["grand_total"] == Decimal("25.50")
    assert isinstance(refunded["amount"], Decimal)
    assert refunded["amount"] == Decimal("5.25")

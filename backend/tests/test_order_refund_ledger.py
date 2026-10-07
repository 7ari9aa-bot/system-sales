"""The refund ledger — every unit of money out has a ``Refund`` row behind it (M1).

Gap register line 153 claimed ``reconcile_payment`` could flip a CAPTURED payment
back to FAILED and so "forge refunds without Refund rows", citing
``orders/service.py:527-542``. That citation is STALE: the §47 money merge moved
the rule into ``orders.money.reconciliation_refusal`` and ``reconcile_payment``
now raises ``ConflictError`` for it (``app/modules/orders/service.py:936-940``).
What was missing is coverage of the ledger as a whole, which is what this file
owns — the pieces no other test pins:

* the money-out write has exactly ONE writer (``register_refund``), so no path
  can leave the till without a row (AST-guarded, runs locally);
* the real refund ENDPOINT creates exactly one row per refund, and a refund
  never edits ``grand_total`` — the totals agree with the rows read back
  independently;
* a double-submitted refund is not two refunds. It is already covered, by the
  ``/api/v1/orders`` entry in ``IDEMPOTENT_PATHS``: the first test below proves
  the refund path is inside the allow-list, and the endpoint test proves the
  replay leaves one row and one unit of money out. So nothing new was added.

Structure: the first block is DB-free and runs locally; the rest is DB-backed
and runs in CI (skips locally without ``DATABASE_URL_APP_ADMIN``).
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.idempotency import REPLAY_HEADER, should_guard
from app.modules.catalog.service import CatalogService
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders import money as orders_money
from app.modules.orders import service as orders_service
from app.modules.orders.models import OrderPayment, Refund
from app.modules.orders.service import OrderService
from tests.test_order_idempotency import KEY_HEADER, SessionStore, _build_app

ORDERS_DIR = pathlib.Path(orders_service.__file__).parent


# ---------------------------------------------------------------------------
# DB-free: who is allowed to write the ledger
# ---------------------------------------------------------------------------


def test_no_provider_report_can_assert_a_refund_on_its_own() -> None:
    """The table the reconcile path reads, checked pair by pair.

    ``_PAYMENT_PROVIDER_STATUSES`` maps a provider's ``refunded`` onto the local
    status, so the ONLY thing standing between a webhook and a forged money-out
    row is ``reconciliation_refusal`` refusing it for every current state.
    """
    assert orders_service._PAYMENT_PROVIDER_STATUSES["refunded"] == "refunded"
    assert orders_service._PAYMENT_PROVIDER_STATUSES["partially_refunded"] == ("partially_refunded")
    for current in ("captured", "pending", "authorized", "unknown", "failed", "refunded"):
        for observed in ("refunded", "partially_refunded"):
            if observed == current:
                continue  # an identical report is a no-op, never a forged row
            assert orders_money.reconciliation_refusal(current, observed), (
                current,
                observed,
            )
    # …and a capture can never be walked back to a non-collected state either.
    for observed in ("failed", "pending", "unknown", "authorized"):
        assert orders_money.reconciliation_refusal("captured", observed), observed


def test_the_refund_row_has_exactly_one_writer_in_the_module() -> None:
    """One door for money out, so the ledger cannot be entered sideways.

    A second ``Refund(...)`` construction — or a raw INSERT — would be a path
    that moves money without the capture/over-refund checks ``register_refund``
    makes, which is the gap M1 is about.
    """
    writers: list[str] = []
    for path in sorted(ORDERS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "INSERT INTO refunds" not in source, path.name
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Refund"
            ):
                writers.append(path.name)
    assert writers == ["service.py"], writers

    # …and that one site is the function that does the capture/over-refund checks.
    inside = [
        fn.name
        for fn in ast.walk(ast.parse((ORDERS_DIR / "service.py").read_text(encoding="utf-8")))
        if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef)
        and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Refund"
            for node in ast.walk(fn)
        )
    ]
    assert inside == ["register_refund"], inside


def test_the_refund_endpoint_is_inside_the_idempotency_allow_list() -> None:
    """A retried refund is the duplicate the guard exists for.

    ``/api/v1/orders`` prefixes the allow-list, so the nested refund route is
    guarded when the client sends ``Idempotency-Key`` — the honest answer to
    "does a double submit create two refunds" is already yes-with-a-header, and
    nothing new is needed here. (Without the header the route keeps its plain
    semantics, which is the documented opt-in policy.)
    """
    path = "/api/v1/orders/11111111-1111-1111-1111-111111111111/payments/reunds/refunds"
    assert should_guard("POST", path) is True
    assert should_guard("POST", path.replace("/refunds", "/reconcile")) is True


# ---------------------------------------------------------------------------
# DB-backed (CI): the ledger end to end, through the real endpoint
# ---------------------------------------------------------------------------


async def _tenant_ledger(db: AsyncSession, order_id: uuid.UUID):
    """The order's money read back from the rows, not from the service."""
    payments = list(
        (await db.execute(sa.select(OrderPayment).where(OrderPayment.order_id == order_id)))
        .scalars()
        .all()
    )
    refunds = list(
        (await db.execute(sa.select(Refund).where(Refund.payment_id.in_([p.id for p in payments]))))
        .scalars()
        .all()
        if payments
        else []
    )
    gross = sum(
        (p.amount for p in payments if p.status in orders_money.SETTLED_PAYMENT_STATUSES),
        Decimal("0"),
    )
    returned = sum((r.amount for r in refunds if r.status != "rejected"), Decimal("0"))
    return payments, refunds, orders_money.net_collected(gross, returned)


async def _order(db: AsyncSession, tenant_id: uuid.UUID, *, price: str = "40.00"):
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="Ledger Buyer",
        phone=f"+2010{uuid.uuid4().hex[:8]}",
    )
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Ledger WH",
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    product = await CatalogService.create_product(
        db, tenant_id, title="Ledger Widget", slug=f"ldg-{uuid.uuid4().hex[:10]}"
    )
    # §M4: only an active product sells, and `draft` is the create default.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"LDG-{uuid.uuid4().hex[:6].upper()}", price=price
    )
    await InventoryService.move(
        db, tenant_id, variant.id, warehouse.id, direction="in", quantity=50, reason="purchase"
    )
    order = await OrderService.create_order(
        db,
        tenant_id,
        customer.id,
        [{"variant_id": variant.id, "quantity": 1}],
        warehouse_id=warehouse.id,
    )
    return customer, order


async def test_a_captured_payment_cannot_go_back_to_failed_without_a_refund_row(
    db: AsyncSession, tenant_ctx
) -> None:
    """M1 itself: the downgrade that used to erase money from the ledger.

    The refusal, then the legal way out — one refund row for the same amount,
    and the ledger reading the same money either side of the refusal.
    """
    tenant_id = tenant_ctx.tenant_id
    _customer, order = await _order(db, tenant_id)
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="card", amount="40.00")
    await db.flush()
    _payments, _refunds, before = await _tenant_ledger(db, order.id)
    assert before == Decimal("40.00")

    with pytest.raises(ConflictError):
        await OrderService.reconcile_payment(
            db, tenant_id, order.id, payment.id, provider_status="failed"
        )
    await db.flush()

    payment_row = (
        await db.execute(sa.select(OrderPayment).where(OrderPayment.id == payment.id))
    ).scalar_one()
    assert payment_row.status == "captured"
    assert (
        await db.execute(sa.select(Refund).where(Refund.payment_id == payment.id))
    ).scalars().all() == []
    _payments, _refunds, after = await _tenant_ledger(db, order.id)
    assert after == before, "a refused reconcile moved money"

    # The only way the money goes back: a row, and the totals follow it.
    refund = await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount="40.00", reason="wrong item"
    )
    await db.flush()
    rows, refunds, net = await _tenant_ledger(db, order.id)
    assert len(refunds) == 1 and refunds[0].id == refund.id
    assert net == Decimal("0.00")
    assert rows[0].status == "refunded"


async def test_a_provider_reported_refund_never_writes_the_ledger_itself(
    db: AsyncSession, tenant_ctx
) -> None:
    """The other half: a ``refunded`` report cannot stand in for a row.

    Before the guard this read as money returned while nothing had been booked,
    which is the same forgery seen from the customer's side.
    """
    tenant_id = tenant_ctx.tenant_id
    _customer, order = await _order(db, tenant_id)
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="card", amount="40.00")

    with pytest.raises(ConflictError):
        await OrderService.reconcile_payment(
            db, tenant_id, order.id, payment.id, provider_status="refunded"
        )
    await db.flush()

    assert payment.status == "captured"
    assert (
        await db.execute(sa.select(Refund).where(Refund.payment_id == payment.id))
    ).scalars().all() == []


async def test_the_refund_endpoint_creates_exactly_one_row_per_refund(
    db: AsyncSession, tenant_ctx
) -> None:
    """``POST /orders/{id}/payments/{pid}/refunds`` against the real router."""
    tenant_id = tenant_ctx.tenant_id
    customer, order = await _order(db, tenant_id)
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount="40.00")
    app = _build_app(
        store=SessionStore(db),
        tenant_id=tenant_id,
        session=db,
        user_id=tenant_ctx.user.id,
    )
    url = f"/api/v1/orders/{order.id}/payments/{payment.id}/refunds"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(url, json={"amount": "10.00", "reason": "one line"})
        second = await client.post(url, json={"amount": "5.00", "reason": "another line"})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["status"] == "processed"

    payments, refunds, net = await _tenant_ledger(db, order.id)
    assert len(refunds) == 2, [r.id for r in refunds]
    assert {Decimal(str(r.amount)) for r in refunds} == {Decimal("10.00"), Decimal("5.00")}
    assert net == Decimal("25.00")
    # The totals were never edited to match: the rows ARE the position.
    assert Decimal(str(payments[0].amount)) == Decimal("40.00")
    assert payments[0].status == "partially_refunded"
    stored = (
        await db.execute(sa.select(Customer.lifetime_value).where(Customer.id == customer.id))
    ).scalar_one()
    assert Decimal(str(stored)) == net, "lifetime_value disagrees with the ledger"


async def test_a_double_submit_of_one_refund_intent_creates_one_row(
    db: AsyncSession, tenant_ctx
) -> None:
    """One ``Idempotency-Key``, two HTTP calls, one unit of money out."""
    tenant_id = tenant_ctx.tenant_id
    customer, order = await _order(db, tenant_id)
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount="40.00")
    app = _build_app(
        store=SessionStore(db),
        tenant_id=tenant_id,
        session=db,
        user_id=tenant_ctx.user.id,
    )
    url = f"/api/v1/orders/{order.id}/payments/{payment.id}/refunds"
    key = f"refund-{uuid.uuid4().hex}"
    body = {"amount": "15.00", "reason": "damaged on arrival"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(url, json=body, headers={KEY_HEADER: key})
        retry = await client.post(url, json=body, headers={KEY_HEADER: key})

    assert first.status_code == 201, first.text
    assert retry.status_code == 201, retry.text
    assert retry.json() == first.json()
    assert retry.headers.get(REPLAY_HEADER) == "true"

    _payments, refunds, net = await _tenant_ledger(db, order.id)
    assert len(refunds) == 1, f"a retried refund booked {len(refunds)} rows"
    assert net == Decimal("25.00")
    stored = (
        await db.execute(sa.select(Customer.lifetime_value).where(Customer.id == customer.id))
    ).scalar_one()
    assert Decimal(str(stored)) == Decimal("25.00")

    # The same key with a DIFFERENT amount is a client bug, not a retry.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        conflict = await client.post(url, json={"amount": "30.00"}, headers={KEY_HEADER: key})
    assert conflict.status_code == 409, conflict.text
    _payments, refunds, net = await _tenant_ledger(db, order.id)
    assert len(refunds) == 1 and net == Decimal("25.00")


async def test_two_refunds_of_one_capture_book_two_rows_and_no_more_money(
    db: AsyncSession, tenant_ctx
) -> None:
    """The clean end state: money out == the rows, summed exactly once.

    A payment is ``refunded`` with 40.00 gross on the settled side and 40.00 of
    refund rows against it. Reading the gross side WITHOUT the rows (or the rows
    without the gross side) is the double count that makes an order look
    over-refunded by its own total.
    """
    tenant_id = tenant_ctx.tenant_id
    _customer, order = await _order(db, tenant_id)
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount="40.00")
    await OrderService.register_refund(db, tenant_id, order.id, payment.id, amount="10.00")
    await OrderService.register_refund(db, tenant_id, order.id, payment.id, amount="30.00")
    await db.flush()

    rows, refunds, net = await _tenant_ledger(db, order.id)
    assert len(refunds) == 2
    assert sum((r.amount for r in refunds), Decimal("0")) == Decimal("40.00")
    assert net == Decimal("0.00")
    assert rows[0].status == "refunded"
    assert sum((p.amount for p in rows), Decimal("0")) == Decimal("40.00")
    # Nothing more can leave: a third refund has no captured money behind it.
    with pytest.raises(ConflictError):
        await OrderService.register_refund(db, tenant_id, order.id, payment.id, amount="0.01")
    rows, refunds, net = await _tenant_ledger(db, order.id)
    assert len(refunds) == 2 and net == Decimal("0.00"), "a refused refund booked a row"

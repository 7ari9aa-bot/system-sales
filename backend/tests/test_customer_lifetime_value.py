"""CUSTOMER ``lifetime_value`` — the number the money ledger must write (gap M6).

``customers.lifetime_value`` is the column every LTV-based segment reads
(``segments.service`` maps ``lifetime_value`` onto it), and until now nothing on
the order path ever wrote it: the only UPDATE in the codebase was the ``+=``
inside the identity merge, consolidating a number nobody had ever set. So
``{"field": "lifetime_value", "op": "gt", "value": 500}`` matched no customer in
any tenant, forever.

The shape these tests pin, and the choice behind it:

* **Only money that arrived moves it.** An order is a promise; a capture is
  revenue. Creating one leaves the column alone, so an unpaid (or COD-never-
  settled) order cannot inflate a customer.
* **It is DERIVED, not nudged.** One statement rewrites the column from the
  payment/refund rows the customer holds *now*, instead of adding this
  transaction's amount to whatever was stored before. An increment is a guess
  about every past write: ``test_a_lifetime_value_recomputes_what_an_order_
  reassignment_changed`` is the case that proves it — an order moving to another
  customer (exactly what the identity merge's ``UPDATE orders SET customer_id``
  remap does) makes every stored increment wrong by the moved amount, and a
  derived write fixes it on the next mutation rather than propagating it.
* **It never goes negative.** A ledger that has given back more than it holds
  (rows written before the over-refund cap, a manual correction) reads as zero.
* **One statement per mutation**, written as SQL against ``customers`` the way
  ``_audit_shipping`` writes ``audit_logs``: an ``orders -> customers.models``
  import is an edge the module-boundary ratchet has no room for, and the
  vocabulary of which payment states count as money stays in ``orders.money``,
  where every other money rule lives (§47).

Structure: the first block is DB-free and runs locally; the rest is DB-backed
and runs in CI (it skips locally without ``DATABASE_URL_APP_ADMIN``).
"""

from __future__ import annotations

import ast
import pathlib
import re
import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.customers import service as customers_module
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders import money as orders_money
from app.modules.orders import service as orders_service
from app.modules.orders.models import OrderPayment, Refund
from app.modules.orders.service import OrderService
from app.modules.segments.service import SegmentService

SERVICE_SOURCE = pathlib.Path(orders_service.__file__).read_text(encoding="utf-8")
SERVICE_TREE = ast.parse(SERVICE_SOURCE)

RESTRIPE = "_recompute_lifetime_value"


def _function(name: str) -> ast.AsyncFunctionDef | ast.FunctionDef | None:
    for node in ast.walk(SERVICE_TREE):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return node
    return None


def _names_called(name: str) -> set[str]:
    """Every call target made inside one function, as plain / dotted names."""
    fn = _function(name)
    assert fn is not None, f"orders/service.py has no {name}"
    found: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            found.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            found.add(node.func.attr)
    return found


# ---------------------------------------------------------------------------
# DB-free: the rule itself
# ---------------------------------------------------------------------------


def test_lifetime_value_counts_only_money_that_actually_arrived() -> None:
    """``authorized`` is a promise at the provider, not revenue in the till.

    ``SETTLED_PAYMENT_STATUSES`` deliberately carries ``authorized``, because
    capturing on top of an authorization would over-collect. That set must not
    be reused for lifetime value, where only money that settled counts.
    ``refunded`` DOES count on the gross side: its ``refunds`` rows subtract it
    back, and dropping it there would count the refund twice.
    """
    collected = orders_money.COLLECTED_PAYMENT_STATUSES
    assert "authorized" not in collected
    assert "pending" not in collected
    assert "failed" not in collected
    assert set(collected) == {"captured", "partially_refunded", "refunded"}


def test_an_over_refunded_ledger_floors_at_zero() -> None:
    """Value given back past value received is zero, never a negative number."""
    assert orders_money.lifetime_value("30.00", "10.00") == Decimal("20.00")
    assert orders_money.lifetime_value("10.00", "25.00") == Decimal("0.00")
    assert orders_money.lifetime_value("10.00", "10.00") == Decimal("0.00")
    # Quantized like every other money figure, so the compared value is the one
    # the NUMERIC(14,2) column will hold: half a cent is a cent, a fifth of one
    # is nothing.
    assert orders_money.lifetime_value("0.005", "0") == Decimal("0.01")
    assert orders_money.lifetime_value("10.00", "0.004") == Decimal("10.00")


def test_every_mutation_that_moves_money_restripes_the_customer() -> None:
    """A rule no service method calls is decoration — this repo's own lesson.

    ``add_payment`` captures, ``reconcile_payment`` resolves a lost provider
    result into a capture, ``register_refund`` gives money back: the whole write
    side of the ledger, so all three must reach the column.
    """
    for method in ("add_payment", "reconcile_payment", "register_refund"):
        assert RESTRIPE in _names_called(method), (
            f"{method} moves money without restriping lifetime_value"
        )


def test_the_lifetime_value_write_is_one_derived_and_floored_statement() -> None:
    fn = _function(RESTRIPE)
    assert fn is not None, (
        "orders/service.py has no _recompute_lifetime_value — lifetime_value is "
        "still nobody's job to write"
    )
    source = ast.get_source_segment(SERVICE_SOURCE, fn) or ""
    assert "UPDATE customers" in source
    assert "order_payments" in source and "refunds" in source, (
        "the write must be derived from the ledger rows"
    )
    assert "GREATEST" in source, "no floor: an over-refunded customer reads negative"
    assert "COLLECTED_PAYMENT_STATUSES" in source, (
        "the payment vocabulary must come from orders.money, not a literal here"
    )
    assert "lifetime_value +" not in source and "lifetime_value -" not in source, (
        "an incremental write is a guess about every past write"
    )
    executes = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    assert len(executes) == 1, f"{len(executes)} statements; one per mutation is the shape"


async def test_the_restripe_sql_is_one_well_formed_statement() -> None:
    """Raw SQL fails loudly only in Postgres, so check it without a session.

    Paren balance and the bind-name/parameter pairing are the two ways a hand-
    written statement breaks: the server rejects the first, SQLAlchemy rejects
    the second, and neither is visible from the Python side. The DB-backed tests
    cover the rest — they skip locally, which is exactly why this one does not.
    """
    captured: dict[str, object] = {}

    class _Recorder:
        async def execute(self, statement, parameters=None):  # noqa: ANN001
            captured["sql"] = str(statement)
            captured["params"] = dict(parameters or {})

    await OrderService._recompute_lifetime_value(_Recorder(), uuid.uuid4(), uuid.uuid4())

    sql = str(captured["sql"])
    assert sql.lstrip().upper().startswith("UPDATE CUSTOMERS"), sql
    assert sql.count("(") == sql.count(")"), f"unbalanced parentheses: {sql}"
    assert sql.upper().count("SELECT") == 2, sql  # gross and refunded, nothing else
    binds = set(re.findall(r":([a-z_][a-z0-9_]*)", sql))
    assert binds == set(captured["params"]), (
        f"binds {sorted(binds)} vs params {sorted(captured['params'])}"
    )


async def test_the_restripe_names_its_customer_from_the_order_row_not_the_caller() -> None:
    """A caller's ``order.customer_id`` is a memory, and memories go stale.

    The remap the derived write exists for is an out-of-band
    ``UPDATE orders SET customer_id``; a session that already loaded the order
    still names the OLD owner on its instance. Binding the write to a
    caller-supplied ``:cid`` then moves the money to the person who no longer
    has the order — which is the identity-merge bug this whole file pins.
    """
    captured: dict[str, object] = {}

    class _Recorder:
        async def execute(self, statement, parameters=None):  # noqa: ANN001
            captured["sql"] = str(statement)
            captured["params"] = dict(parameters or {})

    await OrderService._recompute_lifetime_value(_Recorder(), uuid.uuid4(), uuid.uuid4())

    sql = str(captured["sql"])
    binds = set(re.findall(r":([a-z_][a-z0-9_]*)", sql))
    assert "cid" not in binds, f"the target came from the caller: {sorted(binds)}"
    assert "oid" in binds, sql
    assert "from orders" in sql.lower(), (
        "nothing resolves the order's current owner inside the statement"
    )


def test_the_write_reaches_customers_without_a_new_module_edge() -> None:
    """``orders`` must not start importing ``customers`` tables for this.

    The boundary ratchet is at 103 against a baseline of 104, so a new edge is
    unpayable. Checkout's single function-scope ``customers.service`` import is
    all the coupling allowed here.
    """
    edges = [
        node
        for node in ast.walk(SERVICE_TREE)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("app.modules.customers")
    ]
    assert len(edges) <= 1, f"{len(edges)} customers imports in orders/service.py"


def test_nothing_else_in_the_customers_module_writes_the_column() -> None:
    """A derived figure survives only if it has one writer.

    A staff field or a CRM-side ``+=`` would be silently overwritten by the next
    capture — and would have made this column a second source of truth, which is
    exactly how it ended up never being written at all.
    """
    customers_dir = pathlib.Path(customers_module.__file__).resolve().parent
    orm_writes: list[str] = []
    for path in sorted(customers_dir.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            assigned = (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Attribute) and t.attr == "lifetime_value"
                    for t in node.targets
                )
            ) or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "lifetime_value"
            )
            if assigned:
                orm_writes.append(path.name)
    assert orm_writes == [], orm_writes


# ---------------------------------------------------------------------------
# DB-backed (CI): the write end to end
# ---------------------------------------------------------------------------


async def _ltv(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Decimal:
    """The stored column, read straight from the row."""
    value = (
        await db.execute(
            sa.select(Customer.lifetime_value).where(
                Customer.tenant_id == tenant_id, Customer.id == customer_id
            )
        )
    ).scalar_one()
    return Decimal(str(value))


async def _buyer(db: AsyncSession, tenant_id: uuid.UUID) -> Customer:
    return await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="LTV Buyer",
        phone=f"+2010{uuid.uuid4().hex[:8]}",
    )


async def _shop(db: AsyncSession, tenant_id: uuid.UUID, *, price: str):
    """A published variant with enough stock for every order below."""
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="LTV WH",
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    product = await CatalogService.create_product(
        db, tenant_id, title="LTV Widget", slug=f"ltv-{uuid.uuid4().hex[:10]}"
    )
    # §M4: only an active product sells, and `draft` is the create default.
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"LTV-{uuid.uuid4().hex[:6].upper()}", price=price
    )
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=100,
        reason="purchase",
    )
    return variant, warehouse


async def _order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    variant_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    *,
    quantity: int = 1,
):
    return await OrderService.create_order(
        db,
        tenant_id,
        customer_id,
        [{"variant_id": variant_id, "quantity": quantity}],
        warehouse_id=warehouse_id,
    )


async def test_an_unpaid_order_moves_no_lifetime_value(db: AsyncSession, tenant_ctx) -> None:
    """A promise is not revenue: checkout alone leaves the column at zero."""
    tenant_id = tenant_ctx.tenant_id
    customer = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="25.50")

    order = await _order(db, tenant_id, customer.id, variant.id, warehouse.id)
    await db.flush()

    assert Decimal(str(order.grand_total)) == Decimal("25.50")
    assert await _ltv(db, tenant_id, customer.id) == Decimal("0.00")


async def test_a_capture_raises_lifetime_value_by_the_money_collected(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="25.50")
    # Two units: a 51.00 order, so both captures fit inside the balance guard.
    order = await _order(db, tenant_id, customer.id, variant.id, warehouse.id, quantity=2)

    await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount="20.00")
    await db.flush()
    assert await _ltv(db, tenant_id, customer.id) == Decimal("20.00")

    await OrderService.add_payment(db, tenant_id, order.id, method="card", amount="31.00")
    await db.flush()
    assert await _ltv(db, tenant_id, customer.id) == Decimal("51.00")


async def test_a_reconciled_capture_raises_lifetime_value_too(db: AsyncSession, tenant_ctx) -> None:
    """§141: a provider result resolved late is money that arrived all the same."""
    tenant_id = tenant_ctx.tenant_id
    customer = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="25.50")
    order = await _order(db, tenant_id, customer.id, variant.id, warehouse.id)
    payment = OrderPayment(
        tenant_id=tenant_id,
        order_id=order.id,
        method="card",
        status="unknown",
        amount=Decimal("25.50"),
        currency=order.currency,
        provider="test-gateway",
    )
    db.add(payment)
    await db.flush()

    assert await _ltv(db, tenant_id, customer.id) == Decimal("0.00")
    await OrderService.reconcile_payment(
        db, tenant_id, order.id, payment.id, provider_status="succeeded"
    )
    await db.flush()
    assert await _ltv(db, tenant_id, customer.id) == Decimal("25.50")


async def test_an_authorized_amount_is_not_lifetime_value(db: AsyncSession, tenant_ctx) -> None:
    """The set difference from ``SETTLED_PAYMENT_STATUSES``, pinned on a real row."""
    tenant_id = tenant_ctx.tenant_id
    customer = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="25.50")
    order = await _order(db, tenant_id, customer.id, variant.id, warehouse.id)
    db.add(
        OrderPayment(
            tenant_id=tenant_id,
            order_id=order.id,
            method="card",
            status="authorized",
            amount=Decimal("25.50"),
            currency=order.currency,
        )
    )
    await db.flush()

    assert await _ltv(db, tenant_id, customer.id) == Decimal("0.00")


async def test_a_refund_lowers_lifetime_value(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="25.50")
    order = await _order(db, tenant_id, customer.id, variant.id, warehouse.id)
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="card", amount="25.50")

    await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount="10.00", reason="one line returned"
    )
    await db.flush()
    assert await _ltv(db, tenant_id, customer.id) == Decimal("15.50")

    await OrderService.register_refund(
        db, tenant_id, order.id, payment.id, amount="15.50", reason="the rest"
    )
    await db.flush()
    assert await _ltv(db, tenant_id, customer.id) == Decimal("0.00")


async def test_a_lifetime_value_recomputes_what_an_order_reassignment_changed(
    db: AsyncSession, tenant_ctx
) -> None:
    """The pin on DERIVED rather than incremental.

    Two 10.00 orders for A (so A holds 20.00), then O1 moves to B — the identity
    merge's remap. A refund on O1 restripes B to 5.00; a later refund on O2
    restripes A from A's own rows: 6.00. An increment would have left 16.00,
    because it still believes A made the 10.00 that walked away.
    """
    tenant_id = tenant_ctx.tenant_id
    a = await _buyer(db, tenant_id)
    b = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="10.00")
    o1 = await _order(db, tenant_id, a.id, variant.id, warehouse.id)
    o2 = await _order(db, tenant_id, a.id, variant.id, warehouse.id)
    p1 = await OrderService.add_payment(db, tenant_id, o1.id, method="cash", amount="10.00")
    p2 = await OrderService.add_payment(db, tenant_id, o2.id, method="cash", amount="10.00")
    assert await _ltv(db, tenant_id, a.id) == Decimal("20.00")

    await db.execute(
        sa.text("UPDATE orders SET customer_id = :b WHERE tenant_id = :t AND id = :o"),
        {"b": b.id, "t": tenant_id, "o": o1.id},
    )
    await OrderService.register_refund(
        db, tenant_id, o1.id, p1.id, amount="5.00", reason="moved to another cardholder"
    )
    await db.flush()
    assert await _ltv(db, tenant_id, b.id) == Decimal("5.00")

    await OrderService.register_refund(
        db, tenant_id, o2.id, p2.id, amount="4.00", reason="a damaged line"
    )
    await db.flush()
    assert await _ltv(db, tenant_id, a.id) == Decimal("6.00")


async def test_a_stored_number_that_disagrees_with_the_ledger_is_corrected(
    db: AsyncSession, tenant_ctx
) -> None:
    """Rows are the source of truth: the next mutation overwrites a bad figure.

    Seed a captured payment + a refund and assert the exact expected number, so
    a legacy tenant's hand-edited 999.00 cannot survive one more refund.
    """
    tenant_id = tenant_ctx.tenant_id
    customer = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="40.00")
    order = await _order(db, tenant_id, customer.id, variant.id, warehouse.id)
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount="40.00")
    await db.execute(
        sa.text("UPDATE customers SET lifetime_value = 999.00 WHERE id = :cid"),
        {"cid": customer.id},
    )
    assert await _ltv(db, tenant_id, customer.id) == Decimal("999.00")

    await OrderService.register_refund(db, tenant_id, order.id, payment.id, amount="15.00")
    await db.flush()
    assert await _ltv(db, tenant_id, customer.id) == Decimal("25.00")


async def test_a_ledger_that_gave_back_more_than_it_holds_floors_at_zero(
    db: AsyncSession, tenant_ctx
) -> None:
    """Refund rows written before the over-refund cap existed.

    Unreachable through the service today, so the surplus row is seeded by hand:
    20.00 collected against 30.00 refunded reads as 0.00 — not a negative number
    that turns the customer into a liability in every segment and report.
    """
    tenant_id = tenant_ctx.tenant_id
    customer = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="20.00")
    order = await _order(db, tenant_id, customer.id, variant.id, warehouse.id)
    payment = await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount="20.00")
    await OrderService.register_refund(db, tenant_id, order.id, payment.id, amount="20.00")
    db.add(
        Refund(
            tenant_id=tenant_id,
            payment_id=payment.id,
            amount=Decimal("10.00"),
            reason="legacy row: booked before the cap existed",
            status="processed",
        )
    )
    await db.flush()

    # A fresh capture restripes through the real path, and the floor holds.
    await OrderService.add_payment(db, tenant_id, order.id, method="cash", amount="5.00")
    await db.flush()
    assert await _ltv(db, tenant_id, customer.id) == Decimal("0.00")


async def test_a_lifetime_value_segment_sees_the_new_value(db: AsyncSession, tenant_ctx) -> None:
    """The point of M6: a segment on LTV finally matches somebody real."""
    tenant_id = tenant_ctx.tenant_id
    rich = await _buyer(db, tenant_id)
    poor = await _buyer(db, tenant_id)
    variant, warehouse = await _shop(db, tenant_id, price="50.00")
    # 12 units = a 600.00 order for the high-value buyer, 1 unit for the other.
    for customer, quantity in ((rich, 12), (poor, 1)):
        order = await _order(
            db, tenant_id, customer.id, variant.id, warehouse.id, quantity=quantity
        )
        await OrderService.add_payment(
            db,
            tenant_id,
            order.id,
            method="cash",
            amount=str(order.grand_total),
        )
    await db.flush()

    segment = await SegmentService.create(
        db,
        tenant_id,
        name="High value",
        definition={"all": [{"field": "lifetime_value", "op": "gt", "value": 500}]},
    )
    matched = await SegmentService.evaluate(db, tenant_id, segment)

    assert matched == [rich.id]
    assert await _ltv(db, tenant_id, rich.id) == Decimal("600.00")
    assert await _ltv(db, tenant_id, poor.id) == Decimal("50.00")
    assert segment.last_count == 1


def test_the_lifetime_value_rule_is_a_money_rule_not_a_service_secret() -> None:
    """§47: every money rule lives in ``orders.money``.

    The floor and the status vocabulary below the SQL must be testable without a
    session, or the next caller re-implements them — which is how ``refunded``
    came to be counted twice in one place and dropped in another.
    """
    assert hasattr(orders_money, "COLLECTED_PAYMENT_STATUSES")
    assert callable(orders_money.lifetime_value)
    assert "lifetime_value" in orders_money.__all__
    assert "COLLECTED_PAYMENT_STATUSES" in orders_money.__all__

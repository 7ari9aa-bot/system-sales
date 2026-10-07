"""§176 gate scenario 16 — AI tool-scope attack (§132).

§132's rule: the model may only ever reach the conversation's OWN customer.
The customer id is injected server-side into the tool's ``context`` and is
DELIBERATELY absent from every tool's argument schema, so a prompt-injected
"read customer 9999 / place an order for someone else" has nowhere to land.
Enforcement is the pair ``_bound_customer_id`` (refuse when nothing is bound)
and the ``order.customer_id != customer_id`` re-check in ``_get_order``
(tools.py:384) that turns a foreign id into a plain not-found.

The gate that claimed this scenario (`test_gate.py::test_gate_ai_tool_scope`)
only ran the guardrail TEXT chain on an Arabic prompt — the same thing scenario
9 covers — and never invoked a tool handler. Deleting the scope re-check at
tools.py:384 leaves it green, because it never reaches the code it names.

These tests drive the REAL tool handlers and assert the scope holds:

* a scoped read of the bound customer's own order succeeds;
* the SAME order requested while bound to a different customer is a not-found
  (cross-customer leakage inside one tenant is exactly the attack);
* a tool call with NO customer bound is refused outright, never falling back to
  whatever id the model supplied;
* ``create_order`` cannot be steered to another customer: with no bound scope it
  raises, and its argument schema has no customer_id at all.

DB-backed (real handlers, real tenant-scoped services); skips via ``db_url``
without an application database — CI-only evidence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.errors import DomainError, NotFoundError
from app.modules.ai.tools import _create_order, _get_customer, _get_order
from app.modules.customers.models import Customer
from app.modules.orders.models import Order

pytestmark = [pytest.mark.gate]


async def _customer(db, tenant_id, name: str) -> Customer:
    customer = Customer(tenant_id=tenant_id, name=name)
    db.add(customer)
    await db.flush()
    return customer


async def _order_of(db, tenant_id, customer_id) -> Order:
    order = Order(
        tenant_id=tenant_id,
        number=f"GATE-SCOPE-{uuid.uuid4().hex[:6]}",
        customer_id=customer_id,
        status="pending",
        currency="EGP",
        grand_total=Decimal("50.00"),
        subtotal=Decimal("50.00"),
        discount_total=Decimal("0"),
        shipping_total=Decimal("0"),
        tax_total=Decimal("0"),
        placed_at=datetime.now(UTC),
    )
    db.add(order)
    await db.flush()
    return order


async def test_gate_a_bound_tool_read_returns_only_its_own_customers_order(db, tenant_ctx) -> None:
    """Positive control: the scope is not a blanket denial — the owner reads it."""
    tid = tenant_ctx.tenant_id
    owner = await _customer(db, tid, "Owner")
    order = await _order_of(db, tid, owner.id)

    result = await _get_order(db, tid, order_id=order.id, context={"customer_id": str(owner.id)})
    assert result["order_id"] == str(order.id)


async def test_gate_a_scoped_read_cannot_reach_another_customers_order(db, tenant_ctx) -> None:
    """Same tenant, different customer: the foreign order is invisible.

    Removing tools.py:384's ``order.customer_id != customer_id`` check makes
    ``_order_service().get`` hand the attacker the victim's order (RLS is
    tenant-wide, so the service alone does NOT stop it) — this assertion then
    fails because no NotFoundError is raised.
    """
    tid = tenant_ctx.tenant_id
    victim = await _customer(db, tid, "Victim")
    attacker = await _customer(db, tid, "Attacker")
    order = await _order_of(db, tid, victim.id)

    with pytest.raises(NotFoundError):
        await _get_order(db, tid, order_id=order.id, context={"customer_id": str(attacker.id)})


async def test_gate_a_tool_call_with_no_bound_customer_is_refused(db, tenant_ctx) -> None:
    """Fail closed: an unbound scope never falls back to a model-supplied id."""
    tid = tenant_ctx.tenant_id
    owner = await _customer(db, tid, "Owner")
    order = await _order_of(db, tid, owner.id)

    with pytest.raises(DomainError):
        await _get_order(db, tid, order_id=order.id, context=None)
    with pytest.raises(DomainError):
        await _get_customer(db, tid, context={})


async def test_gate_create_order_cannot_be_steered_to_another_customer(db, tenant_ctx) -> None:
    """§132: create_order takes NO customer from the model — only the bound one.

    The argument schema deliberately omits ``customer_id``; with nothing bound
    the handler refuses rather than trusting a model argument.
    """
    from app.modules.ai.tools import CreateOrderArgs

    tid = tenant_ctx.tenant_id
    # The customer the model TRIED to name is not even a field the schema has.
    assert "customer_id" not in CreateOrderArgs.model_fields

    with pytest.raises(DomainError):
        await _create_order(
            db, tid, items=[{"variant_id": uuid.uuid4(), "quantity": 1}], context={}
        )


async def test_gate_customer_id_is_never_a_model_argument_for_scoped_reads(db, tenant_ctx) -> None:
    """The read tools expose no way to name a customer; scope is server-injected."""
    from app.modules.ai.tools import GetCustomerArgs, GetOrderArgs

    assert "customer_id" not in GetCustomerArgs.model_fields
    assert "customer_id" not in GetOrderArgs.model_fields
    # Whatever the model names, the handler returns ONLY the bound customer:
    # the id comes from context, never from a model argument.
    bound = await _customer(db, tenant_ctx.tenant_id, "Bound")
    result = await _get_customer(db, tenant_ctx.tenant_id, context={"customer_id": str(bound.id)})
    assert result["customer_id"] == str(bound.id)

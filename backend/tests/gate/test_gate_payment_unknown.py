"""§176 gate scenario 20 — payment UNKNOWN reconciliation (§141).

§141's promise is that a payment whose provider result was never observed
(``unknown``) is resolved by a provider REPORT, not by a second charge, and
that a resolved (``captured``) payment is NEVER moved back by a later, stale
report — captured money leaves the ledger only through ``register_refund``.

The gate that stood in ``test_gate.py`` (``test_gate_payment_unknown_reconcil-
iation``) only walked ``unknown -> captured`` and then re-called ``captured``
and checked the status was unchanged. That cannot fail on the protection this
scenario names: it never feeds a NON-MONOTONIC report to a captured payment, so
deleting the guard in ``money.reconciliation_refusal`` (money.py:267) — the
line that stops a captured payment being flipped to ``failed``/``refunded`` and
re-capturable — leaves that test green.

These tests drive the REAL service (`OrderService.reconcile_payment`, which
delegates the monotonic rule to ``reconciliation_refusal`` and raises
``ConflictError`` on a refusal) and assert:

* an ``unknown`` payment resolves to ``captured`` and applies its effects;
* a stale report of ``failed`` against the captured payment is REFUSED, and the
  row stays ``captured`` (money is not silently clawed back into a re-capturable
  state);
* a definitive local ``failed`` payment cannot be silently reconciled to
  ``captured`` — that needs human eyes;
* re-reporting the same ``captured`` result is an idempotent no-op: the payment
  is not charged twice and the row is unchanged.

DB-backed (real PostgreSQL, ``sales_app`` role); skips via ``db_url`` without an
application database — CI-only evidence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import ConflictError
from app.modules.customers.service import CustomerService
from app.modules.orders.models import Order, OrderPayment
from app.modules.orders.service import OrderService

pytestmark = [pytest.mark.gate]


async def _payment_in(db, tenant_id, *, status: str) -> tuple[Order, OrderPayment]:
    """A committed order with a single payment in `status`; returns (order, payment)."""
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        channel="webchat",
        external_id=f"pay-{uuid.uuid4().hex[:8]}",
        name="Pay Gate",
    )
    order = Order(
        tenant_id=tenant_id,
        number=f"GATE-PAY-{uuid.uuid4().hex[:6]}",
        customer_id=customer.id,
        status="pending",
        currency="EGP",
        grand_total=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        discount_total=Decimal("0"),
        shipping_total=Decimal("0"),
        tax_total=Decimal("0"),
        placed_at=datetime.now(UTC),
    )
    db.add(order)
    await db.flush()
    payment = OrderPayment(
        tenant_id=tenant_id,
        order_id=order.id,
        method="manual",
        status=status,
        amount=Decimal("100.00"),
        currency="EGP",
    )
    db.add(payment)
    await db.flush()
    return order, payment


async def _reload(db, payment_id) -> OrderPayment:
    return (
        await db.execute(select(OrderPayment).where(OrderPayment.id == payment_id))
    ).scalar_one()


async def test_gate_an_unknown_payment_resolves_to_captured_without_a_second_charge(
    db, tenant_ctx
) -> None:
    """A provider report resolves UNKNOWN into captured; nothing re-charges."""
    order, payment = await _payment_in(db, tenant_ctx.tenant_id, status="unknown")

    resolved = await OrderService.reconcile_payment(
        db, tenant_ctx.tenant_id, order.id, payment.id, provider_status="captured"
    )
    assert resolved.status == "captured"
    assert resolved.paid_at is not None, "a capture must stamp when the money arrived"
    # §140/§139 side effects applied: the pending order was confirmed.
    order_now = (
        await db.execute(select(Order).where(Order.id == order.id))
    ).scalar_one()
    assert order_now.status == "confirmed"

    # Re-reporting the SAME captured result is an idempotent no-op: exactly one
    # payment row, status unchanged, paid_at not re-stamped — the service never
    # re-runs the charge or the effects.
    again = await OrderService.reconcile_payment(
        db, tenant_ctx.tenant_id, order.id, payment.id, provider_status="captured"
    )
    assert again.id == payment.id
    assert again.status == "captured"
    assert again.paid_at == resolved.paid_at


async def test_gate_a_captured_payment_is_never_downgraded_by_a_stale_report(
    db, tenant_ctx
) -> None:
    """The core monotonicity guard: captured money cannot move to failed.

    Removing ``money.reconciliation_refusal``'s captured branch (money.py:267)
    makes the service silently flip a captured payment back to ``failed`` on a
    late provider report — which drops the money out of the settled balance and
    lets the same amount be captured a second time. This assertion is the one
    the pre-existing gate test never made.
    """
    order, payment = await _payment_in(db, tenant_ctx.tenant_id, status="unknown")
    await OrderService.reconcile_payment(
        db, tenant_ctx.tenant_id, order.id, payment.id, provider_status="captured"
    )

    with pytest.raises(ConflictError):
        await OrderService.reconcile_payment(
            db, tenant_ctx.tenant_id, order.id, payment.id, provider_status="failed"
        )

    stayed = await _reload(db, payment.id)
    assert stayed.status == "captured", "a stale report clawed back captured money"


async def test_gate_a_failed_payment_cannot_be_silently_reconciled_to_captured(
    db, tenant_ctx
) -> None:
    """A capture after a definitive local failure needs a human, not a flip."""
    order, payment = await _payment_in(db, tenant_ctx.tenant_id, status="failed")

    with pytest.raises(ConflictError):
        await OrderService.reconcile_payment(
            db, tenant_ctx.tenant_id, order.id, payment.id, provider_status="captured"
        )
    stayed = await _reload(db, payment.id)
    assert stayed.status == "failed"


async def test_gate_an_unsupported_provider_status_is_refused_before_any_write(
    db, tenant_ctx
) -> None:
    """The lookup maps only known provider vocabularies; garbage never touches state."""
    from app.core.errors import ValidationError

    order, payment = await _payment_in(db, tenant_ctx.tenant_id, status="unknown")
    with pytest.raises(ValidationError):
        await OrderService.reconcile_payment(
            db, tenant_ctx.tenant_id, order.id, payment.id, provider_status="not-a-state"
        )
    assert (await _reload(db, payment.id)).status == "unknown"

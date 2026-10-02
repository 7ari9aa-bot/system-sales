"""Synthetic store + golden runner tests (spec §17.1-§17.2) — Phase 2's gate.

Each planted scenario flows through the REAL analytics path (compiler →
capabilities → drivers → engines) against a seeded real database, and the
manifest's truth is asserted. Determinism is pinned: the same seed rebuilds
the identical store. No LLM anywhere (§17.2's "golden scenarios, no model").
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.modules.analytics.evaluation.golden import evaluate_scenario
from app.modules.analytics.evaluation.synthetic import Scenario, generate_store
from app.modules.customers.models import Customer
from app.modules.orders.models import Order, OrderPayment, Refund, Shipment


def test_generation_is_deterministic_under_a_seed():
    first = generate_store(Scenario.BASELINE, seed=42)
    second = generate_store(Scenario.BASELINE, seed=42)
    assert [o["placed_at"] for o in first.orders] == [
        o["placed_at"] for o in second.orders
    ]
    assert [o["grand_total"] for o in first.orders] == [
        o["grand_total"] for o in second.orders
    ]


async def _seed_store(db, tenant_id: uuid.UUID, store) -> None:
    customer = Customer(tenant_id=tenant_id, name="Synthetic Customer")
    db.add(customer)
    await db.flush()
    order_ids: dict[str, uuid.UUID] = {}
    for order in store.orders:
        row = Order(
            tenant_id=tenant_id,
            number=f"{order['number']}-{uuid.uuid4().hex[:6]}",
            customer_id=customer.id,
            status=order["status"],
            grand_total=order["grand_total"],
            channel=order["channel"],
            placed_at=datetime.fromisoformat(order["placed_at"]),
        )
        db.add(row)
        order_ids[order["id"]] = row
    await db.flush()  # ids assigned before shipments/payments reference them
    for shipment in store.shipments:
        db.add(
            Shipment(
                tenant_id=tenant_id,
                order_id=order_ids[shipment["order_id"]].id,
                carrier=shipment["carrier"],
                status=shipment["status"],
                shipped_at=datetime.fromisoformat(shipment["shipped_at"]),
                delivered_at=datetime.fromisoformat(shipment["delivered_at"]),
            )
        )
    for payment in store.payments:
        db.add(
            OrderPayment(
                tenant_id=tenant_id,
                order_id=order_ids[payment["order_id"]].id,
                method=payment["method"],
                status=payment["status"],
                amount=payment["amount"],
                paid_at=datetime.fromisoformat(payment["paid_at"]),
            )
        )
    for refund in store.refunds:
        payment_row = next(
            p for p in store.payments if p["id"] == refund["payment_id"]
        )
        from sqlalchemy import select

        payment = (
            await db.execute(
                select(OrderPayment).where(
                    OrderPayment.tenant_id == tenant_id,
                    OrderPayment.order_id == order_ids[payment_row["order_id"]].id,
                )
            )
        ).scalars().first()
        db.add(
            Refund(
                tenant_id=tenant_id,
                payment_id=payment.id,
                amount=refund["amount"],
                status=refund["status"],
                processed_at=datetime.fromisoformat(refund["processed_at"]),
            )
        )
    await db.flush()


@pytest.mark.parametrize(
    "scenario",
    [
        Scenario.BASELINE,
        Scenario.AOV_DECLINE,
        Scenario.ORDERS_DECLINE,
        Scenario.REVENUE_SPIKE,
        Scenario.REFUND_SPIKE,
        Scenario.IMMATURE_TAIL,
        Scenario.CHANNEL_SHIFT,
    ],
)
async def test_golden_scenario_passes_end_to_end(db, tenant_ctx, scenario):
    store = generate_store(scenario, seed=42)
    await _seed_store(db, tenant_ctx.tenant_id, store)

    result = await evaluate_scenario(db, tenant_ctx.tenant_id, store)
    failures = [c for c in result.checks if not c[1]]
    assert result.passed, f"{scenario.value}: {failures}"

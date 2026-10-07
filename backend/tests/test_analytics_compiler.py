"""Query compiler tests (spec §7) — REAL schema, REAL tenant boundary.

The compiler's promises are proven against the real orders/shipments/
order_payments/refunds tables: values match hand-seeded data, soft-deletes
and out-of-window rows never count, the channel filter binds to the only
table carrying the column, and a foreign tenant's compute returns ZERO even
though the rows exist — the WHERE clause, not just RLS.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.analytics.compiler import (
    UnsupportedFilter,
    compile_metric,
    compute_fact,
)
from app.modules.analytics.contracts import (
    AnalysisPeriod,
    MaturityPolicy,
    MaturityStatus,
)
from app.modules.customers.models import Customer
from app.modules.orders.models import (
    Order,
    OrderPayment,
    OrderStatusHistory,
    Refund,
    Shipment,
)

NOW = datetime.now(UTC)
WINDOW_START = NOW - timedelta(days=30)
WINDOW_END = NOW


def _period() -> AnalysisPeriod:
    return AnalysisPeriod(
        start=WINDOW_START,
        end=WINDOW_END,
        timezone="Africa/Cairo",
        attribution_basis="placed_at",
        maturity_policy=MaturityPolicy(kind="immediate"),
        maturity_status=MaturityStatus.MATURE,
        data_as_of=NOW,
    )


async def _seed_world(db, tenant_id: uuid.UUID) -> dict:
    """Three in-window orders (two web, one retail), one soft-deleted, one
    out-of-window; a delivered shipment on the first; a payment and a refund."""
    customer = Customer(tenant_id=tenant_id, name="Compiler Customer")
    db.add(customer)
    await db.flush()

    def _order(number: str, *, total: float, channel: str, days: int, deleted: bool = False):
        order = Order(
            tenant_id=tenant_id,
            number=number,
            customer_id=customer.id,
            status="fulfilled",
            grand_total=total,
            channel=channel,
            placed_at=NOW - timedelta(days=days),
            deleted_at=NOW if deleted else None,
        )
        db.add(order)
        return order

    web_a = _order(f"O-{uuid.uuid4().hex[:8]}", total=100.0, channel="web", days=2)
    web_b = _order(f"O-{uuid.uuid4().hex[:8]}", total=250.0, channel="web", days=3)
    retail = _order(f"O-{uuid.uuid4().hex[:8]}", total=90.0, channel="retail", days=1)
    _order(f"O-{uuid.uuid4().hex[:8]}", total=999.0, channel="web", days=2, deleted=True)
    _order(f"O-{uuid.uuid4().hex[:8]}", total=888.0, channel="web", days=45)
    await db.flush()

    db.add(
        Shipment(
            tenant_id=tenant_id,
            order_id=web_a.id,
            carrier="Bosta",
            status="delivered",
            shipped_at=NOW - timedelta(days=1),
            delivered_at=NOW - timedelta(hours=5),
        )
    )
    payment = OrderPayment(
        tenant_id=tenant_id,
        order_id=web_a.id,
        method="cod",
        status="captured",
        amount=100.0,
        paid_at=NOW - timedelta(hours=4),
    )
    db.add(payment)
    await db.flush()
    db.add(
        Refund(
            tenant_id=tenant_id,
            payment_id=payment.id,
            amount=20.0,
            status="processed",
            processed_at=NOW - timedelta(hours=1),
        )
    )
    await db.flush()
    return {"web_a": web_a, "web_b": web_b, "retail": retail, "payment": payment}


async def test_orders_placed_excludes_deleted_and_out_of_window(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    await _seed_world(db, tenant_id)
    fact = await compute_fact(db, tenant_id, "orders_placed", _period(), fact_id="F1")
    assert fact.value == 3  # 4 minus the soft-deleted one; the 45-day-old is out
    assert fact.unit == "count"
    assert fact.maturity_status is MaturityStatus.MATURE


async def test_channel_filter_binds_to_the_orders_table(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    await _seed_world(db, tenant_id)
    web = await compute_fact(db, tenant_id, "orders_placed", _period(), channel="web", fact_id="F1")
    assert web.value == 2
    assert web.filters == {"channel": "web"}


async def test_delivered_revenue_counts_only_delivered_shipments(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    await _seed_world(db, tenant_id)
    fact = await compute_fact(db, tenant_id, "delivered_revenue", _period(), fact_id="F1")
    # Only web_a has a DELIVERED shipment — 100.0.
    assert fact.value == Decimal("100")
    assert fact.unit == "money"


async def test_collected_and_refund_facts(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    await _seed_world(db, tenant_id)
    collected = await compute_fact(db, tenant_id, "collected_revenue", _period(), fact_id="F1")
    refunds = await compute_fact(db, tenant_id, "refund_amount", _period(), fact_id="F2")
    assert collected.value == Decimal("100")
    assert refunds.value == Decimal("20")


async def test_foreign_tenant_compute_returns_zero(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    await _seed_world(db, tenant_id)
    # A different tenant's run compiles the same statement — and sees NOTHING.
    fact = await compute_fact(db, uuid.uuid4(), "orders_placed", _period(), fact_id="F1")
    assert fact.value == 0


async def test_composite_metrics_are_rejected_not_improvised(db, tenant_ctx):
    with pytest.raises(UnsupportedFilter):
        compile_metric("net_revenue", tenant_ctx.tenant_id, _period())


async def test_unknown_channel_dimension_rejected_where_the_column_does_not_exist(db, tenant_ctx):
    # shipments carry no channel column — the compiler refuses instead of
    # silently dropping the filter (§4.3).
    with pytest.raises(UnsupportedFilter):
        compile_metric("shipped_orders", tenant_ctx.tenant_id, _period(), channel="web")


async def test_status_history_rows_exist_for_seeded_orders(db, tenant_ctx):
    # D1 resolved: the history table exists; a seeded transition is visible
    # with its recorded time — the event view's basis (§6.7).
    tenant_id = tenant_ctx.tenant_id
    world = await _seed_world(db, tenant_id)
    db.add(
        OrderStatusHistory(
            tenant_id=tenant_id,
            order_id=world["web_a"].id,
            from_status="pending",
            to_status="fulfilled",
        )
    )
    await db.flush()
    rows = (
        (
            await db.execute(
                select(OrderStatusHistory).where(
                    OrderStatusHistory.tenant_id == tenant_id,
                    OrderStatusHistory.order_id == world["web_a"].id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].to_status == "fulfilled"

"""The comparison and driver tools return what the analytics store collected.

The store keeps comparisons and drivers in dicts keyed by reference. The two tool adapters
iterated the dict itself, so they got the KEYS (strings) and raised
``'str' object has no attribute 'label'`` / ``'kind'`` on every call that found anything.
Nothing exercised them: the existing tests only checked they were registered. In a real run the
sales assistant burned its tool budget on these two failures and answered with an apology.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.ai.agents.sales_intelligence.tools import (
    _si_analyze_drivers,
    _si_compare_periods,
)
from app.modules.customers.models import Customer
from app.modules.orders.models import Order

NOW = datetime.now(UTC)


async def _orders(db, tenant_id, *, count: int, days_ago: int, total: str, tag: str) -> None:
    customer = Customer(tenant_id=tenant_id, name=f"c-{tag}")
    db.add(customer)
    await db.flush()
    for i in range(count):
        db.add(
            Order(
                tenant_id=tenant_id,
                number=f"{tag}-{i}",
                customer_id=customer.id,
                status="delivered",
                grand_total=Decimal(total),
                channel="web",
                placed_at=NOW - timedelta(days=days_ago, hours=i),
            )
        )
    await db.flush()


async def _two_periods(db, tenant_ctx) -> None:
    # Current 30 days: 6 orders of 200. Previous 30 days: 3 orders of 100.
    await _orders(db, tenant_ctx.tenant_id, count=6, days_ago=5, total="200.00", tag="cur")
    await _orders(db, tenant_ctx.tenant_id, count=3, days_ago=40, total="100.00", tag="prev")


async def test_compare_periods_returns_the_comparison_rows(db, tenant_ctx):
    await _two_periods(db, tenant_ctx)

    out = await _si_compare_periods(db, tenant_ctx.tenant_id, metric_name="orders_placed", days=30)

    assert out["comparisons"], "a comparison between two populated periods must be reported"
    row = out["comparisons"][0]
    assert set(row) == {"label", "left_fact_id", "right_fact_id", "delta", "delta_pct"}
    assert isinstance(row["label"], str) and row["label"]
    assert Decimal(row["delta"]) == Decimal("3")


async def test_analyze_drivers_returns_the_driver_rows(db, tenant_ctx):
    await _two_periods(db, tenant_ctx)

    out = await _si_analyze_drivers(db, tenant_ctx.tenant_id, days=30)

    assert out["drivers"], "a revenue change between two populated periods has drivers"
    row = out["drivers"][0]
    assert set(row) == {"kind", "orders_contribution", "aov_contribution", "total_delta"}
    assert isinstance(row["kind"], str) and row["kind"]
    # The shop's default primary sales metric is orders_placed, so the "total" being
    # decomposed is the order count: 6 now against 3 before.
    assert Decimal(row["total_delta"]) == Decimal("3")
    assert Decimal(row["orders_contribution"]) + Decimal(row["aov_contribution"]) == Decimal(
        row["total_delta"]
    )

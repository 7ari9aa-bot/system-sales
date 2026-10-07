"""§116 PERFORMANCE TESTING — hot-path latency budgets under real load.

§116 names the shapes to load (concurrent users, webhook/AI bursts, bulk actions,
large tables, connection pressure). The whole matrix cannot live in a unit-test
job, but the three HOTTEST transactional paths can, and those are the ones a
regression actually slows down unnoticed:

  * order create / checkout rules  -> OrderService.create_order (price ladder +
    sellability gate + stock reserve + totals + reservation + outbox)
  * analytics overview             -> analytics.service.revenue_summary
    (gross/refund/net/count/AOV aggregation over the orders created above)
  * customer 360 read              -> Customer360Service.build (profile + recent
    orders + payments + conversations + tasks + merged timeline on one screen)

BUDGETS (documented, asserted):
  create_order    p95 <= 300 ms
  revenue_summary p95 <= 250 ms
  get_360         p95 <= 150 ms

These are deliberately CONSERVATIVE per-call budgets sized for a cold shared CI
runner, not for a tuned load rig. The point is a floor under latency, not a
benchmark: an accidental N+1, a lost index, or a scan that used to be a seek
pushes a single call past these numbers on ordinary data and turns the suite red.
The standalone ``scripts/load_test.py`` remains the venue for throughput/concurrency
numbers; this file is the CI gate that a hot path did not silently regress.

VENUE: these tests are DB-backed and assert against REAL services on REAL
PostgreSQL. They SKIP LOCALLY without ``DATABASE_URL_APP_ADMIN`` (see
tests/conftest.py::db_url) and RUN in CI's backend job (ci.yml provisions the
``sales_app`` role + schema). They are safe in CI: every write happens inside the
per-test transaction that conftest rolls back, so nothing persists and the timing
loop never contends another tenant's rows.

These budgets are meaningful only when a database round trip is small relative
to a hot-path budget. Local databases reached through a VM or port-forward can
add tens of milliseconds of fixed transport delay. Outside GitHub Actions, this
test measures SELECT 1 first and skips when its median round-trip exceeds 10 ms.
GitHub Actions never takes that skip path; its service-container run remains the
required performance gate.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.service import revenue_summary
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.customers.timeline import Customer360Service
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.service import OrderService

# --- documented budgets (ms). Keep in sync with the module docstring. --------
BUDGET_CREATE_ORDER_MS = 300.0
BUDGET_REVENUE_SUMMARY_MS = 250.0
BUDGET_GET_360_MS = 150.0

# --- iteration counts: enough samples for a stable p95, small enough to keep
# the CI job seconds, not minutes. --------------------------------------------
CREATE_ITERS = 25
READ_ITERS = 40
WARMUP_ITERS = 3
LOCAL_DB_RTT_LIMIT_MS = 10.0


def _percentile(samples: list[float], q: float) -> float:
    """Nearest-rank percentile over latencies in MILLISECONDS."""
    assert samples, "no samples measured"
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


async def _measure(
    label: str,
    fn: Callable[[], Coroutine[Any, Any, Any]],
    *,
    iters: int,
) -> list[float]:
    """Run ``fn`` ``WARMUP + iters`` times, timing only the measured rounds.

    Every round's result is asserted truthy-by-caller; a hot path that returns
    nothing (a broken fast branch) must not be allowed to 'pass' by being fast.
    """
    for _ in range(WARMUP_ITERS):
        await fn()
    samples: list[float] = []
    for _ in range(iters):
        start = time.perf_counter()
        result = await fn()
        samples.append((time.perf_counter() - start) * 1000.0)
        assert result is not None, f"{label}: measured call returned None"
    return samples


async def _seed_orderable_stock(db: AsyncSession, tenant_id: uuid.UUID) -> tuple[Any, Any]:
    """A published product/variant with deep stock + a buyer, for checkout.

    Reuses the exact recipe tests/test_order_idempotency.py::_seed_checkout uses
    (create_product -> publish active -> add_variant -> InventoryService.move in),
    so create_order's sellability + reserve guards are satisfied rather than
    tripped mid-loop. Stock is deep because each timed create_order reserves one
    unit and a reserve failure would abort the run for the wrong reason.
    """
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "webchat", f"perf-{uuid.uuid4().hex[:10]}", name="Perf Buyer"
    )
    warehouse = Warehouse(
        tenant_id=tenant_id, name="Perf WH", code=f"WH-{uuid.uuid4().hex[:6].upper()}"
    )
    db.add(warehouse)
    await db.flush()
    product = await CatalogService.create_product(
        db, tenant_id, title="Perf Widget", slug=f"pw-{uuid.uuid4().hex[:10]}"
    )
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"PWG-{uuid.uuid4().hex[:6].upper()}", price="25.50"
    )
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=CREATE_ITERS * 5,
        reason="purchase",
    )
    return customer, variant


async def test_hot_path_latency_budgets(db, tenant_ctx) -> None:  # noqa: ANN001
    """Order create -> analytics overview -> customer 360: each p95 within budget.

    The three run in one test on purpose: the analytics/360 reads are only
    meaningful when there are real orders + a real customer to aggregate, and
    measuring them against the freshly-written data is the same shape a merchant
    dashboard hits seconds after a checkout.
    """
    if os.getenv("GITHUB_ACTIONS", "").lower() != "true":
        round_trip_samples = await _measure(
            "database_round_trip",
            lambda: db.scalar(text("SELECT 1")),
            iters=7,
        )
        round_trip_p50 = _percentile(round_trip_samples, 0.50)
        if round_trip_p50 > LOCAL_DB_RTT_LIMIT_MS:
            pytest.skip(
                "local PostgreSQL round-trip baseline is "
                f"{round_trip_p50:.1f}ms (limit {LOCAL_DB_RTT_LIMIT_MS:.0f}ms); "
                "run in the GitHub Actions service-container job for the "
                "authoritative latency gate"
            )

    tenant_id = tenant_ctx.tenant_id
    customer, variant = await _seed_orderable_stock(db, tenant_id)

    # 1) ORDER CREATE / CHECKOUT RULES -------------------------------------
    async def create() -> Any:
        return await OrderService.create_order(
            db,
            tenant_id,
            customer.id,
            [{"variant_id": str(variant.id), "quantity": 1}],
            channel="webchat",
        )

    create_samples = await _measure("create_order", create, iters=CREATE_ITERS)
    create_p95 = _percentile(create_samples, 0.95)

    # 2) ANALYTICS OVERVIEW (aggregates the orders just created) -----------
    now = _utcnow()
    since = _days_ago(now, 7)

    async def revenue() -> Any:
        return await revenue_summary(db, tenant_id, since=since, until=now)

    revenue_samples = await _measure("revenue_summary", revenue, iters=READ_ITERS)
    revenue_p95 = _percentile(revenue_samples, 0.95)

    # 3) CUSTOMER 360 READ --------------------------------------------------
    async def profile() -> Any:
        # The 360 read lives in its own read-model module now; the customers
        # router (router.py::get_customer_360) serves it through this: profile +
        # recent orders + payments + conversations + tasks + merged timeline.
        return await Customer360Service.build(db, tenant_id, customer.id)

    profile_samples = await _measure("get_360", profile, iters=READ_ITERS)
    profile_p95 = _percentile(profile_samples, 0.95)

    report = (
        f"\n  create_order    p50={_percentile(create_samples, 0.50):7.1f}ms "
        f"p95={create_p95:7.1f}ms  budget={BUDGET_CREATE_ORDER_MS:.0f}ms\n"
        f"  revenue_summary p50={_percentile(revenue_samples, 0.50):7.1f}ms "
        f"p95={revenue_p95:7.1f}ms  budget={BUDGET_REVENUE_SUMMARY_MS:.0f}ms\n"
        f"  get_360         p50={_percentile(profile_samples, 0.50):7.1f}ms "
        f"p95={profile_p95:7.1f}ms  budget={BUDGET_GET_360_MS:.0f}ms"
    )

    assert create_p95 <= BUDGET_CREATE_ORDER_MS, f"create_order p95 breached budget{report}"
    assert revenue_p95 <= BUDGET_REVENUE_SUMMARY_MS, f"revenue_summary p95 breached budget{report}"
    assert profile_p95 <= BUDGET_GET_360_MS, f"get_360 p95 breached budget{report}"


# --- tiny time helpers (avoid importing app datetime utils into the harness) --
def _utcnow():  # noqa: ANN202
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _days_ago(now, days: int):  # noqa: ANN001, ANN202
    from datetime import timedelta

    return now - timedelta(days=days)

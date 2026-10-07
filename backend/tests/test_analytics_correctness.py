"""Analytics correctness tests — gaps M3 (refunded money as revenue) and
M10 (UTC day buckets, low_stock counting zeros).

Two classes of case:

* Pure / unit cases that run with no database at all: the merchant-day bucketing
  rule, the net-of-refund arithmetic, and the HTTP surface of the new endpoints.
* DB-backed cases that seed payments and refunds at explicit instants. These
  skip locally when DATABASE_URL_APP_ADMIN is unset and run in CI.

The naming contract these tests pin: every money figure that leaves analytics
says which family it belongs to (`gross_revenue` / `net_revenue` /
`gross_aov` / `net_aov`), so no caller can label a gross number "revenue".
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.customers.service import CustomerService
from app.modules.orders.models import Order, OrderPayment, Refund

# A fixed epoch far from "now" is not enough: the window functions read the
# columns we set explicitly, so every seed below places its own instants.
DAY = datetime(2026, 3, 14, tzinfo=UTC)
W1_SINCE = datetime(2026, 3, 1, tzinfo=UTC)
W1_UNTIL = datetime(2026, 3, 15, tzinfo=UTC)
W2_SINCE = W1_UNTIL
W2_UNTIL = datetime(2026, 4, 1, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return DAY + timedelta(minutes=minutes)


# ------------------------------------------------- pure: net-of-refund -----


def test_net_of_a_full_refund_is_zero_with_no_excess() -> None:
    from app.modules.analytics.service import net_of

    assert net_of(Decimal("100.00"), Decimal("100.00")) == (Decimal("0.00"), Decimal("0.00"))


def test_net_of_a_partial_refund_keeps_the_remainder() -> None:
    from app.modules.analytics.service import net_of

    assert net_of(Decimal("100.00"), Decimal("40.00")) == (
        Decimal("60.00"),
        Decimal("0.00"),
    )


def test_net_of_never_goes_negative_and_reports_the_excess() -> None:
    """A refund that leaves in a window with no matching gross must not turn
    that window's *revenue* negative — the part that could not be subtracted
    is reported separately instead of vanishing."""
    from app.modules.analytics.service import net_of

    assert net_of(Decimal("0.00"), Decimal("60.00")) == (
        Decimal("0.00"),
        Decimal("60.00"),
    )


def test_net_of_quantizes_to_money_scale() -> None:
    from app.modules.analytics.service import net_of

    net, excess = net_of(Decimal("10"), Decimal("3.333"))
    assert net == Decimal("6.67")
    assert excess == Decimal("0.00")


# ------------------------------------------- pure: one revenue status list ---


def test_gross_and_net_read_one_payment_status_vocabulary() -> None:
    """M3's other half: which rows COUNT must be one answer, not three copies.

    ``net_revenue`` subtracts from ``revenue``, so the two share their gross
    side by construction — but the payment-status filter itself was a typed-out
    SQL string here, a second copy of it in the metric registry, and a third in
    ``orders/money.COLLECTED_PAYMENT_STATUSES``. The moment one of the three is
    edited, gross and net disagree about which payments are revenue and a
    dashboard starts averaging two different orders-of-idea. The filter is now
    RENDERED from the registry, and the registry's list is pinned against
    orders' own money rule set.
    """
    from app.modules.analytics import service as analytics
    from app.modules.orders import money as orders_money
    from app.modules.platform.metrics import MetricRegistry

    revenue_status = MetricRegistry.get("revenue").filters["status"]
    # analytics holds no copy of the list: the fragment IS the registry, rendered
    assert analytics._GROSS_PAYMENT_STATUSES == analytics._status_sql(revenue_status)
    # the registry and orders' money rule set name the same payments
    assert tuple(revenue_status) == orders_money.COLLECTED_PAYMENT_STATUSES
    # and `net_revenue` is defined as this metric minus refunds, never as its
    # own re-derivation of what counts
    registry_net = MetricRegistry.get("net_revenue").filters
    assert registry_net["revenue"] == "revenue"
    assert registry_net["minus"] == "refunded_amount"


def test_the_order_existence_filter_is_rendered_from_the_registry_too() -> None:
    """``orders_count`` is the AOV denominator, so its status filter is part of
    the money story: a cancelled order excluded there must not be excluded
    differently by hand somewhere else."""
    from app.modules.analytics import service as analytics
    from app.modules.platform.metrics import MetricRegistry

    excluded = MetricRegistry.get("orders_count").filters["status_excluded"]
    assert analytics._UNPLACED_ORDER_STATUSES == analytics._status_sql(excluded)


def test_a_status_that_is_not_a_word_cannot_reach_the_sql() -> None:
    """The fragment is built from source-controlled text, but building SQL by
    string means the builder is the seam that must hold."""
    from app.modules.analytics.service import _status_sql

    assert _status_sql(["captured", "refunded"]) == "('captured', 'refunded')"
    with pytest.raises(ValueError):
        _status_sql(["captured') OR 1=1 --"])
    with pytest.raises(ValueError):
        _status_sql([])


# ------------------------------------------------ pure: merchant-day rule --


def test_merchant_day_pushes_a_late_utc_sale_into_the_next_day() -> None:
    """23:30 UTC is 03:30 the NEXT day in UTC+4 — the register's exact bug."""
    from app.modules.analytics.timekit import merchant_day

    late = datetime(2026, 3, 14, 23, 30, tzinfo=UTC)
    assert merchant_day(late, "UTC") == date(2026, 3, 14)
    assert merchant_day(late, "Asia/Dubai") == date(2026, 3, 15)


def test_merchant_day_pulls_an_early_utc_sale_back_a_day_west_of_prime() -> None:
    from app.modules.analytics.timekit import merchant_day

    early = datetime(2026, 3, 14, 0, 30, tzinfo=UTC)
    assert merchant_day(early, "America/New_York") == date(2026, 3, 13)


def test_merchant_day_boundary_is_exactly_at_local_midnight() -> None:
    """The boundary itself is where bugs live: 20:00 UTC is local midnight in
    UTC+4, so 19:59 is day N and 20:00 is day N+1."""
    from app.modules.analytics.timekit import merchant_day

    assert merchant_day(datetime(2026, 3, 14, 19, 59, tzinfo=UTC), "Asia/Dubai") == date(
        2026, 3, 14
    )
    assert merchant_day(datetime(2026, 3, 14, 20, 0, tzinfo=UTC), "Asia/Dubai") == date(2026, 3, 15)


def test_merchant_day_window_returns_utc_instants_for_the_bucket() -> None:
    from app.modules.analytics.timekit import merchant_day_window

    since, until = merchant_day_window(date(2026, 3, 14), "Asia/Dubai")
    assert since == datetime(2026, 3, 13, 20, 0, tzinfo=UTC)
    assert until == datetime(2026, 3, 14, 20, 0, tzinfo=UTC)


def test_resolve_timezone_falls_back_to_the_deployment_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.analytics import timekit

    monkeypatch.delenv(timekit.REPORTING_TZ_ENV, raising=False)
    assert timekit.resolve_timezone(None) == timekit.FALLBACK_TIMEZONE
    monkeypatch.setenv(timekit.REPORTING_TZ_ENV, "Europe/Paris")
    assert timekit.resolve_timezone(None) == "Europe/Paris"
    # A caller-supplied zone always wins over the deployment default.
    assert timekit.resolve_timezone("Asia/Dubai") == "Asia/Dubai"


def test_resolve_timezone_refuses_a_zone_that_does_not_exist() -> None:
    from app.modules.analytics.timekit import UnknownTimezoneError, resolve_timezone

    with pytest.raises(UnknownTimezoneError):
        resolve_timezone("Mars/Olympus_Mons")


# --------------------------------------------------- HTTP surface guards ---


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/analytics/revenue/summary",
        "/api/v1/analytics/daily-series",
        "/api/v1/analytics/inventory/stock-health",
    ],
)
def test_analytics_exposes_the_corrected_endpoints(path: str) -> None:
    assert path in set(create_app().openapi()["paths"])


def test_daily_series_exposes_its_timezone_parameter() -> None:
    """The bucketing zone must be on the wire, or the service can honour it
    while the router silently always reports UTC."""
    params = create_app().openapi()["paths"]["/api/v1/analytics/daily-series"]["get"]["parameters"]
    assert "timezone" in {p["name"] for p in params}


# ---------------------------------------------------------- DB fixtures ---


async def _customer_id(db: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", name="Buyer"
    )
    return customer.id


async def _collected(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    amount: str,
    paid_at: datetime,
    placed_at: datetime | None = None,
) -> OrderPayment:
    """One settled payment (and the order behind it) at explicit instants."""
    order = Order(
        tenant_id=tenant_id,
        customer_id=await _customer_id(db, tenant_id),
        number=f"SO-{uuid.uuid4().hex[:10].upper()}",
        status="completed",
        grand_total=Decimal(amount),
        placed_at=placed_at or paid_at,
    )
    db.add(order)
    await db.flush()
    payment = OrderPayment(
        tenant_id=tenant_id,
        order_id=order.id,
        method="cash",
        status="captured",
        amount=Decimal(amount),
        paid_at=paid_at,
    )
    db.add(payment)
    await db.flush()
    return payment


async def _refund(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment: OrderPayment,
    *,
    amount: str,
    processed_at: datetime | None,
    status: str = "processed",
    created_at: datetime | None = None,
) -> Refund:
    refund = Refund(
        tenant_id=tenant_id,
        payment_id=payment.id,
        amount=Decimal(amount),
        status=status,
        processed_at=processed_at,
    )
    # created_at is server-default now(); a bucketed read model needs the row to
    # sit in the window under test, so it is placed explicitly when given.
    if created_at is not None:
        refund.created_at = created_at
    db.add(refund)
    await db.flush()
    return refund


# --------------------------------------------------------- M3: money ------


async def test_full_refund_leaves_gross_untouched_and_net_zero(
    db: AsyncSession, tenant_ctx
) -> None:
    """The figure labelled gross must still contain the refunded money (that is
    what makes `net = gross - refund` hold); only net may drop it."""
    from app.modules.analytics.service import revenue, revenue_summary

    tid = tenant_ctx.tenant_id
    payment = await _collected(db, tid, amount="100.00", paid_at=_at(60))
    await _refund(db, tid, payment, amount="100.00", processed_at=_at(120))

    assert await revenue(db, tid, since=W1_SINCE, until=W1_UNTIL) == Decimal("100.00")
    summary = await revenue_summary(db, tid, since=W1_SINCE, until=W1_UNTIL)
    assert summary["gross_revenue"] == Decimal("100.00")
    assert summary["net_revenue"] == Decimal("0.00")
    assert summary["refunded_amount"] == Decimal("100.00")
    assert summary["refund_excess"] == Decimal("0.00")


async def test_partial_refund_nets_the_unreturned_part(db: AsyncSession, tenant_ctx) -> None:
    from app.modules.analytics.service import revenue_summary

    tid = tenant_ctx.tenant_id
    payment = await _collected(db, tid, amount="100.00", paid_at=_at(60))
    await _refund(db, tid, payment, amount="40.00", processed_at=_at(120))

    summary = await revenue_summary(db, tid, since=W1_SINCE, until=W1_UNTIL)
    assert summary["gross_revenue"] == Decimal("100.00")
    assert summary["net_revenue"] == Decimal("60.00")
    assert summary["net_aov"] == Decimal("60.00")
    assert summary["gross_aov"] == Decimal("100.00")


async def test_second_refund_in_a_later_window_is_not_double_subtracted(
    db: AsyncSession, tenant_ctx
) -> None:
    """40 back in W1, 60 more in W2, for one 100.00 payment.

    W1 keeps its 60.00. W2 collected nothing, so its revenue must read 0.00
    (never -60.00) with the 60.00 surfaced as refund_excess. Across the whole
    period the refund total is 100.00 and net is 0.00 — one subtraction.
    """
    from app.modules.analytics.service import net_revenue, revenue_summary

    tid = tenant_ctx.tenant_id
    payment = await _collected(db, tid, amount="100.00", paid_at=_at(60))
    await _refund(db, tid, payment, amount="40.00", processed_at=_at(120))
    await _refund(db, tid, payment, amount="60.00", processed_at=_at(60 + 24 * 60))

    w1 = await revenue_summary(db, tid, since=W1_SINCE, until=W1_UNTIL)
    assert w1["gross_revenue"] == Decimal("100.00")
    assert w1["net_revenue"] == Decimal("60.00")

    w2 = await revenue_summary(db, tid, since=W2_SINCE, until=W2_UNTIL)
    assert w2["gross_revenue"] == Decimal("0.00")
    assert w2["refunded_amount"] == Decimal("60.00")
    assert w2["net_revenue"] == Decimal("0.00")
    assert w2["refund_excess"] == Decimal("60.00")
    # The public metric must agree with the summary, not return a negative.
    assert await net_revenue(db, tid, since=W2_SINCE, until=W2_UNTIL) == Decimal("0.00")

    whole = await revenue_summary(db, tid, since=W1_SINCE, until=W2_UNTIL)
    assert whole["gross_revenue"] == Decimal("100.00")
    assert whole["refunded_amount"] == Decimal("100.00")
    assert whole["net_revenue"] == Decimal("0.00")
    assert whole["refund_excess"] == Decimal("0.00")


async def test_refund_without_a_processed_stamp_is_not_dropped(
    db: AsyncSession, tenant_ctx
) -> None:
    """`approved` is an allowed refund status and is counted by the metric, but
    an approved row can legitimately carry no processed_at yet. Bucketing on
    processed_at alone makes that money invisible, so net stays overstated."""
    from app.modules.analytics.service import revenue_summary

    tid = tenant_ctx.tenant_id
    payment = await _collected(db, tid, amount="100.00", paid_at=_at(60))
    await _refund(
        db,
        tid,
        payment,
        amount="40.00",
        processed_at=None,
        status="approved",
        created_at=_at(90),
    )

    summary = await revenue_summary(db, tid, since=W1_SINCE, until=W1_UNTIL)
    assert summary["refunded_amount"] == Decimal("40.00")
    assert summary["net_revenue"] == Decimal("60.00")


async def test_summary_reports_the_tenants_currency_not_a_literal(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.core.tenancy import resolve_tenant_currency
    from app.modules.analytics.service import revenue_summary

    tid = tenant_ctx.tenant_id
    summary = await revenue_summary(db, tid, since=W1_SINCE, until=W1_UNTIL)
    assert summary["currency"] == await resolve_tenant_currency(db, tid)


# ---------------------------------------------------------- M10: tz -------


async def test_daily_series_buckets_a_late_utc_sale_in_the_merchant_day(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.analytics.service import daily_revenue_series

    tid = tenant_ctx.tenant_id
    # 23:30 UTC on 14 March = 03:30 on 15 March in UTC+4.
    await _collected(db, tid, amount="70.00", paid_at=datetime(2026, 3, 14, 23, 30, tzinfo=UTC))

    utc_rows = await daily_revenue_series(db, tid, since=W1_SINCE, until=W2_UNTIL, timezone="UTC")
    assert [r["day"] for r in utc_rows] == ["2026-03-14"]

    local_rows = await daily_revenue_series(
        db, tid, since=W1_SINCE, until=W2_UNTIL, timezone="Asia/Dubai"
    )
    assert [r["day"] for r in local_rows] == ["2026-03-15"]
    assert local_rows[0]["gross_revenue"] == Decimal("70.00")
    assert local_rows[0]["orders_count"] == 1


async def test_daily_series_net_never_goes_negative_on_a_refund_only_day(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.analytics.service import daily_revenue_series

    tid = tenant_ctx.tenant_id
    payment = await _collected(
        db, tid, amount="50.00", paid_at=datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
    )
    await _refund(
        db,
        tid,
        payment,
        amount="50.00",
        processed_at=datetime(2026, 3, 20, 9, 0, tzinfo=UTC),
    )

    rows = await daily_revenue_series(db, tid, since=W1_SINCE, until=W2_UNTIL, timezone="UTC")
    by_day = {r["day"]: r for r in rows}
    assert by_day["2026-03-10"]["gross_revenue"] == Decimal("50.00")
    assert by_day["2026-03-10"]["net_revenue"] == Decimal("50.00")
    assert by_day["2026-03-20"]["gross_revenue"] == Decimal("0.00")
    assert by_day["2026-03-20"]["net_revenue"] == Decimal("0.00")
    assert by_day["2026-03-20"]["refund_excess"] == Decimal("50.00")


# ------------------------------------------------------ M10: low stock ----


async def _balance(db: AsyncSession, tenant_id: uuid.UUID, *, on_hand: int, reserved: int):
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.models import InventoryBalance, Warehouse

    product = await CatalogService.create_product(
        db, tenant_id, title=f"P-{uuid.uuid4().hex[:8]}", slug=f"p-{uuid.uuid4().hex[:8]}"
    )
    variant = await CatalogService.add_variant(db, tenant_id, product.id, price="10.00")
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name=f"WH-{uuid.uuid4().hex[:6]}",
        code=f"W-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    balance = InventoryBalance(
        tenant_id=tenant_id,
        warehouse_id=warehouse.id,
        variant_id=variant.id,
        on_hand=on_hand,
        reserved=reserved,
    )
    db.add(balance)
    await db.flush()
    return balance


async def test_zero_available_is_out_of_stock_not_low_stock(db: AsyncSession, tenant_ctx) -> None:
    """The register's complaint: `available <= 2` folds an empty shelf into
    "low stock", so the alert is noise. The two must be separate counts and the
    field names must say which is which."""
    from app.modules.analytics.service import stock_health

    tid = tenant_ctx.tenant_id
    await _balance(db, tid, on_hand=0, reserved=0)  # empty shelf
    await _balance(db, tid, on_hand=2, reserved=2)  # reserved to zero
    await _balance(db, tid, on_hand=3, reserved=2)  # 1 left — genuinely low
    await _balance(db, tid, on_hand=50, reserved=0)  # healthy

    health = await stock_health(db, tid, low_stock_threshold=2)
    assert health["out_of_stock_count"] == 2
    assert health["low_stock_count"] == 1
    assert health["healthy_count"] == 1
    assert health["low_stock_threshold"] == 2


async def test_negative_available_is_counted_as_out_of_stock(db: AsyncSession, tenant_ctx) -> None:
    from app.modules.analytics.service import stock_health

    tid = tenant_ctx.tenant_id
    await _balance(db, tid, on_hand=1, reserved=4)

    health = await stock_health(db, tid, low_stock_threshold=2)
    assert health["out_of_stock_count"] == 1
    assert health["low_stock_count"] == 0

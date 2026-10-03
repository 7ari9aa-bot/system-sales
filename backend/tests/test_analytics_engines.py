"""The new analysis engines (spec §5.3/§5.4/§5.7) — pure, planted-truth tests.

Weekday seasonality must EXPLAIN a calendar-shape change and NOT explain a
behavioral one; the customer split must separate first-time buyers from
repeat ones; fulfillment rates must omit small-n carriers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.analytics.capabilities import (
    analyze_customers,
    analyze_fulfillment,
)
from app.modules.analytics.engines import (
    customer_split,
    seasonality_explains,
    weekday_profile,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


def _flat_series(days: int, daily: str) -> dict:
    return {
        START + timedelta(days=i, hours=i % 20): Decimal(daily)
        for i in range(days)
    }


def _customer_orders(counts: list[int], start_day: int) -> list[dict]:
    """counts[i] = orders placed by customer i, spread over the days."""
    orders = []
    for customer, count in enumerate(counts):
        for nth in range(count):
            orders.append({
                "customer_id": f"c-{customer}",
                "placed_at": START + timedelta(days=start_day + nth * 2),
            })
    return orders


# ------------------------------------------------------------ seasonality ---

def test_weekday_profile_lifts_the_busy_day():
    daily = {}
    for i in range(28):
        day = START + timedelta(days=i)
        # Friday (weekday 4) sells double.
        daily[day] = Decimal("1000") if day.weekday() == 4 else Decimal("500")
    profile = weekday_profile(daily)
    assert profile["الجمعة"] > 1.5
    assert 0.8 < profile["الاثنين"] < 1.2


def test_seasonality_explains_a_calendar_shape_change():
    # Previous window: 4 weeks of quiet days + one weekend lift pattern.
    # Current window: same weekday shape — the mix explains everything.
    previous = _flat_series(28, "500.00")
    current = _flat_series(28, "700.00")  # higher prices, same shape
    explained, gap = seasonality_explains(current, previous, tolerance=0.6)
    assert explained and gap is not None and gap <= 0.6


def test_seasonality_does_not_explain_a_behavior_change():
    # Same weekday shape, but the last week COLLAPSED to a third — a
    # weekday-mix projection cannot produce that.
    previous = _flat_series(28, "500.00")
    current = _flat_series(28, "500.00")
    for i in range(21, 28):
        current[START + timedelta(days=i, hours=i % 20)] = Decimal("150.00")
    explained, gap = seasonality_explains(current, previous, tolerance=0.15)
    assert not explained and gap > 0.15


def test_seasonality_with_no_previous_data_is_honest():
    explained, gap = seasonality_explains(_flat_series(14, "500.00"), {})
    assert explained is False and gap is None


# -------------------------------------------------------------- customers ---

def test_customer_split_separates_new_from_returning():
    # Customer 0: one order BEFORE the window, one INSIDE → returning.
    # Customer 1: first order INSIDE the window → new.
    orders = [
        {"customer_id": "c-0", "placed_at": START},
        {"customer_id": "c-0", "placed_at": START + timedelta(days=12)},
        {"customer_id": "c-1", "placed_at": START + timedelta(days=13)},
    ]
    split = customer_split(orders, window_start=START + timedelta(days=10))
    assert split == {"new": 1, "returning": 1}


def test_all_new_customers_when_store_is_new():
    orders = _customer_orders([1, 1, 1], start_day=0)
    split = customer_split(orders, START)
    assert split == {"new": 3, "returning": 0}


def test_capability_surfaces_the_split():
    orders = [
        {"customer_id": "c-0", "placed_at": START},
        {"customer_id": "c-0", "placed_at": START + timedelta(days=4)},
    ]
    result = analyze_customers(orders, window_start=START + timedelta(days=2))
    assert result.status == "ok"
    assert result.summary["identity_quality"].startswith("raw")


# ------------------------------------------------------------ fulfillment ---

def _shipments(rows: list[tuple[str, str]]) -> list[dict]:
    return [
        {
            "carrier": carrier,
            "status": status,
            "shipped_at": START,
            "delivered_at": START + timedelta(days=2) if status == "delivered" else None,
        }
        for carrier, status in rows
    ]


def test_fulfillment_rates_and_small_n_omission():
    rows = [("Bosta", "delivered")] * 15 + [("Bosta", "failed")] * 5
    rows += [("Tiny", "delivered")] * 3
    result = analyze_fulfillment(_shipments(rows), minimum_volume=10)
    carriers = {c["carrier"]: c for c in result.summary["carriers"]}
    assert "Tiny" not in carriers, "small-n carriers are omitted"
    assert carriers["Bosta"]["delivered"] == 15
    assert carriers["Bosta"]["rejected"] == 5


def test_average_days_to_deliver_computed_from_real_timestamps():
    rows = [("Bosta", "delivered")] * 12
    shipments = _shipments(rows)
    result = analyze_fulfillment(shipments, minimum_volume=10)
    carrier = result.summary["carriers"][0]
    assert carrier["avg_days_to_deliver"] == 2.0

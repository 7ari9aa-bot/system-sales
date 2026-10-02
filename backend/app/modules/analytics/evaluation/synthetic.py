"""Synthetic store generator (spec §17.1) — planted truth, known answers.

Produces the rows of a full synthetic store (orders, shipments, payments,
refunds) with SCENARIOS planted at known dates, plus the ground-truth
manifest the golden runner asserts against: expected facts, driver
direction, anomaly days, limitations. Deterministic under ``seed`` — the
same seed rebuilds the identical store, so a failing check reproduces.

Pure data: no DB, no models, no LLM. The seeding layer (tests/eval harness)
maps these dicts onto the orders-domain tables; the analytics layer then
computes over them exactly as it would over production data.

Scenarios (§17.1 minimum set, adapted to the real schema's vocabulary):
* BASELINE          — flat weekday-stable revenue, everything delivered
* AOV_DECLINE       — same order count, cheaper orders → AOV driver negative
* ORDERS_DECLINE    — fewer orders, same AOV → orders driver negative
* REVENUE_SPIKE     — one 4x day (anomaly: spike)
* REFUND_SPIKE      — refunds eat 40% of the current window
* IMMATURE_TAIL     — recent orders placed but NOT yet delivered (fake drop)
* CHANNEL_SHIFT     — web collapses, retail takes the volume
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

BASELINE_AOV = Decimal("500.00")
BASELINE_PER_DAY = 4  # orders per day on the flat line
WINDOW_DAYS = 60  # 30 days "current" + 30 days "previous"


class Scenario(StrEnum):
    BASELINE = "baseline"
    AOV_DECLINE = "aov_decline"
    ORDERS_DECLINE = "orders_decline"
    REVENUE_SPIKE = "revenue_spike"
    REFUND_SPIKE = "refund_spike"
    IMMATURE_TAIL = "immature_tail"
    CHANNEL_SHIFT = "channel_shift"


@dataclass(slots=True)
class SyntheticStore:
    """The generated rows + the truth manifest. Row dicts carry ISO datetimes
    and plain numbers — the seeding layer maps them onto the tables."""

    scenario: Scenario
    reference: datetime  # the "now" the store was generated around
    orders: list[dict] = field(default_factory=list)
    shipments: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    refunds: list[dict] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)


def generate_store(
    scenario: Scenario = Scenario.BASELINE, *, seed: int = 42, days: int = WINDOW_DAYS
) -> SyntheticStore:
    """Build the store. Deterministic: same (scenario, seed) → same rows."""
    rng = random.Random(seed)
    reference = datetime(2026, 10, 1, tzinfo=UTC)  # a FIXED anchor, not now()
    today_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)

    store = SyntheticStore(scenario=scenario, reference=reference)
    seq = 0

    def _add_order(*, days_back: int, total: str, channel: str = "web",
                   delivered_days_back: int | None = None) -> None:
        nonlocal seq
        seq += 1
        placed = today_start - timedelta(days=days_back) + timedelta(hours=rng.randint(0, 20))
        order_id = f"synthetic-{scenario.value}-{seq:04d}"
        store.orders.append({
            "id": order_id,
            "number": f"SYN-{seq:05d}",
            "customer_id": f"customer-{rng.randint(1, 40)}",
            "status": "fulfilled",
            "grand_total": float(Decimal(total)),
            "channel": channel,
            "placed_at": placed.isoformat(),
            "deleted_at": None,
        })
        if delivered_days_back is not None:
            delivered = today_start - timedelta(days=delivered_days_back)
            store.shipments.append({
                "id": f"shipment-{seq:04d}",
                "order_id": order_id,
                "carrier": "synthetic-carrier",
                "status": "delivered",
                "shipped_at": (delivered - timedelta(days=1)).isoformat(),
                "delivered_at": delivered.isoformat(),
            })
            store.payments.append({
                "id": f"payment-{seq:04d}",
                "order_id": order_id,
                "method": "cod",
                "status": "captured",
                "amount": float(Decimal(total)),
                "paid_at": delivered.isoformat(),
            })
        return order_id

    for day_back in range(days - 1, 0, -1):
        current = day_back < 30  # the most recent 30 days are the CURRENT window
        aov = BASELINE_AOV
        count = BASELINE_PER_DAY
        channel = "web"

        if scenario is Scenario.AOV_DECLINE and current:
            aov = Decimal("360.00")  # AOV drops 28%, count unchanged
        if scenario is Scenario.ORDERS_DECLINE and current:
            count = 2  # count drops 50%, AOV unchanged
        if scenario is Scenario.CHANNEL_SHIFT and current and day_back % 2 == 0:
            # alternate channels so the breakdown shows the shift
            channel = "retail" if day_back % 4 == 0 else "web"

        for _ in range(count):
            jitter = Decimal(str(rng.uniform(-40, 40)))
            total = (aov + jitter).quantize(Decimal("0.01"))
            delivered_back = day_back - 2 if day_back >= 3 else None
            if scenario is Scenario.IMMATURE_TAIL and current and day_back <= 3:
                delivered_back = None  # recent orders placed, NOT delivered yet
            _add_order(days_back=day_back, total=str(total), channel=channel,
                       delivered_days_back=delivered_back)

    if scenario is Scenario.REVENUE_SPIKE:
        spike_day = 12
        for _ in range(3):
            _add_order(days_back=spike_day, total=str(BASELINE_AOV * 4),
                       delivered_days_back=spike_day - 2)
        store.manifest["anomaly_days"] = [
            (today_start - timedelta(days=spike_day)).date().isoformat()
        ]
        store.manifest["anomaly_direction"] = "spike"

    if scenario is Scenario.REFUND_SPIKE:
        refundable = [p for p in store.payments
                      if datetime.fromisoformat(p["paid_at"])
                      >= today_start - timedelta(days=30)]
        for payment in refundable[: max(1, len(refundable) // 2)]:
            store.refunds.append({
                "id": f"refund-{payment['id']}",
                "payment_id": payment["id"],
                "amount": float(Decimal(str(payment["amount"])) * Decimal("0.4")),
                "status": "processed",
                "processed_at": payment["paid_at"],
            })
        store.manifest["refund_heavy_current_window"] = True

    if scenario is Scenario.IMMATURE_TAIL:
        store.manifest["immature_tail_days"] = 3
        store.manifest["expected"] = "recent days show NO delivered revenue yet"

    if scenario is Scenario.AOV_DECLINE:
        store.manifest["expected_driver"] = "aov"
    if scenario is Scenario.ORDERS_DECLINE:
        store.manifest["expected_driver"] = "orders"
    if scenario is Scenario.CHANNEL_SHIFT:
        store.manifest["expected_shift"] = "retail gains share in the current window"

    return store

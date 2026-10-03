"""Anomaly detection (spec §5.2) — statistical, seasonal, never the LLM's.

v1 pipeline on a DAILY money series: same-weekday median baseline →
residual → robust z (MAD-based) → minimum volume → effect size → dedupe.
This is explicit SHORT-HISTORY mode (same-weekday median +
``insufficient_history`` flag); STL lands when ≥8 weeks of history exists.
Dedupe keeps the strongest day of any contiguous 3-day run so one incident
does not report as three.

Inputs are Decimal (money); floats appear only inside the z-score math and
every reported value stays Decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

_MIN_HISTORY_DAYS = 14
_ROBUST_Z_THRESHOLD = 3.0
_MAD_TO_STD = 1.4826
_MIN_VOLUME = Decimal("100")
_MIN_EFFECT_PCT = Decimal("0.25")  # 25% off the baseline


@dataclass(frozen=True, slots=True)
class Anomaly:
    day: date
    observed: Decimal
    baseline: Decimal
    z: float
    direction: Literal["spike", "drop"]
    # True while the window is short of the 8-week STL requirement: the
    # anomaly is reportable but its confidence is capped downstream (§9.3).
    insufficient_history: bool = True


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def detect_anomalies(
    series: dict[date, Decimal],
    *,
    minimum_volume: Decimal = _MIN_VOLUME,
    effect_pct: Decimal = _MIN_EFFECT_PCT,
) -> list[Anomaly]:
    """Scan a daily money series for anomalies worth reporting."""
    if len(series) < _MIN_HISTORY_DAYS:
        return []

    by_weekday: dict[int, list[float]] = {}
    for day, value in series.items():
        by_weekday.setdefault(day.weekday(), []).append(float(value))
    medians = {weekday: _median(vals) for weekday, vals in by_weekday.items()}

    residuals = {
        day: float(value) - medians[day.weekday()] for day, value in series.items()
    }
    median_residual = _median(list(residuals.values()))
    mad = _median([abs(r - median_residual) for r in residuals.values()])
    robust_std = mad * _MAD_TO_STD

    candidates: list[Anomaly] = []
    for day in sorted(series):
        value = series[day]
        if value < minimum_volume:
            continue
        baseline = Decimal(str(round(medians[day.weekday()], 2)))
        if baseline <= 0:
            continue
        effect = abs(value - baseline) / baseline
        if effect < effect_pct:
            continue
        if robust_std:
            z = residuals[day] / robust_std
        elif residuals[day] != 0:
            # A zero-variance series that suddenly deviates is the strongest
            # signal there is; the effect/volume gates still contain it.
            z = 99.0
        else:
            z = 0.0
        if abs(z) < _ROBUST_Z_THRESHOLD:
            continue
        candidates.append(
            Anomaly(
                day=day,
                observed=value,
                baseline=baseline,
                z=round(z, 2),
                direction="spike" if value > baseline else "drop",
                insufficient_history=len(series) < 56,
            )
        )

    kept: list[Anomaly] = []
    for candidate in sorted(candidates, key=lambda a: -abs(a.z)):
        if all(abs((candidate.day - other.day).days) > 2 for other in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda a: a.day)


# ----------------------------------------------------- seasonality (§5.3) ---

_WEEKDAYS_AR = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")


def weekday_profile(daily: dict) -> dict[str, float]:
    """Per-weekday lift vs the overall median (1.0 = no weekday effect).

    A day whose series value is zero/missing contributes to the overall
    median only through the days that exist — quiet days are data, not gaps.
    """
    values = [float(v) for v in daily.values() if v]
    if not values:
        return {}
    overall = _median(values)
    if overall <= 0:
        return {}
    by_weekday: dict[int, list[float]] = {}
    for day, value in daily.items():
        by_weekday.setdefault(day.weekday(), []).append(float(value))
    return {
        _WEEKDAYS_AR[weekday]: round(_median(vals) / overall, 3)
        for weekday, vals in sorted(by_weekday.items())
    }


def seasonality_explains(
    daily_current: dict, daily_previous: dict, *, tolerance: float = 0.15
) -> tuple[bool, float | None]:
    """Does the weekday MIX explain the change between two windows?

    Projects the current window using the PREVIOUS window's per-weekday
    medians applied to the current window's weekday day-counts, then compares
    the projection to the actual. A small gap means the change is mostly
    calendar shape, not behavior. Returns (explained, unexplained_share):
    None when either window lacks a usable baseline (§5.3 — honest None).
    """
    prev_values = [float(v) for v in daily_previous.values() if v]
    if not prev_values:
        return False, None
    prev_by_weekday: dict[int, list[float]] = {}
    for day, value in daily_previous.items():
        prev_by_weekday.setdefault(day.weekday(), []).append(float(value))
    prev_medians = {wd: _median(vals) for wd, vals in prev_by_weekday.items()}
    if not any(m > 0 for m in prev_medians.values()):
        return False, None

    projected = 0.0
    for day in daily_current:
        projected += prev_medians.get(day.weekday(), 0.0)
    actual = sum(float(v) for v in daily_current.values())
    if projected <= 0:
        return False, None
    gap = abs(actual - projected) / projected
    return gap <= tolerance, round(gap, 3)


# ------------------------------------------------------ customers (§5.4) ----

def customer_split(orders: list[dict], window_start: datetime) -> dict[str, int]:
    """New vs returning customers in a window.

    New = the customer's FIRST order falls inside the window; returning =
    they ordered before it. Orders must carry customer_id and placed_at.
    """
    first_order: dict[str, datetime] = {}
    window_orders: dict[str, datetime] = {}
    for order in orders:
        customer = str(order["customer_id"])
        placed = order["placed_at"]
        first = first_order.get(customer)
        if first is None or placed < first:
            first_order[customer] = placed
        if placed >= window_start:
            window_orders[customer] = placed
    new = sum(
        1
        for customer in window_orders
        if first_order[customer] >= window_start
    )
    return {"new": new, "returning": len(window_orders) - new}


# ---------------------------------------------------- fulfillment (§5.7) ----

@dataclass(frozen=True, slots=True)
class CarrierPerformance:
    carrier: str
    total: int
    delivered: int
    rejected: int
    in_flight: int
    avg_days_to_deliver: float | None


def fulfillment_by_carrier(
    shipments: list[dict], *, minimum_volume: int = 10
) -> list[CarrierPerformance]:
    """Delivery/rejection rates per carrier from REAL shipment statuses.

    §5.7: uses only what exists (status, shipped_at, delivered_at). No
    attempt history, no COD settlement. Carriers below the minimum volume
    are omitted from rate claims (small-n rates lie).
    """
    by_carrier: dict[str, list[dict]] = {}
    for shipment in shipments:
        carrier = shipment.get("carrier") or "unknown"
        by_carrier.setdefault(carrier, []).append(shipment)
    out: list[CarrierPerformance] = []
    for carrier, rows in sorted(by_carrier.items()):
        if len(rows) < minimum_volume:
            continue
        delivered = [r for r in rows if r.get("status") == "delivered"]
        rejected = [r for r in rows if r.get("status") == "failed"]
        in_flight = [r for r in rows if r.get("status") in ("picked_up", "in_transit")]
        durations = []
        for row in delivered:
            shipped, delivered_at = row.get("shipped_at"), row.get("delivered_at")
            if shipped and delivered_at:
                durations.append((delivered_at - shipped).total_seconds() / 86400)
        out.append(
            CarrierPerformance(
                carrier=carrier,
                total=len(rows),
                delivered=len(delivered),
                rejected=len(rejected),
                in_flight=len(in_flight),
                avg_days_to_deliver=round(_median(durations), 2) if durations else None,
            )
        )
    return out

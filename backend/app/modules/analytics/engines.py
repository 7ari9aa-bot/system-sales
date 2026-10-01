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
from datetime import date
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

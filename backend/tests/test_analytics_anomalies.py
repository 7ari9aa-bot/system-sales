"""Anomaly engine tests (spec §5.2) — planted truth on synthetic series.

A flat weekday-seasonal series with ONE planted spike: the engine must find
exactly the planted day (dedupe), skip sub-threshold noise, respect the
minimum volume, flag short history, and say drop vs spike with the right
sign.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.modules.analytics.engines import detect_anomalies

START = date(2026, 8, 1)


def _series(days: int, daily: str) -> dict[date, Decimal]:
    return {START + timedelta(days=i): Decimal(daily) for i in range(days)}


def test_planted_spike_found_exactly_once():
    series = _series(30, "500.00")
    spike_day = START + timedelta(days=10)
    series[spike_day] = Decimal("2000.00")  # 4x the flat line

    anomalies = detect_anomalies(series)
    assert len(anomalies) == 1
    found = anomalies[0]
    assert found.day == spike_day
    assert found.direction == "spike"
    assert found.observed == Decimal("2000.00")
    assert found.insufficient_history is True  # 30 days < the 8-week STL bar


def test_planted_drop_found_with_drop_direction():
    series = _series(30, "500.00")
    drop_day = START + timedelta(days=15)
    series[drop_day] = Decimal("150.00")
    anomalies = detect_anomalies(series)
    assert len(anomalies) == 1
    assert anomalies[0].direction == "drop"
    assert anomalies[0].day == drop_day


def test_quiet_series_reports_nothing():
    # Weekend lift is the ONLY variation — the same-weekday baseline eats it.
    series = {}
    for i in range(30):
        day = START + timedelta(days=i)
        series[day] = Decimal("600.00") if day.weekday() >= 5 else Decimal("500.00")
    assert detect_anomalies(series) == []


def test_minimum_volume_gates_small_stores():
    series = _series(30, "500.00")
    series[START + timedelta(days=8)] = Decimal("80.00")  # big % but tiny money
    anomalies = detect_anomalies(series, minimum_volume=Decimal("100"))
    assert anomalies == []


def test_short_history_returns_nothing():
    assert detect_anomalies(_series(10, "500.00")) == []


def test_contiguous_run_dedupes_to_the_strongest_day():
    series = _series(30, "500.00")
    for offset, value in ((10, "3000.00"), (11, "2500.00"), (12, "1200.00")):
        series[START + timedelta(days=offset)] = Decimal(value)
    anomalies = detect_anomalies(series)
    assert [a.day for a in anomalies] == [START + timedelta(days=10)]

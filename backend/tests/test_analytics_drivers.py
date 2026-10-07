"""Driver tests (spec §5.1) — the midpoint decomposition is EXACT and the
Σ == Δ invariant holds with ZERO tolerance, in Decimal. Hand-computed
fixtures plus a parameter sweep; a float here would break the invariant by
construction.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.analytics.drivers import dimension_revenue_deltas, orders_vs_aov

D = Decimal


@pytest.mark.parametrize(
    ("n0", "aov0", "n1", "aov1"),
    [
        (D(100), D("50.00"), D(90), D("55.00")),  # classic: orders down, AOV up
        (D(1), D("200.00"), D(2), D("100.00")),  # 1→2 orders, AOV halves: ΔR = 0
        (D(0), D("0.00"), D(10), D("35.50")),  # new store from zero
        (D(10), D("35.55"), D(0), D("0.00")),  # store died
        (D("7"), D("33.33"), D("13"), D("44.44")),  # repeating decimals stay exact
    ],
)
def test_contributions_sum_exactly_to_the_delta(n0, aov0, n1, aov1):
    orders_part, aov_part, total = orders_vs_aov(
        orders_before=n0, aov_before=aov0, orders_after=n1, aov_after=aov1
    )
    assert orders_part + aov_part == total
    assert total == n1 * aov1 - n0 * aov0


def test_hand_computed_classic_case():
    # 100 orders @ 50 → 90 orders @ 55. ΔR = 4950 − 5000 = −50.
    # ΔN·avg(AOV) = −10 · 52.5 = −525 ; ΔAOV·avg(N) = 5 · 95 = +475.
    orders_part, aov_part, total = orders_vs_aov(
        orders_before=D(100),
        aov_before=D("50.00"),
        orders_after=D(90),
        aov_after=D("55.00"),
    )
    assert orders_part == D("-525.00")
    assert aov_part == D("475.00")
    assert total == D("-50.00")
    assert orders_part + aov_part == total


def test_decomposition_sums_exactly_with_new_and_discontinued():
    before = {"t-shirt": D("100.00"), "abaya": D("250.00"), "scarf": D("40.00")}
    after = {"t-shirt": D("80.00"), "abaya": D("310.00"), "hoodie": D("60.00")}
    breakdown = dimension_revenue_deltas("product", before, after)

    by_key = {e.key: e for e in breakdown.entries}
    assert by_key["t-shirt"].delta == D("-20.00") and by_key["t-shirt"].bucket == "existing"
    assert by_key["abaya"].delta == D("60.00") and by_key["abaya"].bucket == "existing"
    assert by_key["hoodie"].delta == D("60.00") and by_key["hoodie"].bucket == "new"
    assert by_key["scarf"].delta == D("-40.00") and by_key["scarf"].bucket == "discontinued"

    total = sum(e.delta for e in breakdown.entries)
    assert total == (D("80") + D("310") + D("60")) - (D("100") + D("250") + D("40"))

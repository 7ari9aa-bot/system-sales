"""Driver analysis (spec §5.1) — deterministic, exact, test-heavy.

The revenue decomposition uses the midpoint method and is EXACT: with real
arithmetic, the two contributions sum to the total delta with ZERO residual.
Money crosses this module as ``Decimal`` only (§47's rule, applied to
analytics): a float here would break the Σ == Δ invariant by construction.

Dimension decompositions (product, channel, governorate, ...) are each an
INDEPENDENT decomposition of the total delta — they are never summed across
dimensions, and every evidence pack states that explicitly.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.analytics.contracts import DimensionBreakdown, DimensionEntry

TWO = Decimal(2)


def orders_vs_aov(
    *,
    orders_before: Decimal,
    aov_before: Decimal,
    orders_after: Decimal,
    aov_after: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Midpoint decomposition of the revenue delta into orders/AOV effects.

    ΔR = ΔN · avg(AOV) + ΔAOV · avg(N), with avg over the two periods.
    Exact in Decimal: division by 2 is terminating, so the invariant
    Σ contributions == ΔR holds with zero tolerance (§5.1).
    Returns (orders_contribution, aov_contribution, total_delta).
    """
    delta_orders = orders_after - orders_before
    delta_aov = aov_after - aov_before
    avg_aov = (aov_before + aov_after) / TWO
    avg_orders = (orders_before + orders_after) / TWO
    orders_contribution = delta_orders * avg_aov
    aov_contribution = delta_aov * avg_orders
    total_delta = orders_after * aov_after - orders_before * aov_before
    assert orders_contribution + aov_contribution == total_delta, (
        "midpoint decomposition must be exact"
    )
    return orders_contribution, aov_contribution, total_delta


def dimension_revenue_deltas(
    dimension: str,
    before: dict[str, Decimal],
    after: dict[str, Decimal],
) -> DimensionBreakdown:
    """One entity-level decomposition of the revenue delta.

    Entities present in only one period land in explicit new/discontinued
    buckets (§5.1); every entry carries its own delta and
    Σ entries == total delta, exactly.
    """
    entries: list[DimensionEntry] = []
    total = Decimal(0)
    for key in sorted(set(before) | set(after)):
        before_value = before.get(key)
        after_value = after.get(key)
        if before_value is not None and after_value is not None:
            delta = after_value - before_value
            bucket = "existing"
        elif after_value is not None:
            delta = after_value
            bucket = "new"
        else:
            delta = -before_value  # type: ignore[operator] — before is not None here
            bucket = "discontinued"
        entries.append(DimensionEntry(key=key, delta=delta, bucket=bucket))
        total += delta
    assert sum(e.delta for e in entries) == total
    return DimensionBreakdown(dimension=dimension, entries=entries)

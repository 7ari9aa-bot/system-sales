"""Semantic layer (spec §6) — the metric registry, on the REAL schema.

Every definition below is derived from the actual orders-domain columns
(app/modules/orders/models.py) — attribution events and timestamps are the
tables' real ones, not the spec's guesses. §6.2's VERIFY items are thereby
resolved:

* ``order_status_history`` EXISTS (order_id, from_status, to_status,
  created_at) — the recorded time of a transition is its only time column,
  so the event view uses it with that caveat; same-age resolution curves
  can be built from it going forward.
* ``orders.placed_at`` is NULLABLE — the attribution timestamp for
  placed-based metrics is COALESCE(placed_at, created_at), declared here
  once, in the definition.
* delivered/shipped live on ``shipments`` (delivered_at, shipped_at,
  carrier); collected lives on ``payments`` (paid_at); refunds carry
  ``processed_at``.

The registry compiles to queries (compiler.py) — it is a product decision,
not a data dictionary.
"""

from __future__ import annotations

from app.modules.analytics.contracts import (
    Assumption,
    FreshnessPolicy,
    MaturityPolicy,
    MetricDefinition,
)

_PLACED_TS = "COALESCE(placed_at, created_at)"

METRIC_REGISTRY_VERSION = "1"

_registry: dict[str, MetricDefinition] = {}


def _register(definition: MetricDefinition) -> None:
    _registry[definition.name] = definition


def metric(name: str) -> MetricDefinition:
    """The definition, or KeyError naming the unknown metric — an unknown
    metric must fail the REQUEST loudly, never degrade silently."""
    if name not in _registry:
        raise KeyError(f"unknown metric: {name} (registry v{METRIC_REGISTRY_VERSION})")
    return _registry[name]


def all_metrics() -> dict[str, MetricDefinition]:
    return dict(_registry)


# The store's sellable-to-ship vocabulary, mirrored from the checkout gate's
# real order status vocabulary (orders/service.py). Placed-based metrics
# count every non-deleted order — an order that was later cancelled was
# still PLACED; its cancellation shows in the delivered/collected metrics.
_PLACED_LIFECYCLE = ["all_non_deleted"]

_register(
    MetricDefinition(
        name="orders_placed",
        description="Orders placed in the period (any later status; soft-deletes excluded).",
        semantic_type="count",
        value_definition="count of non-deleted orders",
        attribution_event="order created",
        attribution_timestamp=_PLACED_TS,
        lifecycle_filter=_PLACED_LIFECYCLE,
        maturity_policy=MaturityPolicy(kind="immediate"),
        dimensions_allowed=["channel", "product", "governorate"],
        source="orders",
        version=METRIC_REGISTRY_VERSION,
    )
)
_register(
    MetricDefinition(
        name="delivered_revenue",
        description="Grand total of orders with a DELIVERED shipment in the period.",
        semantic_type="money",
        value_definition="sum of orders.grand_total",
        attribution_event="shipment delivered",
        attribution_timestamp="shipments.delivered_at",
        lifecycle_filter=["shipment_status=delivered"],
        maturity_policy=MaturityPolicy(kind="carrier_curve", settle_days=7),
        dimensions_allowed=["product", "channel", "governorate", "carrier"],
        source="orders+shipments",
        version=METRIC_REGISTRY_VERSION,
    )
)
_register(
    MetricDefinition(
        name="shipped_orders",
        description="Orders with a SHIPPED shipment in the period.",
        semantic_type="count",
        value_definition="count of shipments with shipped_at",
        attribution_event="shipment shipped",
        attribution_timestamp="shipments.shipped_at",
        lifecycle_filter=["shipment_status in (picked_up,in_transit,delivered)"],
        maturity_policy=MaturityPolicy(kind="fast", settle_days=2),
        dimensions_allowed=["carrier"],
        source="shipments",
        version=METRIC_REGISTRY_VERSION,
    )
)
_register(
    MetricDefinition(
        name="collected_revenue",
        description="Payments captured in the period (paid_at set).",
        semantic_type="money",
        value_definition="sum of payments.amount with a paid_at",
        attribution_event="payment captured",
        attribution_timestamp="payments.paid_at",
        lifecycle_filter=["payment captured"],
        maturity_policy=MaturityPolicy(kind="long_tail", settle_days=14),
        dimensions_allowed=["method"],
        source="payments",
        version=METRIC_REGISTRY_VERSION,
    )
)
_register(
    MetricDefinition(
        name="refund_amount",
        description="Processed refunds in the period.",
        semantic_type="money",
        value_definition="sum of refunds.amount with processed_at",
        attribution_event="refund processed",
        attribution_timestamp="refunds.processed_at",
        lifecycle_filter=["refund processed"],
        maturity_policy=MaturityPolicy(kind="long_tail", settle_days=30),
        dimensions_allowed=["reason"],
        source="refunds",
        version=METRIC_REGISTRY_VERSION,
    )
)
_register(
    MetricDefinition(
        name="net_revenue",
        description="delivered_revenue minus processed refunds (composite).",
        semantic_type="money",
        value_definition="delivered_revenue - refund_amount",
        attribution_event="delivered minus processed refund",
        attribution_timestamp="shipments.delivered_at",
        lifecycle_filter=["composite"],
        maturity_policy=MaturityPolicy(kind="composite", settle_days=30),
        dimensions_allowed=[],
        source="composite",
        version=METRIC_REGISTRY_VERSION,
    )
)
_register(
    MetricDefinition(
        name="aov",
        description="Average order value: orders revenue over orders count.",
        semantic_type="money",
        value_definition="revenue / non-zero order count",
        attribution_event="follows its revenue component",
        attribution_timestamp="follows its revenue component",
        lifecycle_filter=["composite"],
        maturity_policy=MaturityPolicy(kind="composite", settle_days=7),
        dimensions_allowed=["channel"],
        source="composite",
        version=METRIC_REGISTRY_VERSION,
    )
)

#: §6.3 — StoreMetricProfile. The store's "how do you measure sales" choice.
#: Until onboarding captures it, D15's fallback applies and every answer
#: surfaces it as an assumption: non-cancelled ordered revenue by placed_at
#: (earliest available, least exposed to maturity lag).
DEFAULT_PRIMARY_SALES_METRIC = "orders_placed"


class StoreMetricProfile:
    """Per-store measurement choice (v1: in-memory; onboarding persists it
    to a store_metric_profiles table when it lands)."""

    def __init__(
        self,
        *,
        primary_sales_metric: str = DEFAULT_PRIMARY_SALES_METRIC,
        version: str = "1",
    ):
        if primary_sales_metric not in _registry:
            raise KeyError(f"unknown metric: {primary_sales_metric}")
        self.primary_sales_metric = primary_sales_metric
        self.version = version

    def as_assumption(self) -> Assumption:
        return Assumption(
            key="primary_sales_metric",
            statement=(
                f"المقياس الأساسي للمبيعات افتراضي ({self.primary_sales_metric}) "
                "لأن المتجر لم يختار بعد — اختره من الإعدادات."
            ),
        )


def freshness_policies() -> dict[str, FreshnessPolicy]:
    return {name: d.freshness_policy for name, d in _registry.items()}


async def load_store_metric_profile(session: object, tenant_id: object) -> StoreMetricProfile:
    """Load store metric profile from persistent settings if configured,
    otherwise falling back to default StoreMetricProfile."""
    from sqlalchemy import text

    try:
        row = (
            await session.execute(
                text(
                    "SELECT value FROM platform_settings"
                    " WHERE tenant_id = :tid"
                    " AND key = 'primary_sales_metric'"
                ),
                {"tid": str(tenant_id)},
            )
        ).scalar_one_or_none()
        if row and row in _registry:
            return StoreMetricProfile(primary_sales_metric=row)
    except Exception:
        pass
    return StoreMetricProfile()

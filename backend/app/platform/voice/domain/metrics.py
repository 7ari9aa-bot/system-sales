"""The metric registry: every number the voice assistant may say, and what it means.

A shop owner asking "how much did we make?" is asking a question with a definition behind it.
Net sales is not gross sales minus whatever the model remembers; it is a named formula with a
version, the scopes it needs and the inputs it consumes. The agent may only speak a metric that is
in this registry, and the answer carries the version that produced it (invariant 13).

`needs` is what makes an honest "I cannot tell you" possible: a metric whose inputs are missing is
reported as unavailable with the missing input named, never computed from the parts that happened
to be there.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.platform.voice.domain.contracts import Evidence


class MetricUnit(enum.StrEnum):
    MONEY = "money"
    COUNT = "count"
    RATIO = "ratio"
    DAYS = "days"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One metric, versioned. Changing the formula means changing the version, not the meaning."""

    code: str
    label: str
    label_ar: str
    unit: MetricUnit
    scope: str
    formula: str
    needs: tuple[str, ...]
    version: str = "1.0"

    def evidence(self) -> Evidence:
        return Evidence(
            source="metric_registry",
            metric_definition_version=f"{self.code}@{self.version}",
            detail=self.formula,
        )


class UnknownMetric(LookupError):
    """Raised when a caller names a metric the registry does not define."""


_DEFINITIONS = (
    MetricDefinition(
        code="gross_sales",
        label="Gross sales",
        label_ar="إجمالي المبيعات",
        unit=MetricUnit.MONEY,
        scope="analytics:read",
        formula="sum(order.total) for orders not cancelled, before discounts and returns",
        needs=("orders",),
    ),
    MetricDefinition(
        code="net_sales",
        label="Net sales",
        label_ar="صافي المبيعات",
        unit=MetricUnit.MONEY,
        scope="analytics:read",
        formula="gross_sales - discounts - returns",
        needs=("orders", "returns"),
    ),
    MetricDefinition(
        code="gross_profit",
        label="Gross profit",
        label_ar="الربح الإجمالي",
        unit=MetricUnit.MONEY,
        scope="analytics:read",
        formula="net_sales - cost_of_goods_sold",
        needs=("orders", "returns", "cogs"),
    ),
    MetricDefinition(
        code="net_profit",
        label="Net profit",
        label_ar="صافي الربح",
        unit=MetricUnit.MONEY,
        scope="expenses:read",
        formula="gross_profit - operating_expenses",
        needs=("orders", "returns", "cogs", "expenses"),
    ),
    MetricDefinition(
        code="order_count",
        label="Orders",
        label_ar="عدد الطلبات",
        unit=MetricUnit.COUNT,
        scope="orders:read",
        formula="count(orders) in the period, excluding cancelled",
        needs=("orders",),
    ),
    MetricDefinition(
        code="aov",
        label="Average order value",
        label_ar="متوسط قيمة الطلب",
        unit=MetricUnit.MONEY,
        scope="analytics:read",
        formula="net_sales / order_count",
        needs=("orders", "returns"),
    ),
    MetricDefinition(
        code="refund_rate",
        label="Refund rate",
        label_ar="نسبة المرتجعات",
        unit=MetricUnit.RATIO,
        scope="analytics:read",
        formula="refunded_orders / order_count",
        needs=("orders", "returns"),
    ),
    MetricDefinition(
        code="inventory_turnover",
        label="Inventory turnover",
        label_ar="معدل دوران المخزون",
        unit=MetricUnit.RATIO,
        scope="inventory:read",
        formula="cogs / average_inventory_value",
        needs=("cogs", "inventory"),
    ),
    MetricDefinition(
        code="stock_cover_days",
        label="Days of stock left",
        label_ar="أيام تغطية المخزون",
        unit=MetricUnit.DAYS,
        scope="inventory:read",
        formula="on_hand_quantity / average_daily_units_sold",
        needs=("inventory", "orders"),
    ),
    MetricDefinition(
        code="marketing_roi",
        label="Marketing return",
        label_ar="عائد التسويق",
        unit=MetricUnit.RATIO,
        scope="analytics:read",
        formula="attributed_gross_profit / campaign_spend",
        needs=("campaigns", "orders"),
    ),
    MetricDefinition(
        code="customer_retention",
        label="Repeat customers",
        label_ar="العملاء المتكررون",
        unit=MetricUnit.RATIO,
        scope="customers:read",
        formula="customers_with_2plus_orders / customers_with_1plus_orders",
        needs=("orders", "customers"),
    ),
)

METRIC_REGISTRY: Mapping[str, MetricDefinition] = MappingProxyType(
    {definition.code: definition for definition in _DEFINITIONS}
)


def metric(code: str) -> MetricDefinition:
    """The definition, or a refusal: an undefined metric is never approximated."""
    try:
        return METRIC_REGISTRY[code]
    except KeyError:
        raise UnknownMetric(f"no metric named {code!r} is defined") from None

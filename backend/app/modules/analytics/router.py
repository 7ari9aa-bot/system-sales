"""Spec §55-57 — analytics routes: metric queries, definitions, retention.

Re-export aggregator for the decomposed analytics routers package.
"""

from __future__ import annotations

from app.core.audit import write_audit_row
from app.core.tenancy import resolve_tenant_currency
from app.modules.analytics import service as analytics_service
from app.modules.analytics.routers import router
from app.modules.analytics.routers._deps import (
    _METRIC_BASIS,
    _MONEY_FIELDS,
    _MONEY_METRICS,
    _SINCE_DOC,
    _UNTIL_DOC,
    _WINDOW_POLICY,
    MAX_LOW_STOCK_THRESHOLD,
    MAX_WINDOW_DAYS,
    AnalyticsReadCtx,
    AnalyticsWriteCtx,
    MetricRegistry,
    SettingsCtx,
    TenantContext,
    TenantCtxDep,
    _as_json,
    _bind_edge,
    _bind_window,
    _money_json,
    _window,
    _window_failure,
    _zone_source,
    require_permission,
)
from app.modules.analytics.routers.metrics import (
    compute_metric,
    list_metric_definitions,
)
from app.modules.analytics.routers.overview import (
    analytics_overview,
    daily_series,
    revenue_summary,
    stock_health,
)
from app.modules.analytics.routers.retention import (
    RetentionPolicyChoice,
    _gate_block,
    _gate_json,
    _unblock_requires,
    choose_retention_policy,
    retention_position,
)

# Preserve module qualification for introspection and test sweeps
for _endpoint in (
    list_metric_definitions,
    compute_metric,
    revenue_summary,
    daily_series,
    stock_health,
    analytics_overview,
    retention_position,
    choose_retention_policy,
):
    _endpoint.__module__ = "app.modules.analytics.router"

__all__ = [
    "AnalyticsReadCtx",
    "AnalyticsWriteCtx",
    "MAX_LOW_STOCK_THRESHOLD",
    "MAX_WINDOW_DAYS",
    "MetricRegistry",
    "RetentionPolicyChoice",
    "SettingsCtx",
    "TenantContext",
    "TenantCtxDep",
    "_METRIC_BASIS",
    "_MONEY_FIELDS",
    "_MONEY_METRICS",
    "_SINCE_DOC",
    "_UNTIL_DOC",
    "_WINDOW_POLICY",
    "_as_json",
    "_bind_edge",
    "_bind_window",
    "_gate_block",
    "_gate_json",
    "_money_json",
    "_unblock_requires",
    "_window",
    "_window_failure",
    "_zone_source",
    "analytics_overview",
    "analytics_service",
    "choose_retention_policy",
    "compute_metric",
    "daily_series",
    "list_metric_definitions",
    "require_permission",
    "resolve_tenant_currency",
    "retention_position",
    "revenue_summary",
    "router",
    "stock_health",
    "write_audit_row",
]

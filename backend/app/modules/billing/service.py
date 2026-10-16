"""BILLING service — plans, subscriptions, entitlements, usage metering.

Aggregator module maintaining backward compatibility for all billing services.
"""

from __future__ import annotations

from app.modules.billing.services import (
    _AI_TOKENS_FEATURE,
    _BILLING_CLOSE_LOCK_NAMESPACE,
    _CAPABILITY_FEATURE,
    _DERIVED_USAGE,
    _MONEY_QUANTUM,
    BillingService,
    BillingSnapshotService,
    EntitlementService,
    PeriodUsage,
    _as_decimal,
    _quantize_money,
    _tenant_lock_key,
    _validate_period,
)

BillingService.__module__ = "app.modules.billing.service"
EntitlementService.__module__ = "app.modules.billing.service"
BillingSnapshotService.__module__ = "app.modules.billing.service"

__all__ = [
    "BillingService",
    "EntitlementService",
    "BillingSnapshotService",
    "PeriodUsage",
    "_CAPABILITY_FEATURE",
    "_DERIVED_USAGE",
    "_AI_TOKENS_FEATURE",
    "_MONEY_QUANTUM",
    "_BILLING_CLOSE_LOCK_NAMESPACE",
    "_as_decimal",
    "_quantize_money",
    "_validate_period",
    "_tenant_lock_key",
]

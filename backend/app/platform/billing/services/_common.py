"""Common constants, helpers, and types for billing services."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from app.core.errors import ValidationError

# Capability (what a caller asks for) -> plan feature (what the plan stores).
_CAPABILITY_FEATURE: dict[str, str] = {
    "CanAddUser": "max_users",
    "CanUseAI": "ai_agents",
    "CanCreateChannel": "channels",
}

# Features whose "usage" is a live row count, not a period accumulator.
_DERIVED_USAGE: dict[str, str] = {
    "max_users": "tenant_users",
    "seats": "tenant_users",
}

# Canonical feature name for AI token usage.
_AI_TOKENS_FEATURE = "ai_tokens"

# Money is never a float (ADR-001). Numeric(14,2) columns are quantized with an explicit mode.
_MONEY_QUANTUM = Decimal("0.01")

_BILLING_CLOSE_LOCK_NAMESPACE = 531


def _as_decimal(value: object) -> Decimal:
    """Exact Decimal from a Numeric column — never `float()`."""
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize_money(value: Decimal) -> Decimal:
    """Exact 2dp rounding for a MONEY column."""
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _validate_period(period_start: date, period_end: date) -> None:
    """Reject an empty or inverted period BEFORE any database access."""
    if period_start >= period_end:
        raise ValidationError(
            "period_start must be before period_end",
            details={
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )


def _tenant_lock_key(tenant_id: uuid.UUID) -> int:
    """31 bits of tenant id, inside int4 range, for the 2-arg advisory lock."""
    return uuid.UUID(str(tenant_id)).int & 0x7FFFFFFF


class PeriodUsage(NamedTuple):
    """One tenant's metered usage over one period."""

    features: dict[str, Decimal]
    ai_cost: Decimal

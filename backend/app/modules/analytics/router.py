"""Spec §55-57 — analytics routes: metric queries and definitions.

Read-only: every endpoint returns a number or a list. No writes here.

This module provides the canonical metric computation endpoints (revenue,
orders_count, AOV, etc.) backed by the metric registry (§167). The marketing
module's analytics_router is for campaign-specific analytics (CAC, ROAS);
this module is for the platform-wide canonical numbers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.modules.analytics import service as analytics_service
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform.metrics import MetricRegistry

router = APIRouter(prefix="/analytics", tags=["analytics"])

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]


@router.get("/metrics/definitions")
async def list_metric_definitions(ctx: TenantCtxDep) -> dict:
    """§167: list every canonical metric definition."""
    return {"items": MetricRegistry.definitions()}


@router.get("/metrics/{metric_name}")
async def compute_metric(
    metric_name: str,
    ctx: TenantCtxDep,
    since: datetime = Query(..., description="ISO 8601 start (inclusive)"),
    until: datetime = Query(
        default_factory=lambda: datetime.now(UTC),
        description="ISO 8601 end (exclusive)",
    ),
) -> dict:
    """Compute a single canonical metric for the tenant's window."""
    value = await analytics_service.compute_metric(
        ctx.session,
        ctx.tenant_id,
        metric_name=metric_name,
        since=since,
        until=until,
    )
    return {
        "metric": metric_name,
        "value": str(value) if isinstance(value, (Decimal, float)) else value,
        "since": since.isoformat(),
        "until": until.isoformat(),
    }


@router.get("/dashboard")
async def dashboard(
    ctx: TenantCtxDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict:
    """The headline numbers a dashboard needs in one round-trip."""
    until = datetime.now(UTC)
    since = until - timedelta(days=days)

    metrics = {}
    for name in ("revenue", "orders_count", "net_revenue", "aov", "refunded_amount"):
        try:
            value = await analytics_service.compute_metric(
                ctx.session,
                ctx.tenant_id,
                metric_name=name,
                since=since,
                until=until,
            )
            metrics[name] = str(value) if isinstance(value, (Decimal, float)) else value
        except Exception:
            metrics[name] = None

    for name in ("first_response_time", "resolution_time", "ai_resolution_rate"):
        try:
            value = await analytics_service.compute_metric(
                ctx.session,
                ctx.tenant_id,
                metric_name=name,
                since=since,
                until=until,
            )
            metrics[name] = value
        except Exception:
            metrics[name] = None

    return {
        "days": days,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "metrics": metrics,
    }


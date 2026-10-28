"""Metric definition and computation routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import Query

from app.modules.analytics import schemas
from app.modules.analytics import service as analytics_service


async def _resolve_tenant_currency(session, tenant_id):
    from app.modules.analytics import router as analytics_router

    return await analytics_router.resolve_tenant_currency(session, tenant_id)


from ._deps import (  # noqa: E402
    _METRIC_BASIS,
    _MONEY_METRICS,
    _SINCE_DOC,
    _UNTIL_DOC,
    MetricRegistry,
    TenantCtxDep,
    _as_json,
    _bind_window,
    router,
)


@router.get("/metrics/definitions", response_model=schemas.MetricDefinitionListOut)
async def list_metric_definitions(ctx: TenantCtxDep) -> dict[str, Any]:
    """§167: list every canonical metric definition."""
    return {"items": MetricRegistry.definitions(), "next_cursor": None}


@router.get(
    "/metrics/{metric_name}",
    response_model=schemas.MetricValueOut,
    response_model_exclude_unset=True,
)
async def compute_metric(
    metric_name: str,
    ctx: TenantCtxDep,
    since: Annotated[datetime, Query(description=_SINCE_DOC)],
    until: Annotated[datetime | None, Query(description=_UNTIL_DOC)] = None,
) -> dict[str, Any]:
    """Compute a single canonical metric for the tenant's window."""
    since, until = _bind_window(since, until)
    spec = MetricRegistry.get(metric_name)
    value = await analytics_service.compute_metric(
        ctx.session,
        ctx.tenant_id,
        metric_name=metric_name,
        since=since,
        until=until,
    )
    payload: dict = {
        "metric": metric_name,
        "value": _as_json(value),
        "since": since.isoformat(),
        "until": until.isoformat(),
    }
    if spec is not None:
        payload["refund_treatment"] = spec.refund_treatment
        payload["timezone_rule"] = spec.timezone_rule
    if metric_name in _METRIC_BASIS:
        payload["basis"] = _METRIC_BASIS[metric_name]
    if metric_name in _MONEY_METRICS:
        payload["currency"] = await _resolve_tenant_currency(ctx.session, ctx.tenant_id)
    return payload

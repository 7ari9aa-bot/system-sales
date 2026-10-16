"""SLA and SLO endpoints for operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Query
from sqlalchemy import select

from app.core.errors import ValidationError
from app.modules.operations.schemas import (
    AlertDestination,
    BusinessCalendarList,
    BusinessCalendarOut,
    BusinessCalendarUpsert,
    SLAPolicyList,
    SLAPolicyOut,
    SLAPolicyUpsert,
    SLARiskItem,
    SLARiskList,
    SLODefinitionList,
    SLODefinitionOut,
    SLOMeasurement,
    SLOMeasurementList,
)
from ._deps import (
    SettingsCtx,
    TenantCtxDep,
    _calendar_out,
    _policy_out,
    _slo_out,
    sla_router,
)


@sla_router.get("/policies", response_model=SLAPolicyList)
async def list_sla_policies(ctx: TenantCtxDep):
    from app.modules.operations.models import SLAPolicy

    rows = (
        (await ctx.session.execute(select(SLAPolicy).where(SLAPolicy.tenant_id == ctx.tenant_id)))
        .scalars()
        .all()
    )
    return SLAPolicyList(items=[_policy_out(p) for p in rows])


@sla_router.put("/policies", status_code=201, response_model=SLAPolicyOut)
async def upsert_sla_policy(
    body: SLAPolicyUpsert,
    ctx: SettingsCtx,
):
    """Create or replace the tenant's SLA policy of the same name."""
    from app.modules.operations.models import SLAPolicy

    if body.is_default:
        for row in (
            (
                await ctx.session.execute(
                    select(SLAPolicy).where(
                        SLAPolicy.tenant_id == ctx.tenant_id, SLAPolicy.is_default.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        ):
            row.is_default = False
        await ctx.session.flush()

    existing = (
        await ctx.session.execute(
            select(SLAPolicy).where(
                SLAPolicy.tenant_id == ctx.tenant_id, SLAPolicy.name == body.name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.first_response_minutes = body.first_response_minutes
        existing.resolution_minutes = body.resolution_minutes
        existing.applies_to_channel = body.applies_to_channel
        existing.is_default = body.is_default
        await ctx.session.flush()
        return _policy_out(existing)

    policy = SLAPolicy(
        tenant_id=ctx.tenant_id,
        name=body.name,
        first_response_minutes=body.first_response_minutes,
        resolution_minutes=body.resolution_minutes,
        applies_to_channel=body.applies_to_channel,
        is_default=body.is_default,
        status="active",
    )
    ctx.session.add(policy)
    await ctx.session.flush()
    return _policy_out(policy)


@sla_router.get("/calendars", response_model=BusinessCalendarList)
async def list_business_calendars(ctx: TenantCtxDep):
    from app.modules.operations.models import BusinessCalendar

    rows = (
        (
            await ctx.session.execute(
                select(BusinessCalendar).where(BusinessCalendar.tenant_id == ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    return BusinessCalendarList(items=[_calendar_out(c) for c in rows])


@sla_router.put("/calendars", status_code=201, response_model=BusinessCalendarOut)
async def upsert_business_calendar(
    body: BusinessCalendarUpsert,
    ctx: SettingsCtx,
):
    """Configure opening hours."""
    from app.modules.operations.models import BusinessCalendar
    from app.modules.operations.sla import validate_calendar

    validate_calendar(body.hours, body.holidays)
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"unknown timezone: {body.timezone}") from exc

    if body.is_default:
        for row in (
            (
                await ctx.session.execute(
                    select(BusinessCalendar).where(
                        BusinessCalendar.tenant_id == ctx.tenant_id,
                        BusinessCalendar.is_default.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        ):
            row.is_default = False
        await ctx.session.flush()

    existing = (
        await ctx.session.execute(
            select(BusinessCalendar).where(
                BusinessCalendar.tenant_id == ctx.tenant_id,
                BusinessCalendar.name == body.name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.timezone = body.timezone
        existing.hours = body.hours
        existing.holidays = body.holidays
        existing.is_default = body.is_default
        await ctx.session.flush()
        return _calendar_out(existing)

    calendar = BusinessCalendar(
        tenant_id=ctx.tenant_id,
        name=body.name,
        timezone=body.timezone,
        hours=body.hours,
        holidays=body.holidays,
        is_default=body.is_default,
    )
    ctx.session.add(calendar)
    await ctx.session.flush()
    return _calendar_out(calendar)


@sla_router.get("/risk", response_model=SLARiskList)
async def sla_risk(ctx: TenantCtxDep, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    """Conversations whose first-response SLA is running, breached or at risk."""
    from app.modules.operations.models import SLAEvent
    from app.modules.operations.sla import SlaService

    clock = await SlaService.resolve_clock(ctx.session, ctx.tenant_id)
    rows = (
        (
            await ctx.session.execute(
                select(SLAEvent)
                .where(
                    SLAEvent.tenant_id == ctx.tenant_id,
                    SLAEvent.status.in_(("running", "breached")),
                )
                .order_by(SLAEvent.deadline_at.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    now = datetime.now(UTC)
    items = []
    for row in rows:
        remaining = None
        if row.deadline_at is not None:
            remaining = int((row.deadline_at - now).total_seconds() // 60)
        items.append(
            SLARiskItem(
                id=row.id,
                conversation_id=row.conversation_id,
                kind=row.kind,
                status=row.status,
                deadline_at=row.deadline_at,
                minutes_remaining=remaining,
                at_risk=bool(row.status == "running" and remaining is not None and remaining <= 15),
            )
        )
    return SLARiskList(items=items, timezone=clock.timezone_name)


@sla_router.get("/slos", response_model=SLODefinitionList)
async def list_slo_definitions(ctx: TenantCtxDep):
    """§168: list all SLO definitions (deployment-wide, not per-tenant)."""
    from app.modules.operations.slo_service import get_slo_definitions

    return SLODefinitionList(
        items=[
            SLODefinitionOut(
                name=row["name"],
                description=row["description"],
                target_percent=row["target_percent"],
                window_hours=row["window_hours"],
                warning_percent=row["warning_percent"],
                error_percent=row["error_percent"],
                runbook=row["runbook"],
                alert_destinations=[
                    AlertDestination(channel=d["channel"], target=d["target"])
                    for d in row["alert_destinations"]
                ],
            )
            for row in get_slo_definitions()
        ]
    )


@sla_router.get("/slos/measure", response_model=SLOMeasurementList)
async def measure_all_slos(ctx: TenantCtxDep):
    """§168: compute every SLO's compliance for the tenant."""
    from app.modules.operations.slo_service import measure_all_slos

    return SLOMeasurementList(
        items=[_slo_out(r) for r in await measure_all_slos(ctx.session, ctx.tenant_id)]
    )


@sla_router.get("/slos/{slo_name}", response_model=SLOMeasurement)
async def measure_one_slo(ctx: TenantCtxDep, slo_name: str) -> SLOMeasurement:
    """§168: compute one SLO's compliance for the tenant."""
    from app.modules.operations.slo_service import measure_slo

    return _slo_out(await measure_slo(ctx.session, ctx.tenant_id, slo_name))

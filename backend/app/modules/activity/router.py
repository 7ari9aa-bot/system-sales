"""ACTIVITY routes: the read-only operations timeline.

Needs `orders:read` (the same bar as the screens it summarises). It only ever reads.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.modules.activity.service import KINDS, ActivityService, Cursor
from app.modules.identity.deps import TenantContext, require_permission

router = APIRouter(prefix="/activity", tags=["activity"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("orders:read"))]


class ActivityOut(BaseModel):
    occurred_at: str
    kind: str
    ref_id: str
    # Unique per event (a shift's open and close share a ref_id); the screen's row key.
    event_key: str
    doc: str
    # Decimal as a string: a JSON float would lose cents. Inventory rows carry a unit count.
    amount: str
    actor_id: str | None
    actor_name: str | None
    detail: str | None


class FeedOut(BaseModel):
    items: list[ActivityOut]
    next_cursor: str | None


class SummaryOut(BaseModel):
    counts: dict[str, int]


async def window_for(
    session, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None
) -> tuple[datetime | None, datetime | None]:
    """The ``[since, until)`` instants for a date filter, in the MERCHANT's day.

    "Today" must not flip at 02:00 local because UTC rolled over, and a Dubai shop's 10 January is
    not a Cairo shop's. The zone is the tenant's own (``tenants.timezone``), resolved through the
    same chain analytics uses.
    """
    from app.modules.analytics.timekit import merchant_day_window, resolve_timezone
    from app.modules.identity.models import Tenant

    if date_from and date_to and date_to < date_from:
        raise HTTPException(422, "date_to is before date_from")
    own = (
        await session.execute(select(Tenant.timezone).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    # A plain str, not the ResolvedTimezone: merchant_day_window re-resolves its argument, and a
    # ResolvedTimezone whose source is not "param" is read as "the caller deferred", which would
    # silently drop the tenant's zone and fall through to UTC.
    zone = str(resolve_timezone(tenant_timezone=own))
    since = merchant_day_window(date_from, zone)[0] if date_from else None
    until = merchant_day_window(date_to, zone)[1] if date_to else None
    return since, until


def _kinds(raw: str | None) -> tuple[str, ...] | None:
    if not raw:
        return None
    picked = tuple(k for k in dict.fromkeys(x.strip() for x in raw.split(",")) if k)
    bad = [k for k in picked if k not in KINDS]
    if bad:
        raise HTTPException(422, f"unknown kind: {', '.join(bad)}")
    return picked


def _out(r: dict) -> ActivityOut:
    return ActivityOut(
        occurred_at=r["occurred_at"].isoformat(),
        kind=r["kind"],
        ref_id=r["ref_id"],
        event_key=r["ekey"],
        doc=r["doc"] or "",
        amount=f"{r['amount']:.2f}" if r["kind"] != "inventory" else str(int(r["amount"])),
        actor_id=r["actor_id"],
        actor_name=r["actor_name"],
        detail=r["detail"] or None,
    )


@router.get("", response_model=FeedOut)
async def feed(
    ctx: ReadCtx,
    kinds: Annotated[str | None, Query(description="comma separated; default all")] = None,
    actor_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    start, end = await window_for(ctx.session, ctx.tenant_id, date_from, date_to)
    try:
        cur = Cursor.decode(cursor) if cursor else None
    except ValueError:
        raise HTTPException(422, "bad cursor") from None
    rows, nxt = await ActivityService.feed(
        ctx.session,
        ctx.tenant_id,
        kinds=_kinds(kinds),
        actor_id=actor_id,
        date_from=start,
        date_to=end,
        search=q,
        cursor=cur,
        limit=limit,
    )
    return FeedOut(items=[_out(r) for r in rows], next_cursor=nxt.encode() if nxt else None)


@router.get("/summary", response_model=SummaryOut)
async def summary(ctx: ReadCtx, date_from: date | None = None, date_to: date | None = None):
    start, end = await window_for(ctx.session, ctx.tenant_id, date_from, date_to)
    return SummaryOut(
        counts=await ActivityService.summary(
            ctx.session, ctx.tenant_id, date_from=start, date_to=end
        )
    )

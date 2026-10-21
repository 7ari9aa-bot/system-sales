"""ACTIVITY routes: the read-only operations timeline.

Needs `orders:read` (the same bar as the screens it summarises). It only ever reads.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.modules.activity.service import KINDS, ActivityService, Cursor
from app.modules.identity.deps import TenantContext, require_permission

router = APIRouter(prefix="/activity", tags=["activity"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("orders:read"))]

# The shop's day is the Cairo day: "today" must not flip at 02:00 local because UTC rolled over.
SHOP_TZ = ZoneInfo("Africa/Cairo")


class ActivityOut(BaseModel):
    occurred_at: str
    kind: str
    ref_id: str
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


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=SHOP_TZ)


def _window(
    date_from: date | None, date_to: date | None
) -> tuple[datetime | None, datetime | None]:
    if date_from and date_to and date_to < date_from:
        raise HTTPException(422, "date_to is before date_from")
    return (
        _day_start(date_from) if date_from else None,
        _day_start(date_to + timedelta(days=1)) if date_to else None,
    )


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
        doc=r["doc"] or "",
        amount=f"{r['amount']:.2f}" if r["kind"] != "inventory" else str(int(r["amount"])),
        actor_id=r["actor_id"],
        actor_name=r["actor_name"],
        detail=r["detail"] or None,
    )


@router.get("", response_model=FeedOut)
async def feed(
    ctx: ReadCtx,
    kinds: str | None = Query(None, description="comma separated; default all"),
    actor_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(None, max_length=80),
    cursor: str | None = Query(None, max_length=400),
    limit: int = Query(50, ge=1, le=200),
):
    start, end = _window(date_from, date_to)
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
    start, end = _window(date_from, date_to)
    return SummaryOut(
        counts=await ActivityService.summary(
            ctx.session, ctx.tenant_id, date_from=start, date_to=end
        )
    )

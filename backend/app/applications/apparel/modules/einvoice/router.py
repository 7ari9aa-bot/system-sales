"""Endpoints the Egyptian Tax Authority calls on us (no user session, no JWT).

The authority registers two URLs for a till and calls them with ``PUT``:

* ``/einvoice/eta/notifications/receipts``  a receipt became valid / received / cancelled
* ``/einvoice/eta/notifications/general``   something about the till itself

Both carry ``Authorization: ApiKey <shared key>``. The key is the only thing that says which
store the call is about, so it is resolved BEFORE any store is bound, through a SECURITY DEFINER
function that returns ids only (the device table is FORCE-RLS).

Answers, chosen so the authority behaves well:

* 401  the key is missing or unknown. The authority needs to learn its registration is wrong, so
       this is deliberately not the silent 200 the chat webhooks give strangers.
* 400  a body the authority never documented. It will not help to resend it.
* 200  everything else, including a receipt we do not know and a delivery we already applied.
       The authority retries anything that is not 200, and a retry cannot fix either case.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.core.db import bind_tenant
from app.applications.apparel.modules.einvoice.models import EInvoiceDocument
from app.applications.apparel.modules.einvoice.providers.eta.delivery import (
    apply_device_event,
    apply_receipt_events,
    warn_hours_for,
)
from app.applications.apparel.modules.einvoice.providers.eta.notifications import (
    NotificationError,
    key_hash_from_header,
    parse_general_notification,
    parse_receipt_notification,
)
from app.applications.apparel.modules.einvoice.tracking import attention_of, summarize_documents
from app.modules.identity.deps import DbSession, TenantContext, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/einvoice/eta/notifications", tags=["einvoice"])

_MAX_BODY = 256 * 1024  # a notification is small; refuse anything absurd before parsing it


async def _body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="notification too large")
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="body is not JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return body


async def _till_for_key(session, request: Request):
    """The (tenant, till) the callback key belongs to; binds the tenant. 401 when none."""
    hashed = key_hash_from_header(request.headers.get("authorization"))
    if hashed is None:
        raise HTTPException(status_code=401, detail="missing or malformed ApiKey")
    row = (
        await session.execute(
            text("SELECT * FROM public.resolve_eta_notification_device(:h)"), {"h": hashed}
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=401, detail="unknown key")
    await bind_tenant(session, row.tenant_id)
    return row


@router.put("/receipts")
async def receipt_notification(request: Request, session: DbSession) -> dict:
    row = await _till_for_key(session, request)
    body = await _body(request)
    try:
        events = parse_receipt_notification(body)
    except NotificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    result = await apply_receipt_events(
        session, tenant_id=row.tenant_id, device_id=row.device_id, events=events, raw_body=body
    )
    return {"ok": True, **result}


@router.put("/general")
async def general_notification(request: Request, session: DbSession) -> dict:
    row = await _till_for_key(session, request)
    body = await _body(request)
    try:
        event = parse_general_notification(body)
    except NotificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if event.device_serial != row.device_serial:
        # A key for one till must not move another till's state.
        logger.warning("eta.callback.serial_mismatch device=%s", row.device_id)
        return {"ok": True, "result": "ignored"}
    outcome = await apply_device_event(
        session, tenant_id=row.tenant_id, device_id=row.device_id, event=event, raw_body=body
    )
    return {"ok": True, "result": outcome}


# ---- the merchant's own view -------------------------------------------------------------------
# Read-only, behind the same permission as the sales history: the owner and the accountant need to
# see what the authority accepted, refused, or is about to give up on. Nothing here sends or
# changes a receipt; correcting a refused one is the sender's job.

router_merchant = APIRouter(prefix="/einvoice/receipts", tags=["einvoice"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("orders:read"))]

_STATUS_GROUPS = {
    "accepted": ("reported", "cleared"),
    "waiting": ("submitted", "signed", "draft"),
    "retrying": ("failed",),
    "rejected": ("rejected",),
    "cancelled": ("cancelled",),
}


class ReceiptOut(BaseModel):
    id: str
    invoice_number: str
    document_type: str
    status: str
    # ok | retrying | fix | urgent | expired
    attention: str
    hours_left: float | None
    errors: list[str]
    attempts: int
    next_attempt_at: str | None
    issued_at: str
    order_id: str | None
    authority_uuid: str | None


class ReceiptListOut(BaseModel):
    items: list[ReceiptOut]
    total: int


class SummaryOut(BaseModel):
    total: int
    accepted: int
    waiting: int
    retrying: int
    rejected: int
    fix_now: int
    urgent: int
    expired: int
    needs_attention: int
    warn_hours: int


async def _warn_hours(ctx: TenantContext) -> int:
    return await warn_hours_for(ctx.session, ctx.tenant_id)


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


def _receipt(doc: EInvoiceDocument, *, now: datetime, warn_hours: int) -> dict:
    a = attention_of(doc, now=now, warn_hours=warn_hours)
    return {
        "id": str(doc.id),
        "invoice_number": doc.invoice_number,
        "document_type": doc.document_type,
        "status": doc.status,
        "attention": a.level,
        "hours_left": None if a.hours_left is None else round(a.hours_left, 1),
        "errors": [str(e) for e in (doc.errors or [])],
        "attempts": doc.delivery_attempts or 0,
        "next_attempt_at": doc.next_attempt_at.isoformat() if doc.next_attempt_at else None,
        "issued_at": doc.issued_at.isoformat(),
        "order_id": str(doc.order_id) if doc.order_id else None,
        "authority_uuid": doc.authority_uuid,
    }


@router_merchant.get("/summary", response_model=SummaryOut)
async def receipts_summary(ctx: ReadCtx):
    """The counters at the top of the screen (every Egyptian receipt the shop has issued).

    One GROUP BY for the counts, and rows only for the REFUSED receipts (their deadline needs the
    issue time). A shop with 100k receipts reads a handful of rows, not all of them.
    """
    warn = await _warn_hours(ctx)
    mine = (EInvoiceDocument.tenant_id == ctx.tenant_id, EInvoiceDocument.provider_type == "eta")
    by_status = dict(
        (
            await ctx.session.execute(
                select(EInvoiceDocument.status, func.count())
                .where(*mine)
                .group_by(EInvoiceDocument.status)
            )
        ).all()
    )
    refused = list(
        (
            await ctx.session.execute(
                select(EInvoiceDocument).where(*mine, EInvoiceDocument.status == "rejected")
            )
        )
        .scalars()
        .all()
    )
    out = summarize_documents(refused, now=datetime.now(UTC), warn_hours=warn)
    # the refused ones were counted from their rows; the rest come from the GROUP BY
    others = {k: v for k, v in by_status.items() if k != "rejected"}
    out["total"] = sum(by_status.values())
    out["accepted"] = sum(others.get(s, 0) for s in ("reported", "cleared"))
    out["waiting"] = sum(others.get(s, 0) for s in ("submitted", "signed", "draft"))
    out["retrying"] = others.get("failed", 0)
    return {**out, "warn_hours": warn}


@router_merchant.get("", response_model=ReceiptListOut)
async def list_receipts(
    ctx: ReadCtx,
    group: Annotated[
        str | None, Query(pattern="^(accepted|waiting|retrying|rejected|cancelled)$")
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Receipts newest first. Refused ones that are running out of time come before the rest."""
    warn = await _warn_hours(ctx)
    now = datetime.now(UTC)
    q = select(EInvoiceDocument).where(
        EInvoiceDocument.tenant_id == ctx.tenant_id, EInvoiceDocument.provider_type == "eta"
    )
    if group:
        q = q.where(EInvoiceDocument.status.in_(_STATUS_GROUPS[group]))
    if date_from:
        q = q.where(EInvoiceDocument.issued_at >= _day_start(date_from))
    if date_to:
        q = q.where(EInvoiceDocument.issued_at < _day_start(date_to) + timedelta(days=1))
    docs = list(
        (await ctx.session.execute(q.order_by(EInvoiceDocument.issued_at.desc()))).scalars().all()
    )
    # Refused receipts first, the closest deadline at the top; then everything else by date.
    rank = {"expired": 0, "urgent": 1, "fix": 2, "retrying": 3, "ok": 4}
    rows = [_receipt(d, now=now, warn_hours=warn) for d in docs]
    rows.sort(
        key=lambda r: (rank[r["attention"]], r["hours_left"] if r["hours_left"] is not None else 0)
    )
    return {"items": rows[offset : offset + limit], "total": len(rows)}

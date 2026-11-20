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

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from app.core.db import bind_tenant
from app.modules.einvoice.providers.eta.delivery import apply_device_event, apply_receipt_events
from app.modules.einvoice.providers.eta.notifications import (
    NotificationError,
    key_hash_from_header,
    parse_general_notification,
    parse_receipt_notification,
)
from app.modules.identity.deps import DbSession

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

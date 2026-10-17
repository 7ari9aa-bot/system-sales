"""Channel webhook ingress routes and signature verification."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.registry import get_adapter as default_get_adapter
from app.modules.conversations.routers._deps import DbSession
from app.modules.platform.models import Integration, WebhookEvent

logger = logging.getLogger(__name__)

webhook_router = APIRouter(tags=["channels"])

# Channels accepted on the generic webhook endpoint. Webchat is deliberately
# EXCLUDED: it has no provider signature to verify, so accepting it here would
# let anyone inject messages with a forged "public_key" body field. Webchat
# traffic goes through public_router only (validated + rate-limited there).
_WEBHOOK_CHANNELS = {"whatsapp", "telegram", "messenger", "instagram", "facebook"}


def _get_adapter(channel: str):
    """Resolve adapter with transparent support for monkeypatched router.get_adapter."""
    cr = sys.modules.get("app.modules.conversations.router")
    if cr and hasattr(cr, "get_adapter"):
        fn = cr.get_adapter
        return fn(channel)
    return default_get_adapter(channel)


@webhook_router.get("/webhooks/{channel}")
async def verify_webhook(channel: str, request: Request):
    if channel not in _WEBHOOK_CHANNELS:
        raise NotFoundError(f"unknown channel: {channel}")
    adapter = _get_adapter(channel)
    if adapter is None:
        raise NotFoundError(f"unknown channel: {channel}")
    challenge = adapter.verify_request(dict(request.query_params))
    if challenge is None:
        raise PermissionDeniedError("verification failed")
    return Response(content=challenge, media_type="text/plain")


@webhook_router.post("/webhooks/{channel}")
async def channel_webhook(channel: str, request: Request, session: DbSession):
    """Signature → replay guard → persist raw → queue (§22) → fast ACK."""
    if channel not in _WEBHOOK_CHANNELS:
        raise NotFoundError(f"unknown channel: {channel}")
    adapter = _get_adapter(channel)
    if adapter is None:
        raise NotFoundError(f"unknown channel: {channel}")
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not adapter.check_signature(headers, raw):
        raise PermissionDeniedError("invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        # 422, not the domain 400: an unparsable body is a FRAMEWORK-shaped
        # validation refusal (the same class as a pydantic 422), answered in
        # the unified envelope by the StarletteHTTPException handler with
        # code "validation_error".
        raise HTTPException(status_code=422, detail="unparsable payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be a JSON object")
    payload["_query"] = dict(request.query_params)

    tenant_key = adapter.resolve_tenant_key(payload)
    tenant_id = await IngestService.resolve_tenant(session, channel, tenant_key)

    if tenant_id is None:
        # Unknown tenant: acknowledge without detail (do not leak existence).
        #
        # webhook_events is FORCE-RLS with a strict tenant_isolation policy
        # (tenant_id = app.tenant_id), so a NULL-tenant ingress row cannot be
        # written by the app role under ANY GUC — attempting the insert here
        # would error the request and trigger exactly the provider retry
        # storm §24 exists to avoid. Nothing can be ingested for an
        # unattributed delivery, so log and ACK; the durable audit trail and
        # the §24 retry cover attributed deliveries only.
        logger.info("webhook.unknown_tenant channel=%s", channel)
        return {"ok": True}

    from app.core.db import bind_tenant

    # RLS: the ingress row itself is tenant-scoped — bind the GUC BEFORE the
    # insert. (It used to be bound only after, so the FORCE-RLS WITH CHECK
    # rejected every ingress row and the audit trail the table was built for
    # silently never materialized.)
    await bind_tenant(session, tenant_id)

    # This is transport health, not a claim that the event was processed. The
    # durable WebhookEvent/outbox path below tracks processing independently.
    integration = (
        await session.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.provider == channel,
                Integration.kind == "channel",
                Integration.status.in_(("active", "connected")),
            )
        )
    ).scalar_one_or_none()
    if integration is not None:
        health = dict(integration.webhook_health or {})
        health.update(
            {
                "last_webhook_at": datetime.now(UTC).isoformat(),
                "consecutive_failures": 0,
            }
        )
        health.pop("last_error", None)
        integration.webhook_health = health

    # S10: durable ingress record + replay rejection. Both providers sign a
    # STATIC HMAC over the raw body — neither contract carries a timestamp or
    # nonce — so a captured delivery can be replayed byte-for-byte. The digest
    # of the raw body is stored as the ingress event id and a unique index
    # (uq_webhook_events_provider_external) makes the second insert a no-op.
    # This is also the audit trail the WebhookEvent table was built for and
    # never had written to it.
    digest = hashlib.sha256(raw).hexdigest()
    inserted = (
        await session.execute(
            pg_insert(WebhookEvent)
            .values(
                provider=channel,
                external_event_id=digest,
                tenant_id=tenant_id,
                signature_valid=True,
                payload=payload,
                processing_status="pending",
            )
            .on_conflict_do_nothing(index_elements=["provider", "external_event_id"])
            .returning(WebhookEvent.id)
        )
    ).scalar_one_or_none()
    if inserted is None:
        logger.info("webhook.replay_ignored channel=%s digest=%s", channel, digest[:12])
        # Acknowledge: providers retry on non-2xx, and a retry is exactly what
        # a replay is. Reprocessing would double-write.
        return {"ok": True, "duplicate": True}

    # §22: the request path ENDS here. The long ingest block (parse → customer
    # → conversation → messages → AI fan-out) runs on the WebhookWorker via a
    # ``webhook.ingest`` event staged in THIS transaction — the outbox makes
    # "row persisted + work queued" atomic, so there is no dual-write window.
    # Running it inline turned a slow provider call into a provider timeout →
    # retry storm over the very work that timed out.
    from app.core.events.writer import add_outbox_event

    await add_outbox_event(
        session,
        aggregate_type="webhook",
        aggregate_id=inserted,
        event_type="webhook.ingest",
        tenant_id=tenant_id,
        payload={"webhook_event_id": str(inserted)},
    )
    return {"ok": True, "queued": True}

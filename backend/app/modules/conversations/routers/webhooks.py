"""Channel webhook ingress routes and signature verification."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.meta_page_events import (
    MESSENGER,
    check_page_signature,
    route_page_payload,
    verify_page_request,
)
from app.modules.conversations.gateway.registry import get_adapter as default_get_adapter
from app.modules.conversations.routers._deps import DbSession
from app.modules.platform.models import Integration, WebhookEvent

logger = logging.getLogger(__name__)

#: A channel that still RECEIVES deliveries keeps its transport health current whatever its
#: connection state says. One waiting to be reconnected (`reauth_required`) or limited by Meta
#: (`restricted`) still gets webhooks, and recording only active ones left exactly those looking
#: as if nothing had ever arrived. A removed channel (`disconnected`, `disabled`) is absent on
#: purpose.
HEALTH_TRACKED_STATUSES = ("active", "connected", "reauth_required", "restricted")

webhook_router = APIRouter(tags=["channels"])

# Channels accepted on the generic webhook endpoint. Webchat is deliberately
# EXCLUDED: it has no provider signature to verify, so accepting it here would
# let anyone inject messages with a forged "public_key" body field. Webchat
# traffic goes through public_router only (validated + rate-limited there).
_WEBHOOK_CHANNELS = {"whatsapp", "telegram", "messenger", "instagram", "facebook"}


async def _flag_untenanted(key: str, channel: str, details: dict | None = None) -> None:
    """Name a webhook problem that has no tenant yet (signature/verify failures come first).

    Tenant-less rows are written with ``tenant_id=None`` (the security trail's pre-auth case); the
    caller's own refusal still goes out, so a failure to record can never change the answer.
    """
    from app.core.meta_diagnostics import record_channel_issue

    await record_channel_issue(key, channel=channel, details=details)


@webhook_router.get("/webhooks/{channel}")
async def verify_webhook(channel: str, request: Request):
    if channel not in _WEBHOOK_CHANNELS:
        raise NotFoundError(f"unknown channel: {channel}")
    adapter = default_get_adapter(channel)
    if adapter is None:
        raise NotFoundError(f"unknown channel: {channel}")
    challenge = adapter.verify_request(dict(request.query_params))
    if challenge is None:
        # Meta's "Verify and save" lands here; a wrong verify token is otherwise invisible.
        await _flag_untenanted("webhook.verify_failed", channel)
        raise PermissionDeniedError("verification failed")
    return Response(content=challenge, media_type="text/plain")


@webhook_router.post("/webhooks/{channel}")
async def channel_webhook(channel: str, request: Request, session: DbSession):
    """Signature → replay guard → persist raw → queue (§22) → fast ACK."""
    if channel not in _WEBHOOK_CHANNELS:
        raise NotFoundError(f"unknown channel: {channel}")
    adapter = default_get_adapter(channel)
    if adapter is None:
        raise NotFoundError(f"unknown channel: {channel}")
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not adapter.check_signature(headers, raw):
        # The commonest reason a connected channel receives nothing: the app secret held here is
        # not the one Meta signs with. Count it instead of refusing in silence.
        await _flag_untenanted(
            "webhook.bad_signature",
            channel,
            {"has_signature_header": "x-hub-signature-256" in headers, "bytes": len(raw)},
        )
        raise PermissionDeniedError("invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        await _flag_untenanted("webhook.unparsable", channel, {"bytes": len(raw)})
        # 422, not the domain 400: an unparsable body is a FRAMEWORK-shaped
        # validation refusal (the same class as a pydantic 422), answered in
        # the unified envelope by the StarletteHTTPException handler with
        # code "validation_error".
        raise HTTPException(status_code=422, detail="unparsable payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be a JSON object")
    payload["_query"] = dict(request.query_params)

    # One signed delivery can name several accounts (Meta batches entries). The tenant is resolved
    # per account, so each gets an envelope of its own; otherwise a second account's messages would
    # be filed under the first one's tenant. Adapters without the hook are single-account.
    splitter = getattr(adapter, "split_by_account", None)
    parts = splitter(payload) if callable(splitter) else [payload]
    if len(parts) <= 1:
        return await _ingest_one(
            session, channel, adapter, parts[0] if parts else payload, _delivery_digest(raw)
        )

    results = [
        await _ingest_one(
            session,
            channel,
            adapter,
            part,
            _batch_part_digest(raw, index, adapter.resolve_tenant_key(part)),
        )
        for index, part in enumerate(parts)
    ]
    return {"ok": True, "queued": any(r.get("queued") for r in results), "accounts": len(parts)}


@webhook_router.get("/webhooks/meta/page")
async def verify_meta_page(request: Request):
    """Meta's "Verify and save" for the single ``page`` callback.

    A Meta app has ONE callback URL per object type, but the platform keeps TWO channel records for
    a Page: ``messenger`` (private chat) and ``facebook`` (the Page's feed/mentions). Registering
    the callback under either channel's own URL silently dropped the other kind of news, so the
    Page object is verified HERE, against the Messenger verify token operators already have.
    """
    challenge = verify_page_request(dict(request.query_params))
    if challenge is None:
        # A wrong verify token is otherwise invisible: Meta only shows "couldn't verify".
        await _flag_untenanted("webhook.verify_failed", MESSENGER, {"object": "page"})
        raise PermissionDeniedError("verification failed")
    return Response(content=challenge, media_type="text/plain")


@webhook_router.post("/webhooks/meta/page")
async def meta_page_webhook(request: Request, session: DbSession):
    """The Page object's one callback: chat → Messenger, Page news → Facebook.

    The signature is checked ONCE, over the whole raw body (the delivery is signed as a unit).
    Then ``route_page_payload`` splits it into one envelope per capability per Page — an entry
    carrying both kinds of news contributes a messaging-only copy to Messenger and a changes-only
    copy to Facebook — and each envelope goes through the SAME ``_ingest_one`` the per-channel
    routes use. Tenant resolution, the replay guard and the durable ingress row therefore behave
    exactly as they did when one capability owned the callback.
    """
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not check_page_signature(headers, raw):
        await _flag_untenanted(
            "webhook.bad_signature",
            MESSENGER,
            {
                "object": "page",
                "has_signature_header": "x-hub-signature-256" in headers,
                "bytes": len(raw),
            },
        )
        raise PermissionDeniedError("invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        await _flag_untenanted(
            "webhook.unparsable", MESSENGER, {"object": "page", "bytes": len(raw)}
        )
        raise HTTPException(status_code=422, detail="unparsable payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be a JSON object")
    payload["_query"] = dict(request.query_params)

    routed = route_page_payload(payload)
    capabilities: list[str] = []
    results: list[dict] = []
    for capability, envelopes in routed.items():
        if not envelopes:
            continue
        adapter = default_get_adapter(capability)
        if adapter is None:
            # Not registered in this deployment: ACK the part we cannot serve instead of 500ing
            # the whole delivery — the other capability's events in it are real.
            logger.warning("webhook.meta_page.no_adapter capability=%s", capability)
            continue
        capabilities.append(capability)
        for index, envelope in enumerate(envelopes):
            # The Page delivery was signed ONCE, over the whole body; each capability's envelope
            # is told apart by the capability and its position within it.
            digest = _batch_part_digest(
                raw, index, f"{capability}:{adapter.resolve_tenant_key(envelope)}"
            )
            results.append(await _ingest_one(session, capability, adapter, envelope, digest))

    return {
        "ok": True,
        "queued": any(result.get("queued") for result in results),
        "capabilities": capabilities,
        "deliveries": len(results),
    }


async def _record_transport_health(session, tenant_id, channel: str) -> None:
    """Stamp the channel's `webhook_health` with "a delivery just arrived".

    This is transport health, not a claim that the event was processed: the durable
    WebhookEvent/outbox path tracks processing independently. See HEALTH_TRACKED_STATUSES for
    which channels are stamped.
    """
    integration = (
        await session.execute(
            select(Integration)
            .where(
                Integration.tenant_id == tenant_id,
                Integration.provider == channel,
                Integration.kind == "channel",
                Integration.status.in_(HEALTH_TRACKED_STATUSES),
            )
            # Two rows for one provider can coexist (an old one awaiting reconnect and the new
            # active one); the live connection is the one that owns the health.
            .order_by(
                case((Integration.status.in_(("active", "connected")), 0), else_=1),
                Integration.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if integration is None:
        return
    health = dict(integration.webhook_health or {})
    health.update({"last_webhook_at": datetime.now(UTC).isoformat(), "consecutive_failures": 0})
    health.pop("last_error", None)
    integration.webhook_health = health


def _delivery_digest(raw: bytes) -> str:
    """The replay guard's identity for a single-account delivery: the bytes Meta signed."""
    return hashlib.sha256(raw).hexdigest()


def _batch_part_digest(raw: bytes, index: int, account_key: object) -> str:
    """The digest of ONE account's slice of a batched, signed delivery.

    The digest is what the replay guard compares, so it has to be built from the only thing the
    provider promises to repeat byte-for-byte: the signed body. It used to be
    ``sha256(json.dumps(part, sort_keys=True))`` — a re-serialisation WE invented — which made the
    audit row's ``external_event_id`` name our own JSON rather than the delivery, and let two
    genuinely distinct deliveries that happen to serialise the same collapse into one (the second
    acknowledged as a replay and silently dropped). Position and account tell the parts of ONE
    delivery apart; the signed bytes keep the identity anchored to the provider.
    """
    material = b"\x00".join((raw, str(index).encode(), str(account_key or "").encode()))
    return hashlib.sha256(material).hexdigest()


async def _ingest_one(session, channel: str, adapter, payload: dict, digest: str) -> dict:
    """Tenant -> health -> replay guard -> durable row -> outbox, for one account's envelope."""
    tenant_key = adapter.resolve_tenant_key(payload)
    tenant_id = await IngestService.resolve_tenant(session, channel, tenant_key)

    if tenant_id is None:
        # Account-level news (a template's review state) names the business account, not a phone
        # number. Only an envelope that is nothing BUT that is placed this way, and only when
        # exactly one store owns the account.
        account_of = getattr(adapter, "resolve_template_account", None)
        account = account_of(payload) if callable(account_of) else None
        if account:
            tenant_id = await IngestService.resolve_account_tenant(session, account)

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
        await _flag_untenanted(
            "webhook.unknown_account", channel, {"account_key": str(tenant_key)[:64]}
        )
        return {"ok": True}

    from app.core.db import bind_tenant

    # RLS: the ingress row itself is tenant-scoped — bind the GUC BEFORE the
    # insert. (It used to be bound only after, so the FORCE-RLS WITH CHECK
    # rejected every ingress row and the audit trail the table was built for
    # silently never materialized.)
    await bind_tenant(session, tenant_id)

    await _record_transport_health(session, tenant_id, channel)

    # S10: durable ingress record + replay rejection. Both providers sign a
    # STATIC HMAC over the raw body — neither contract carries a timestamp or
    # nonce — so a captured delivery can be replayed byte-for-byte. The digest
    # of the raw body is stored as the ingress event id and a unique index
    # (uq_webhook_events_provider_external) makes the second insert a no-op.
    # This is also the audit trail the WebhookEvent table was built for and
    # never had written to it.
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

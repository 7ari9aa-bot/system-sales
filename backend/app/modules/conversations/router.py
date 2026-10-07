"""CONVERSATIONS routes — inbox (staff) + public webchat + channel webhooks."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.field_auth import PII_FIELDS, redact_fields
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.inbox import InboxQuery, decode_keyset, encode_keyset
from app.modules.conversations.service import ConversationService
from app.modules.conversations.templates import TemplateInput, TemplateService
from app.modules.identity.deps import (
    AuthedUser,
    DbSession,
    TenantContext,
    TenantCtxDep,
    require_permission,
)
from app.modules.platform.models import Integration, WebhookEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inbox"])
public_router = APIRouter(tags=["channels"])
webhook_router = APIRouter(tags=["channels"])

# Query params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` — see the parameter-declaration rule in
# app/modules/analytics/router.py and the full-app gate in
# tests/test_route_parameter_declarations.py.


# ---------- staff inbox ----------


class SendMessageRequest(BaseModel):
    """§30: outside the customer-service window a free-form reply is refused,
    so the caller must supply an APPROVED template instead."""

    body: str | None = Field(default=None, max_length=4096)
    template_name: str | None = Field(default=None, max_length=127)
    template_vars: dict | None = None
    template_language: str = Field(default="ar", max_length=15)


class AssignRequest(BaseModel):
    user_id: uuid.UUID | None = None


# §146 on the inbox surface. The read model ships the customer's phone under
# ``customer_phone``, which is NOT the bare ``phone`` key ``PII_FIELDS`` names —
# so ``redact_fields``' default set would walk past it and leak the number. The
# explicit set is applied only when the caller lacks ``pii:read``, because
# ``redact_fields`` with ``fields_to_redact`` redacts UNCONDITIONALLY; the same
# shape ``customers/router.py:_redact_issue_item`` settled on for the same trap.
_INBOX_PII_FIELDS = PII_FIELDS | frozenset({"customer_phone"})


def _redact_inbox_item(item: dict, *, permission_codes: set[str]) -> dict:
    """One inbox row as the caller is allowed to see it (§146)."""
    if "pii:read" in permission_codes:
        return dict(item)
    return redact_fields(
        item, permission_codes=permission_codes, fields_to_redact=_INBOX_PII_FIELDS
    )


def _inbox_page(items: list[dict], limit: int) -> tuple[list[dict], str | None]:
    """Split a ``limit + 1`` fetch into ``(page, next_cursor)``.

    The cursor is the page's own SORT KEY, not ``created_at``: the read model
    orders by ``last_message_at DESC NULLS LAST``, and paging on any other
    column skips or repeats rows the moment the two disagree — which they do on
    every active conversation. ``None`` is load-bearing for the never-messaged
    tail; see ``inbox.encode_keyset``.
    """
    if len(items) <= limit:
        return items, None
    boundary = items[limit - 1]
    # The row's own sort key, NULL included. Falling back to ``created_at``
    # here would hand ``InboxQuery.page`` a DATED cursor for a tail row, which
    # re-admits every dated row that sorts above it — the duplication this
    # whole branch exists to avoid, arriving one page in.
    at = boundary["last_message_at"]
    return items[:limit], encode_keyset(
        datetime.fromisoformat(at) if at else None, uuid.UUID(boundary["id"])
    )


@router.get("/conversations")
async def list_conversations(
    ctx: TenantCtxDep,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """The conversation list, served by the §137 inbox read model.

    Wire shape is unchanged; the read behind it is one statement instead of
    two, and it no longer runs out of the write service.
    """
    before_at, before_id = decode_keyset(cursor) if cursor else (None, None)
    rows = await InboxQuery.page(
        ctx.session,
        ctx.tenant_id,
        status=status,
        customer_id=customer_id,
        limit=limit + 1,
        before_at=before_at,
        before_id=before_id,
    )
    page, next_cursor = _inbox_page(rows, limit)
    return {
        "items": [
            {
                key: _redact_inbox_item(item, permission_codes=ctx.permission_codes)[key]
                for key in (
                    "id",
                    "customer_id",
                    "customer_name",
                    "customer_phone",
                    "channel",
                    "status",
                    "unread_count",
                    "assignee_user_id",
                    "last_message_at",
                )
            }
            for item in page
        ],
        "next_cursor": next_cursor,
    }


@router.get("/inbox")
async def inbox_query(
    ctx: TenantCtxDep,
    status: str | None = None,
    assignee_user_id: uuid.UUID | None = None,
    unassigned: bool = False,
    channel: str | None = None,
    customer_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """§137 ``InboxQuery``: the whole inbox page in one read.

    Conversation + customer + last message + assignment + unread + SLA clock,
    with §99's views (``my`` / ``unassigned`` / status slices) expressed as SQL
    predicates. Before this endpoint had a read model of its own it answered
    none of the last-message or SLA columns and the browser joined ``/sla/risk``
    into it; the filters it does have now are why "My Inbox" can page correctly.
    """
    before_at, before_id = decode_keyset(cursor) if cursor else (None, None)
    rows = await InboxQuery.page(
        ctx.session,
        ctx.tenant_id,
        status=status,
        assignee_user_id=assignee_user_id,
        unassigned=unassigned,
        channel=channel,
        customer_id=customer_id,
        limit=limit + 1,
        before_at=before_at,
        before_id=before_id,
    )
    page, next_cursor = _inbox_page(rows, limit)
    return {
        "items": [_redact_inbox_item(i, permission_codes=ctx.permission_codes) for i in page],
        "next_cursor": next_cursor,
    }


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    ctx: TenantCtxDep,
    conversation_id: uuid.UUID,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)
    # The service fetches newest-first (keyset) and returns oldest-first for
    # display; the extra (oldest) row only signals that more history exists.
    rows = await ConversationService.list_messages(
        ctx.session,
        ctx.tenant_id,
        conversation_id,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[1:]  # drop the overflow row (oldest) from the display page
        boundary = rows[0]  # oldest displayed row = next page's keyset boundary
        next_cursor = encode_cursor(boundary.created_at, boundary.id)
    storage_keys = await ConversationService.attachment_storage_keys(
        ctx.session, ctx.tenant_id, [message.id for message in rows]
    )
    media_urls = {}
    if storage_keys:
        from app.core.storage import get_storage

        storage = get_storage()
        for message_id, key in storage_keys.items():
            try:
                media_urls[message_id] = storage.signed_url(key)
            except Exception:
                logger.exception(
                    "media.signed_url_failed tenant=%s message=%s",
                    ctx.tenant_id,
                    message_id,
                )
                # A durable private object must never fall back to its expired
                # provider URL when signing fails.
                media_urls[message_id] = None
    return {
        "items": [
            {
                "id": str(m.id),
                "direction": m.direction,
                "sender_type": m.sender_type,
                "body": m.body,
                "media_url": media_urls.get(m.id, m.media_url),
                "media_type": m.media_type,
                "status": m.status,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ],
        "next_cursor": next_cursor,
    }


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    from app.core.events.writer import add_outbox_event

    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    if conversation.status == "closed":
        raise ConflictError("conversation is closed")
    if not body.body and not body.template_name:
        raise ValidationError("message needs body or template_name")

    # The policy decision lives in ConversationService.add_message so that the
    # AI, automation and campaigns are bound by exactly the same rule.
    message = await ConversationService.add_message(
        ctx.session,
        ctx.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        sender_type="agent",
        body=body.body,
        sender_user_id=ctx.user.id,
        template_name=body.template_name,
        template_vars=body.template_vars,
    )
    await add_outbox_event(
        ctx.session,
        aggregate_type="message",
        aggregate_id=message.id,
        event_type="message.outbound",
        tenant_id=ctx.tenant_id,
        payload={"message_id": str(message.id), "conversation_id": str(conversation_id)},
    )
    return {"id": str(message.id), "status": message.status}


@router.post("/conversations/{conversation_id}/assign")
async def assign(
    conversation_id: uuid.UUID,
    body: AssignRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    # S11 (IDOR): any user id used to be accepted — including one belonging to
    # another tenant — and the resulting FK error told the caller whether that
    # user exists (a cross-tenant existence oracle). Resolve the assignee
    # through tenant_users instead, which is exactly "is this person on my
    # team"; tenant_users RLS makes other tenants' rows invisible here.
    if body.user_id is not None and body.user_id != ctx.user.id:
        from sqlalchemy import select as sa_select

        from app.modules.identity.models import TenantUser

        member = (
            await ctx.session.execute(
                sa_select(TenantUser.user_id).where(
                    TenantUser.tenant_id == ctx.tenant_id,
                    TenantUser.user_id == body.user_id,
                )
            )
        ).scalar_one_or_none()
        if member is None:
            raise NotFoundError("assignee is not a member of this tenant")

    assignment = await ConversationService.assign(
        ctx.session,
        ctx.tenant_id,
        conversation_id,
        assigned_to_user_id=body.user_id,
        assigned_by_user_id=ctx.user.id,
    )
    return {"id": str(assignment.id)}


@router.post("/conversations/{conversation_id}/close")
async def close(
    conversation_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    await ConversationService.close(ctx.session, ctx.tenant_id, conversation_id)
    await ConversationService.audit(
        ctx.session, ctx.tenant_id, ctx.user.id, "conversation.closed", str(conversation_id)
    )
    return {"ok": True}


@router.post("/conversations/{conversation_id}/read")
async def mark_read(ctx: TenantCtxDep, conversation_id: uuid.UUID):
    await ConversationService.mark_read(ctx.session, ctx.tenant_id, conversation_id)
    return {"ok": True}


# ---------- public webchat ----------


class WebchatInbound(BaseModel):
    body: str = Field(min_length=1, max_length=4096)
    client_message_id: str | None = Field(default=None, max_length=64)
    visitor_name: str | None = Field(default=None, max_length=255)
    # S2: the visitor identity is SERVER-ISSUED. The first message returns a
    # `session_token`; every later message must present it. The client never
    # chooses its own session key.
    session_token: str | None = Field(default=None, max_length=4096)


@public_router.post("/webchat/{public_key}/messages", status_code=201)
async def webchat_inbound(public_key: str, body: WebchatInbound, session: DbSession):
    from app.core.db import bind_tenant
    from app.core.security import create_visitor_token, decode_visitor_token

    adapter = get_adapter("webchat")
    if adapter is None:  # pragma: no cover — registry always has webchat
        raise NotFoundError("webchat disabled")
    tenant_id = await IngestService.resolve_tenant(session, "webchat", public_key)
    if tenant_id is None:
        raise NotFoundError("unknown widget key")

    # S2: a client-chosen session_key was the ONLY visitor identity, so anyone
    # who guessed (or observed) one could read and post into that visitor's
    # conversation. Identity now comes from a token we signed for THIS tenant
    # and THIS widget; a first-time visitor is issued a fresh random key.
    session_key: str | None = None
    if body.session_token:
        claims = decode_visitor_token(body.session_token)
        if claims.get("tenant_id") != str(tenant_id):
            raise PermissionDeniedError("visitor session belongs to another tenant")
        if claims.get("widget") != public_key:
            raise PermissionDeniedError("visitor session belongs to another widget")
        session_key = str(claims["sub"])
    if not session_key:
        session_key = uuid.uuid4().hex

    # RLS: ingest writes tenant-scoped rows — bind the GUC before any insert.
    await bind_tenant(session, tenant_id)
    accepted = 0
    for message in adapter.parse_inbound({**body.model_dump(), "session_key": session_key}):
        conversation_id = await IngestService.ingest(
            session,
            tenant_id=tenant_id,
            message=message,
            idempotency_scope="webhook:webchat",
        )
        if conversation_id is not None:
            accepted += 1
    # NOTE: conversation_id is deliberately NOT returned — it leaked the
    # staff-side record id to an anonymous caller for no functional reason.
    return {
        "ok": True,
        "accepted": accepted,
        "session_token": create_visitor_token(session_key, str(tenant_id), widget=public_key),
    }


# ---------- channel webhooks (generic dispatch through the registry) ----------

# Channels accepted on the generic webhook endpoint. Webchat is deliberately
# EXCLUDED: it has no provider signature to verify, so accepting it here would
# let anyone inject messages with a forged "public_key" body field. Webchat
# traffic goes through public_router only (validated + rate-limited there).
_WEBHOOK_CHANNELS = {"whatsapp", "telegram", "messenger", "instagram"}


@webhook_router.get("/webhooks/{channel}")
async def verify_webhook(channel: str, request: Request):
    if channel not in _WEBHOOK_CHANNELS:
        raise NotFoundError(f"unknown channel: {channel}")
    adapter = get_adapter(channel)
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
    adapter = get_adapter(channel)
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


@router.post("/conversations/messages/reconcile")
async def reconcile_messages(
    minutes: Annotated[int, Query(ge=1, le=1440)] = 15,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Reconcile messages stuck in 'unknown' or 'sending' for longer than threshold."""
    reconciled = await ConversationService.reconcile_unknown_messages(
        ctx.session, ctx.tenant_id, stuck_threshold_minutes=minutes
    )
    return {"reconciled_count": len(reconciled), "items": reconciled}


# ---------- realtime (SSE) ----------


async def _stream_auth(request: Request, token: str | None) -> AuthedUser:
    """Authenticate the staff inbox SSE stream.

    EventSource cannot set headers, so the access token arrives as ?token=; a
    standard `Authorization: Bearer` header is accepted too.

    S9: this endpoint used to decode the JWT and stream the tenant's inbox on the
    strength of the signature alone — it never checked that the user still
    exists, is still active, is still a member of the tenant, or that the
    workspace may still use the API. A deactivated user or a removed member kept
    a live feed of message bodies for the whole token lifetime.

    Mirrors `app.modules.realtime.router._sse_auth`. It deliberately opens its
    OWN short-lived session rather than taking the request-scoped `DbSession`:
    FastAPI tears dependency generators down only AFTER the response completes,
    so a request-scoped session would pin a pooled connection for the entire
    lifetime of the stream (hours) — a handful of open inboxes would exhaust the
    pool for the whole platform (the same failure class as R4).
    """
    from sqlalchemy import select as sa_select
    from sqlalchemy import text as sa_text

    from app.core.db import SessionLocal
    from app.core.errors import PermissionDeniedError
    from app.core.security import decode_token
    from app.modules.identity.deps import tenant_may_use_api
    from app.modules.identity.models import Tenant, TenantUser, User

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header.split(" ", 1)[1].strip()
    elif token:
        raw_token = token
    else:
        raise PermissionDeniedError("missing bearer token")

    try:
        payload = decode_token(raw_token)
        if payload.get("type") != "access":
            raise PermissionDeniedError("wrong token type")
        if not payload.get("tenant_id"):
            # Fail closed: a tenant-less token must never open a stream —
            # every frame in this generator is tenant-filtered.
            raise PermissionDeniedError("token has no tenant")
        user_id = uuid.UUID(str(payload["sub"]))
        tenant_id = uuid.UUID(payload["tenant_id"])
    except PermissionDeniedError:
        raise
    except Exception as exc:
        raise PermissionDeniedError("invalid token") from exc

    async with SessionLocal() as session:
        async with session.begin():
            # `users` is global (no RLS) so this runs before any tenant GUC.
            auth_state = (
                await session.execute(
                    sa_select(User.is_active, User.auth_version).where(User.id == user_id)
                )
            ).one_or_none()
            if auth_state is None or not auth_state.is_active:
                raise PermissionDeniedError("account is inactive")
            if int(payload.get("auth_version", 0)) != int(auth_state.auth_version or 0):
                raise PermissionDeniedError("session revoked by password reset")

            # Bind the user GUC so the tenant_users self-access policy exposes
            # the membership row for the check below.
            await session.execute(
                sa_text("SELECT set_config('app.user_id', :uid, true)"),
                {"uid": str(user_id)},
            )
            member = (
                await session.execute(
                    sa_select(TenantUser.user_id).where(
                        TenantUser.tenant_id == tenant_id,
                        TenantUser.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                raise PermissionDeniedError("not a member of this tenant")

            # §48: checked AFTER membership so the state is never disclosed to a
            # non-member. A suspended workspace must not keep a live inbox.
            lifecycle_state = (
                await session.execute(
                    sa_select(Tenant.lifecycle_state).where(Tenant.id == tenant_id)
                )
            ).scalar_one_or_none()
            if lifecycle_state is None:
                raise PermissionDeniedError("tenant not found")
            if not tenant_may_use_api(lifecycle_state):
                raise PermissionDeniedError(
                    f"workspace is {lifecycle_state} — inbox stream is unavailable"
                )

    return AuthedUser(id=user_id, tenant_id=tenant_id, role_code=payload.get("role"))


@router.get("/conversations/stream")
async def stream_conversations(request: Request, token: str | None = None):
    """Server-Sent Events feed of inbox state changes.

    EventSource cannot set headers, so the access token arrives as ?token=.
    The caller must be an active member of an operational workspace — see
    `_stream_auth`, which mirrors the realtime gateway's gate. Each tick opens a
    short session bound to the tenant GUC; the loop yields only when the inbox
    state digest changes. Connections recycle after MAX_STREAM_SECONDS so
    deploys roll cleanly.
    """
    import asyncio
    import hashlib
    import json

    from fastapi.responses import StreamingResponse

    from app.core.db import SessionLocal, bind_tenant

    user = await _stream_auth(request, token)

    async def event_stream():
        last_digest = None
        started = time.monotonic()
        try:
            while time.monotonic() - started < 300:  # recycle every 5 minutes
                if await request.is_disconnected():
                    return
                from sqlalchemy import select as sa_select

                from app.modules.conversations.models import Conversation

                try:
                    async with SessionLocal() as session:
                        async with session.begin():
                            await bind_tenant(session, user.tenant_id)
                            rows = (
                                await session.execute(
                                    sa_select(
                                        Conversation.id,
                                        Conversation.status,
                                        Conversation.unread_count,
                                        Conversation.last_message_at,
                                        Conversation.assignee_user_id,
                                    )
                                    .where(Conversation.tenant_id == user.tenant_id)
                                    .order_by(Conversation.last_message_at.desc().nullslast())
                                    .limit(100)
                                )
                            ).all()
                except Exception:  # noqa: BLE001 — DB hiccup: keep the stream alive
                    await asyncio.sleep(3)
                    continue
                snapshot = [
                    {
                        "id": str(r.id),
                        "status": r.status,
                        "unread": r.unread_count,
                        "last": r.last_message_at.isoformat() if r.last_message_at else None,
                        "assignee": str(r.assignee_user_id) if r.assignee_user_id else None,
                    }
                    for r in rows
                ]
                digest = hashlib.sha1(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
                if digest != last_digest:
                    last_digest = digest
                    payload_json = json.dumps({"conversations": snapshot}, default=str)
                    yield f"event: inbox\ndata: {payload_json}\n\n"
                await asyncio.sleep(2)
        except asyncio.CancelledError:  # client disconnected
            return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- message templates (§31) ----------
#
# A template must be APPROVED before it can reach a customer outside the
# service window, and the policy engine refuses anything that is not. These
# routes are the only way a template becomes sendable — without them the
# window enforcement would block a tenant with no way to comply.

templates_router = APIRouter(prefix="/message-templates", tags=["templates"])


class TemplateUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    body_text: str = Field(min_length=1, max_length=4096)
    language: str = Field(default="ar", max_length=15)
    provider: str = Field(default="whatsapp", max_length=31)
    variables: list[str] = Field(default_factory=list)


class TemplateRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class TemplateApproveRequest(BaseModel):
    provider_template_id: str | None = Field(default=None, max_length=127)


def _template_out(t) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "status": t.status,
        "language": t.language,
        "provider": t.provider,
        "body_text": t.body_text,
        "variables": t.variables or [],
        "provider_template_id": t.provider_template_id,
        "version": t.version,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _template_input(body: TemplateUpsertRequest) -> TemplateInput:
    return TemplateInput(
        name=body.name,
        body_text=body.body_text,
        language=body.language,
        provider=body.provider,
        variables=tuple(body.variables),
    )


@templates_router.get("")
async def list_templates(
    ctx: TenantContext = Depends(require_permission("conversations:read")),
    status: str | None = None,
    provider: str | None = None,
):
    rows = await TemplateService.list_templates(
        ctx.session, ctx.tenant_id, status=status, provider=provider
    )
    return {"items": [_template_out(t) for t in rows]}


@templates_router.post("", status_code=201)
async def create_template(
    body: TemplateUpsertRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Creates a DRAFT — not sendable until it is submitted and approved."""
    template = await TemplateService.create(ctx.session, ctx.tenant_id, _template_input(body))
    return _template_out(template)


@templates_router.get("/{template_id}")
async def get_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    return _template_out(await TemplateService.get(ctx.session, ctx.tenant_id, template_id))


@templates_router.put("/{template_id}")
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpsertRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Only draft/rejected templates are editable — see TemplateService."""
    template = await TemplateService.update(
        ctx.session, ctx.tenant_id, template_id, _template_input(body)
    )
    return _template_out(template)


@templates_router.post("/{template_id}/submit")
async def submit_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    template = await TemplateService.submit(ctx.session, ctx.tenant_id, template_id)
    return _template_out(template)


@templates_router.post("/{template_id}/approve")
async def approve_template(
    template_id: uuid.UUID,
    body: TemplateApproveRequest | None = None,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Approval is a governance action, so it needs settings:write — not the
    same permission as writing a message."""
    template = await TemplateService.approve(
        ctx.session,
        ctx.tenant_id,
        template_id,
        reviewer=str(ctx.user.id),
        provider_template_id=body.provider_template_id if body else None,
    )
    return _template_out(template)


@templates_router.post("/{template_id}/reject")
async def reject_template(
    template_id: uuid.UUID,
    body: TemplateRejectRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    template = await TemplateService.reject(
        ctx.session,
        ctx.tenant_id,
        template_id,
        reason=body.reason,
        reviewer=str(ctx.user.id),
    )
    return _template_out(template)


@templates_router.post("/{template_id}/pause")
async def pause_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    return _template_out(await TemplateService.pause(ctx.session, ctx.tenant_id, template_id))


@templates_router.post("/{template_id}/resume")
async def resume_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    return _template_out(await TemplateService.resume(ctx.session, ctx.tenant_id, template_id))


@templates_router.post("/{template_id}/archive")
async def archive_template(
    template_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    return _template_out(await TemplateService.archive(ctx.session, ctx.tenant_id, template_id))

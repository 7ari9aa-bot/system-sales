"""CONVERSATIONS routes — inbox (staff) + public webchat + channel webhooks."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.service import ConversationService
from app.modules.conversations.templates import TemplateInput, TemplateService
from app.modules.identity.deps import DbSession, TenantContext, TenantCtxDep, require_permission
from app.modules.platform.models import WebhookEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inbox"])
public_router = APIRouter(tags=["channels"])
webhook_router = APIRouter(tags=["channels"])


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


@router.get("/conversations")
async def list_conversations(
    ctx: TenantCtxDep,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)
    rows = await ConversationService.list_inbox(
        ctx.session,
        ctx.tenant_id,
        status=status,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:  # full page → cursor at the page's oldest boundary
        boundary = page[-1]
        next_cursor = encode_cursor(boundary.created_at, boundary.id)
    return {
        "items": [
            {
                "id": str(c.id),
                "customer_id": str(c.customer_id),
                "customer_name": getattr(c, "customer_name", None),
                "customer_phone": getattr(c, "customer_phone", None),
                "channel": c.channel,
                "status": c.status,
                "unread_count": c.unread_count,
                "assignee_user_id": str(c.assignee_user_id) if c.assignee_user_id else None,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            }
            for c in page
        ],
        "next_cursor": next_cursor,
    }


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    ctx: TenantCtxDep,
    conversation_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
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
    return {
        "items": [
            {
                "id": str(m.id),
                "direction": m.direction,
                "sender_type": m.sender_type,
                "body": m.body,
                "media_url": m.media_url,
                "media_type": m.media_type,
                "status": m.status,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ],
        "next_cursor": next_cursor,
    }


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def send_message(ctx: TenantCtxDep, conversation_id: uuid.UUID, body: SendMessageRequest):
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
    for message in adapter.parse_inbound(
        {**body.model_dump(), "session_key": session_key}
    ):
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
        "session_token": create_visitor_token(
            session_key, str(tenant_id), widget=public_key
        ),
    }


# ---------- channel webhooks (generic dispatch through the registry) ----------

# Channels accepted on the generic webhook endpoint. Webchat is deliberately
# EXCLUDED: it has no provider signature to verify, so accepting it here would
# let anyone inject messages with a forged "public_key" body field. Webchat
# traffic goes through public_router only (validated + rate-limited there).
_WEBHOOK_CHANNELS = {"whatsapp", "telegram"}


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
    """Signature check → replay guard → durable ingest (per-channel adapter)."""
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
        raise ValidationError("unparsable payload") from exc
    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object")
    payload["_query"] = dict(request.query_params)

    tenant_key = adapter.resolve_tenant_key(payload)
    tenant_id = await IngestService.resolve_tenant(session, channel, tenant_key)

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
                processing_status="processing",
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

    if tenant_id is None:
        # Unknown tenant: acknowledge without detail (do not leak existence).
        return {"ok": True}
    # RLS: ingest writes tenant-scoped rows — bind the GUC before any insert.
    from app.core.db import bind_tenant

    await bind_tenant(session, tenant_id)
    accepted = 0
    for message in adapter.parse_inbound(payload):
        conversation_id = await IngestService.ingest(
            session,
            tenant_id=tenant_id,
            message=message,
            idempotency_scope=f"webhook:{channel}",
        )
        if conversation_id is not None:
            accepted += 1
    await _apply_status_updates(session, tenant_id, adapter.parse_status_updates(payload))
    await session.execute(
        sa_update(WebhookEvent)
        .where(WebhookEvent.id == inserted)
        .values(processing_status="processed", attempts=1)
    )
    return {"ok": True, "accepted": accepted}


async def _apply_status_updates(session, tenant_id, updates) -> None:
    """Delivery receipts: update our outbound message rows by provider id.

    Monotonic state machine (§130): a receipt may only move a message
    forward. Out-of-order or replayed provider events (e.g. a late `sent`
    after `read`) are dropped instead of regressing the row.
    """
    from sqlalchemy import update as sa_update

    from app.modules.conversations.models import Message

    # target status → statuses it may legally be advanced from
    _FORWARD_FROM: dict[str, tuple[str, ...]] = {
        "sent": ("queued", "sending", "unknown"),
        "delivered": ("queued", "sending", "unknown", "sent"),
        "read": ("queued", "sending", "unknown", "sent", "delivered"),
        "failed": ("queued", "sending", "unknown"),
    }

    for receipt in updates:
        if not receipt.channel_message_id or not receipt.status:
            continue
        allowed_from = _FORWARD_FROM.get(receipt.status)
        if allowed_from is None:
            continue  # unknown/arbitrary provider status — never written raw
        values: dict = {"status": receipt.status}
        if receipt.error:
            values["error"] = receipt.error
        await session.execute(
            sa_update(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.channel_message_id == receipt.channel_message_id,
                Message.direction == "outbound",
                Message.status.in_(allowed_from),
            )
            .values(**values)
        )


@router.post("/conversations/messages/reconcile")
async def reconcile_messages(
    minutes: int = Query(default=15, ge=1, le=1440),
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Reconcile messages stuck in 'unknown' or 'sending' for longer than threshold."""
    reconciled = await ConversationService.reconcile_unknown_messages(
        ctx.session, ctx.tenant_id, stuck_threshold_minutes=minutes
    )
    return {"reconciled_count": len(reconciled), "items": reconciled}


# ---------- realtime (SSE) ----------

@router.get("/conversations/stream")
async def stream_conversations(request: Request, token: str):
    """Server-Sent Events feed of inbox state changes.

    EventSource cannot set headers, so the access token arrives as ?token=.
    Each tick opens a short session bound to the tenant GUC; the loop yields
    only when the inbox state digest changes. Connections recycle after
    MAX_STREAM_SECONDS so deploys roll cleanly.
    """
    import asyncio
    import hashlib
    import json

    from fastapi.responses import StreamingResponse

    from app.core.db import SessionLocal, bind_tenant
    from app.core.errors import PermissionDeniedError
    from app.core.security import decode_token
    from app.modules.identity.deps import AuthedUser

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise PermissionDeniedError("wrong token type")
        user = AuthedUser(
            id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tenant_id"]) if payload.get("tenant_id") else None,
            role_code=payload.get("role"),
        )
        if user.tenant_id is None:
            raise PermissionDeniedError("no tenant")
    except PermissionDeniedError:
        raise
    except Exception as exc:
        raise PermissionDeniedError("invalid token") from exc

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
                digest = hashlib.sha1(
                    json.dumps(snapshot, sort_keys=True).encode()
                ).hexdigest()
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

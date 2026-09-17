"""CONVERSATIONS routes — inbox (staff) + public webchat + channel webhooks."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.service import ConversationService
from app.modules.identity.deps import DbSession, TenantCtxDep

router = APIRouter(tags=["inbox"])
public_router = APIRouter(tags=["channels"])
webhook_router = APIRouter(tags=["channels"])


# ---------- staff inbox ----------


class SendMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4096)


class AssignRequest(BaseModel):
    user_id: uuid.UUID | None = None


@router.get("/conversations")
async def list_conversations(
    ctx: TenantCtxDep, status: str | None = None, limit: int = 50, offset: int = 0
):
    rows = await ConversationService.list_inbox(
        ctx.session, ctx.tenant_id, status=status, limit=limit, offset=offset
    )
    return [
        {
            "id": str(c.id),
            "customer_id": str(c.customer_id),
            "channel": c.channel,
            "status": c.status,
            "unread_count": c.unread_count,
            "assignee_user_id": str(c.assignee_user_id) if c.assignee_user_id else None,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        }
        for c in rows
    ]


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(ctx: TenantCtxDep, conversation_id: uuid.UUID, limit: int = 100):
    rows = await ConversationService.list_messages(
        ctx.session, ctx.tenant_id, conversation_id, limit=limit
    )
    return [
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
    ]


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def send_message(ctx: TenantCtxDep, conversation_id: uuid.UUID, body: SendMessageRequest):
    from app.core.events.writer import add_outbox_event

    message = await ConversationService.add_message(
        ctx.session,
        ctx.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        sender_type="agent",
        body=body.body,
        sender_user_id=ctx.user.id,
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
async def assign(ctx: TenantCtxDep, conversation_id: uuid.UUID, body: AssignRequest):
    assignment = await ConversationService.assign(
        ctx.session,
        ctx.tenant_id,
        conversation_id,
        assigned_to_user_id=body.user_id,
        assigned_by_user_id=ctx.user.id,
    )
    return {"id": str(assignment.id)}


@router.post("/conversations/{conversation_id}/close")
async def close(ctx: TenantCtxDep, conversation_id: uuid.UUID):
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
    session_key: str = Field(min_length=8, max_length=64)
    body: str = Field(min_length=1, max_length=4096)
    client_message_id: str | None = Field(default=None, max_length=64)
    visitor_name: str | None = Field(default=None, max_length=255)


@public_router.post("/webchat/{public_key}/messages", status_code=201)
async def webchat_inbound(public_key: str, body: WebchatInbound, session: DbSession):
    adapter = get_adapter("webchat")
    if adapter is None:  # pragma: no cover — registry always has webchat
        raise NotFoundError("webchat disabled")
    tenant_id = await IngestService.resolve_tenant(session, "webchat", public_key)
    if tenant_id is None:
        raise NotFoundError("unknown widget key")
    accepted = 0
    conversation_id = None
    for message in adapter.parse_inbound(body.model_dump()):
        conversation_id = await IngestService.ingest(
            session,
            tenant_id=tenant_id,
            message=message,
            idempotency_scope="webhook:webchat",
        )
        if conversation_id is not None:
            accepted += 1
    return {
        "ok": True,
        "accepted": accepted,
        "conversation_id": str(conversation_id) if conversation_id else None,
    }


# ---------- channel webhooks (generic dispatch through the registry) ----------


@webhook_router.get("/webhooks/{channel}")
async def verify_webhook(channel: str, request: Request):
    adapter = get_adapter(channel)
    if adapter is None:
        raise NotFoundError(f"unknown channel: {channel}")
    challenge = adapter.verify_request(dict(request.query_params))
    if challenge is None:
        raise PermissionDeniedError("verification failed")
    return Response(content=challenge, media_type="text/plain")


@webhook_router.post("/webhooks/{channel}")
async def channel_webhook(channel: str, request: Request, session: DbSession):
    """Signature check → normalize → durable ingest (per-channel adapter)."""
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
        raise NotFoundError("unparsable payload") from exc
    if isinstance(payload, dict):
        payload["_query"] = dict(request.query_params)

    tenant_key = adapter.resolve_tenant_key(payload)
    tenant_id = await IngestService.resolve_tenant(session, channel, tenant_key)
    if tenant_id is None:
        # Unknown tenant: acknowledge without detail (do not leak existence).
        return {"ok": True}
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
    return {"ok": True, "accepted": accepted}


async def _apply_status_updates(session, tenant_id, updates) -> None:
    """Delivery receipts: update our outbound message rows by provider id."""
    from sqlalchemy import update as sa_update

    from app.modules.conversations.models import Message

    for receipt in updates:
        if not receipt.channel_message_id or not receipt.status:
            continue
        values: dict = {"status": receipt.status}
        if receipt.error:
            values["error"] = receipt.error
        await session.execute(
            sa_update(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.channel_message_id == receipt.channel_message_id,
            )
            .values(**values)
        )

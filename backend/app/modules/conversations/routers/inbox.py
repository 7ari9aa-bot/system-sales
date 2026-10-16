"""Staff inbox and conversation management routes."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.conversations.inbox import InboxQuery, decode_keyset
from app.modules.conversations.routers._deps import (
    AssignRequest,
    SendMessageRequest,
    TenantContext,
    TenantCtxDep,
    _inbox_page,
    _redact_inbox_item,
    require_permission,
)
from app.modules.conversations.service import ConversationService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inbox"])


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

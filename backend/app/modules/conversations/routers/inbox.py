"""Staff inbox and conversation management routes."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.conversations.gateway.whatsapp import REACTION_REMOVED
from app.modules.conversations.inbox import InboxQuery, decode_keyset
from app.modules.conversations.outbound_media import (
    ABSOLUTE_MAX_BYTES,
    check_caption,
    check_outbound_media,
    content_type_for,
)
from app.modules.conversations.outbound_media_service import OutboundMediaService
from app.modules.conversations.routers._deps import (
    AssignRequest,
    ListStateRequest,
    ReactionRequest,
    SendMessageRequest,
    TenantContext,
    TenantCtxDep,
    _inbox_page,
    _redact_inbox_item,
    require_permission,
)
from app.modules.conversations.service import ConversationService
from app.modules.platform.services import channel_access as _channel_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inbox"])


async def _allowed_channels(ctx: TenantContext) -> set[str] | None:
    return await _channel_access.allowed_providers(
        ctx.session, ctx.tenant_id, ctx.user.id, ctx.role_code
    )


async def _sendable_channels(ctx: TenantContext) -> set[str] | None:
    """Providers this user may SEND on — the stricter can_send grant."""
    return await _channel_access.sendable_providers(
        ctx.session, ctx.tenant_id, ctx.user.id, ctx.role_code
    )


async def _ensure_channel_access(ctx: TenantContext, conversation) -> None:
    allowed = await _allowed_channels(ctx)
    if allowed is not None and conversation.channel not in allowed:
        raise PermissionDeniedError("channel is not enabled for this user")


async def _ensure_channel_send(ctx: TenantContext, conversation) -> None:
    """The SEND enforcement point: visibility is not permission to reply.

    The owner console can set can_send=False on a member (view-only); the
    send route used to check is_enabled alone, so the advertised control was
    inert (deep self-review HIGH).
    """
    sendable = await _sendable_channels(ctx)
    if sendable is not None and conversation.channel not in sendable:
        raise PermissionDeniedError("sending is not enabled for this user on this channel")


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
        channels=await _allowed_channels(ctx),
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
                    "pinned_at",
                    "muted_until",
                    "archived_at",
                    "marked_unread",
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
    archived: bool = False,
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
        channels=await _allowed_channels(ctx),
        customer_id=customer_id,
        archived=archived,
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
    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
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
    on_page = {m.id for m in rows}
    outside_page = await ConversationService.quoted_targets(
        ctx.session,
        ctx.tenant_id,
        conversation_id,
        [
            m.reply_to_message_id
            for m in rows
            if m.reply_to_message_id and m.reply_to_message_id not in on_page
        ],
    )
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
        "items": _present_messages(rows, media_urls, outside_page),
        "next_cursor": next_cursor,
    }


def _present_messages(rows, media_urls: dict, outside_page: dict | None = None) -> list[dict]:
    """Shape a page of messages the way a chat client draws them.

    A reaction is not a message of its own: WhatsApp shows it as a small emoji
    under the message it targets. We store it as a row (it arrives as one), so
    fold each reaction into its target here and drop the row from the list.
    Only the newest reaction per sender counts (WhatsApp lets a person change
    or remove theirs; an empty emoji removes it).
    """
    by_id = {m.id: m for m in rows}
    quotable = {**(outside_page or {}), **by_id}
    reactions: dict = {}
    # Order by when the PROVIDER says it happened: two reactions in one webhook
    # batch share a database timestamp, so created_at alone cannot tell which
    # is the newer one.
    for m in sorted(rows, key=_provider_order):
        if m.content_type != "reaction" or m.reply_to_message_id not in by_id:
            continue
        emoji = (m.body or "").strip()
        reactions.setdefault(m.reply_to_message_id, {})[m.direction] = (
            "" if emoji == REACTION_REMOVED else emoji
        )

    items: list[dict] = []
    for m in rows:
        if m.content_type == "reaction" and m.reply_to_message_id in by_id:
            continue  # shown on its target, not as a line of its own
        quoted = quotable.get(m.reply_to_message_id) if m.reply_to_message_id else None
        items.append(
            {
                "id": str(m.id),
                "direction": m.direction,
                "sender_type": m.sender_type,
                "body": None if m.deleted else m.body,
                "media_url": None if m.deleted else media_urls.get(m.id, m.media_url),
                "media_type": None if m.deleted else m.media_type,
                # The name an agent's document was sent under (None for inbound media).
                "filename": None if m.deleted else (m.provider_metadata or {}).get("filename"),
                "content_type": m.content_type,
                "status": m.status,
                "edited": bool(m.edited),
                "deleted": bool(m.deleted),
                "created_at": m.created_at.isoformat(),
                "reply_to": _present_quote(m, quoted),
                "reactions": [e for e in (reactions.get(m.id) or {}).values() if e],
                # What WE reacted with, so the menu can offer to withdraw it.
                "my_reaction": (reactions.get(m.id) or {}).get("outbound") or "",
            }
        )
    return items


def _provider_order(m) -> tuple:
    raw = ((m.payload or {}).get("raw") or {}).get("timestamp")
    try:
        provider_time = int(raw)
    except (TypeError, ValueError):
        provider_time = 0
    return (m.created_at, provider_time)


def _present_quote(m, quoted) -> dict | None:
    """The quoted message a reply shows above its text, or None if not a reply."""
    if quoted is None:
        # We never stored the target (older than our history): keep the fact it
        # was a reply so the client can draw an unavailable-quote placeholder.
        if (m.provider_metadata or {}).get("reply_to_provider_id") and m.content_type != "reaction":
            return {"id": None, "available": False}
        return None
    return {
        "id": str(quoted.id),
        "available": not quoted.deleted,
        "direction": quoted.direction,
        "content_type": quoted.content_type,
        "body": None if quoted.deleted else (quoted.body or "")[:200],
    }


@router.post("/conversations/{conversation_id}/media", status_code=201)
async def upload_media(
    conversation_id: uuid.UUID,
    request: Request,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Store a file an agent is about to send. The raw file is the request body.

    The response carries a ``media_id``; the send request names it. Nothing
    reaches the customer from here.
    """
    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
    await _ensure_channel_send(ctx, conversation)
    if conversation.channel != "whatsapp":
        raise ValidationError("sending files is only available on WhatsApp conversations")
    if conversation.status == "closed":
        raise ConflictError("conversation is closed")

    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > ABSOLUTE_MAX_BYTES:
            raise ValidationError(
                "the file is too large to send on WhatsApp",
                details={"reason": "too_large", "max_bytes": ABSOLUTE_MAX_BYTES},
            )
    spec = check_outbound_media(
        content_type=request.headers.get("content-type"),
        data=bytes(chunks),
        filename=_decoded_filename(request.headers.get("x-filename")),
        as_sticker=request.headers.get("x-as-sticker", "").lower() == "true",
    )
    attachment = await OutboundMediaService.store_upload(
        ctx.session, ctx.tenant_id, conversation_id=conversation_id, spec=spec, data=bytes(chunks)
    )
    return {
        "media_id": str(attachment.id),
        "kind": spec.kind,
        "content_type": spec.mime,
        "size": spec.size,
        "filename": spec.filename,
    }


def _decoded_filename(raw: str | None) -> str | None:
    """The browser percent-encodes the name so a non-ASCII one survives a header."""
    from urllib.parse import unquote

    return unquote(raw) if raw else None


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    from app.core.events.writer import add_outbox_event

    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
    await _ensure_channel_send(ctx, conversation)
    if conversation.status == "closed":
        raise ConflictError("conversation is closed")
    if not body.body and not body.template_name and body.media_id is None:
        raise ValidationError("message needs body, media_id or template_name")
    if body.media_id is not None and body.template_name:
        raise ValidationError("a template cannot carry an uploaded file")
    if body.reply_to_message_id is not None:
        # The quoted message must belong to THIS conversation. Anything else is
        # reported as not found, so the answer never confirms that a message
        # exists in some other customer's conversation.
        from sqlalchemy import select as _select

        from app.modules.conversations.models import Message as _Message

        found = (
            await ctx.session.execute(
                _select(_Message.id).where(
                    _Message.tenant_id == ctx.tenant_id,
                    _Message.conversation_id == conversation_id,
                    _Message.id == body.reply_to_message_id,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise NotFoundError("quoted message not found")

    media = None
    caption = body.body
    media_kwargs: dict = {}
    if body.media_id is not None:
        media = await OutboundMediaService.claim(
            ctx.session, ctx.tenant_id, media_id=body.media_id, conversation_id=conversation_id
        )
        kind = media.kind or "document"
        caption = check_caption(kind, body.body)
        media_kwargs = {
            "media_url": f"s3://{media.storage_key}",
            "media_type": kind,
            "content_type": content_type_for(kind),
            "provider_metadata": {"filename": media.filename},
        }

    # The policy decision lives in ConversationService.add_message so that the
    # AI, automation and campaigns are bound by exactly the same rule.
    message = await ConversationService.add_message(
        ctx.session,
        ctx.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        sender_type="agent",
        body=caption,
        sender_user_id=ctx.user.id,
        template_name=body.template_name,
        template_vars=body.template_vars,
        reply_to_message_id=body.reply_to_message_id,
        **media_kwargs,
    )
    if media is not None:
        await OutboundMediaService.attach(ctx.session, media, message)
    await add_outbox_event(
        ctx.session,
        aggregate_type="message",
        aggregate_id=message.id,
        event_type="message.outbound",
        tenant_id=ctx.tenant_id,
        payload={"message_id": str(message.id), "conversation_id": str(conversation_id)},
    )
    return {"id": str(message.id), "status": message.status}


@router.post("/conversations/{conversation_id}/messages/{message_id}/reaction", status_code=201)
async def react_to_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    body: ReactionRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """React to a message with an emoji (an empty emoji withdraws ours).

    It travels as a message of its own (queued, sent by the worker) so it gets the
    same channel policy, access checks and delivery tracking as any other send.
    """
    from sqlalchemy import select as _select

    from app.core.events.writer import add_outbox_event
    from app.modules.conversations.models import Message as _Message

    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
    await _ensure_channel_send(ctx, conversation)
    if conversation.status == "closed":
        raise ConflictError("conversation is closed")
    if conversation.channel != "whatsapp":
        raise ValidationError("reactions are only supported on WhatsApp")
    emoji = body.emoji.strip()
    if any(ch.isspace() for ch in emoji) or any(ch.isalnum() and ch.isascii() for ch in emoji):
        raise ValidationError("reaction must be a single emoji")

    target = (
        await ctx.session.execute(
            _select(_Message).where(
                _Message.tenant_id == ctx.tenant_id,
                _Message.conversation_id == conversation_id,
                _Message.id == message_id,
            )
        )
    ).scalar_one_or_none()
    # A reaction to another conversation's message is reported as not found, the
    # same answer as a message that does not exist.
    if target is None:
        raise NotFoundError("message not found")
    if target.deleted or target.content_type == "reaction" or not target.channel_message_id:
        raise ConflictError("this message cannot be reacted to")

    message = await ConversationService.add_message(
        ctx.session,
        ctx.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        sender_type="agent",
        body=emoji or REACTION_REMOVED,
        sender_user_id=ctx.user.id,
        content_type="reaction",
        reply_to_message_id=target.id,
    )
    await add_outbox_event(
        ctx.session,
        aggregate_type="message",
        aggregate_id=message.id,
        event_type="message.outbound",
        tenant_id=ctx.tenant_id,
        payload={"message_id": str(message.id), "conversation_id": str(conversation_id)},
    )
    return {"id": str(message.id), "target_id": str(target.id), "emoji": emoji}


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
    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
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
    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
    await ConversationService.close(ctx.session, ctx.tenant_id, conversation_id)
    await ConversationService.audit(
        ctx.session, ctx.tenant_id, ctx.user.id, "conversation.closed", str(conversation_id)
    )
    return {"ok": True}


_MUTE_FOR = {"8h": timedelta(hours=8), "1w": timedelta(weeks=1)}


@router.post("/conversations/{conversation_id}/list-state")
async def set_list_state(
    conversation_id: uuid.UUID,
    body: ListStateRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Pin, mute, archive or mark a conversation unread, for the whole store.

    These are inbox-only flags. Nothing is sent to the channel provider.
    """
    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
    muted_until: datetime | None | str = "keep"
    if body.mute == "off":
        muted_until = None
    elif body.mute == "always":
        muted_until = ConversationService.MUTE_ALWAYS
    elif body.mute in _MUTE_FOR:
        muted_until = datetime.now(UTC) + _MUTE_FOR[body.mute]
    updated = await ConversationService.set_list_state(
        ctx.session,
        ctx.tenant_id,
        conversation_id,
        pinned=body.pinned,
        archived=body.archived,
        marked_unread=body.marked_unread,
        muted_until=muted_until,
    )
    await ConversationService.audit(
        ctx.session, ctx.tenant_id, ctx.user.id, "conversation.list_state", str(conversation_id)
    )
    return {
        "id": str(updated.id),
        "pinned_at": updated.pinned_at.isoformat() if updated.pinned_at else None,
        "muted_until": updated.muted_until.isoformat() if updated.muted_until else None,
        "archived_at": updated.archived_at.isoformat() if updated.archived_at else None,
        "marked_unread": bool(updated.marked_unread),
    }


@router.post("/conversations/{conversation_id}/read")
async def mark_read(ctx: TenantCtxDep, conversation_id: uuid.UUID):
    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
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

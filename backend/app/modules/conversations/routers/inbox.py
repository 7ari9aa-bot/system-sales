"""Staff inbox and conversation management routes."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.applications.dependencies import workspace_gate
from app.modules.conversations.gateway.instagram_limits import InstagramLimitError, check_upload
from app.modules.conversations.gateway.messenger_media import (
    SENDABLE_REACTIONS,
    MessengerLimitError,
)
from app.modules.conversations.gateway.messenger_media import (
    check_upload as messenger_check_upload,
)
from app.modules.conversations.gateway.telegram_media import (
    TelegramLimitError,
)
from app.modules.conversations.gateway.telegram_media import (
    check_upload as telegram_check_upload,
)
from app.modules.conversations.gateway.whatsapp import REACTION_REMOVED
from app.modules.conversations.inbox import InboxQuery, decode_keyset
from app.modules.conversations.outbound_media import (
    ABSOLUTE_MAX_BYTES,
    OutboundMediaSpec,
    check_caption,
    check_outbound_media,
    content_type_for,
    safe_filename,
)
from app.modules.conversations.outbound_media_service import OutboundMediaService
from app.modules.conversations.routers._deps import (
    AssignRequest,
    ListStateRequest,
    ReactionRequest,
    ReadSignalRequest,
    SendMessageRequest,
    TenantContext,
    TenantCtxDep,
    _inbox_page,
    _redact_inbox_item,
    require_permission,
)
from app.modules.conversations.service import ConversationService
from app.modules.identity.deps import get_tenant_ctx
from app.modules.platform.services import channel_access as _channel_access

logger = logging.getLogger(__name__)

_FILE_CHANNELS = ("whatsapp", "instagram", "messenger", "telegram")

async def _inbox_gate(ctx: TenantContext = Depends(get_tenant_ctx)):
    """The inbox is the engagement product's front door."""
    return await workspace_gate("customer.engagement", ctx)


router = APIRouter(tags=["inbox"], dependencies=[Depends(_inbox_gate)])


async def _allowed_channels(ctx: TenantContext) -> set[str] | None:
    return await _channel_access.allowed_providers(
        ctx.session, ctx.tenant_id, ctx.user.id, ctx.role_code
    )


async def _sendable_channels(ctx: TenantContext) -> set[str] | None:
    """Providers this user may SEND on — the stricter can_send grant."""
    return await _channel_access.sendable_providers(
        ctx.session, ctx.tenant_id, ctx.user.id, ctx.role_code
    )


async def _channel_config(ctx: TenantContext, provider: str) -> dict | None:
    """The tenant's saved credentials for one connected channel (None when not connected)."""
    return await _channel_access.channel_credentials_config(ctx.session, ctx.tenant_id, provider)


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
                # Where an OUTBOUND message came from: "whatsapp_business_app" for a reply the
                # merchant typed on their phone (an echo), "whatsapp_history" for one imported
                # from the app's own log, None for anything sent here. The bubble labels it, so
                # a human reply from the phone is never drawn as the AI's.
                "source": _message_source(m),
                "body": None if m.deleted else m.body,
                "media_url": None if m.deleted else media_urls.get(m.id, m.media_url),
                "media_type": None if m.deleted else m.media_type,
                # The name an agent's document was sent under (None for inbound media).
                "filename": None if m.deleted else (m.provider_metadata or {}).get("filename"),
                "content_type": m.content_type,
                "card": None if m.deleted else _present_card(m),
                "status": m.status,
                "edited": bool(m.edited),
                "deleted": bool(m.deleted),
                "created_at": m.created_at.isoformat(),
                "reply_to": _present_quote(m, quoted),
                "reactions": [e for e in (reactions.get(m.id) or {}).values() if e],
                # What WE reacted with, so the menu can offer to withdraw it.
                "my_reaction": (reactions.get(m.id) or {}).get("outbound") or "",
                # The tap-to-reply buttons we sent under this message (Instagram).
                "quick_replies": [] if m.deleted else _quick_replies(m),
                # The buttons / list / link button we sent (WhatsApp), for the bubble to draw.
                "interactive": None if m.deleted else _present_interactive(m),
                # A cart the customer sent from the catalog (WhatsApp): products and quantities.
                "order": None if m.deleted else _present_order(m),
                # The structured half of a WhatsApp message: a place with coordinates, a contact
                # card, or the id of the option the customer tapped. The body keeps the one-line
                # text the list needs; this is what a map, a card or a bot routes on.
                "structured": None if m.deleted else _present_structured(m),
            }
        )
    return items


def _message_source(m) -> str | None:
    """The import origin stamped on a message, or None for a live one."""
    meta = m.provider_metadata if isinstance(m.provider_metadata, dict) else {}
    source = meta.get("imported_from")
    if not isinstance(source, str):
        return None
    return source.strip() or None


_CARD_KEYS = ("share", "story_reply", "story_mention")


def _present_interactive(m) -> dict | None:
    """The interactive message we sent, rebuilt and checked, or None.

    Never the stored dict as-is: it is run through the same builder that produced what Meta got,
    so the browser only ever sees a checked shape, and a row whose spec no longer passes (a rule
    that tightened since) shows its plain text instead of failing the whole conversation.
    """
    spec = (m.provider_metadata or {}).get("interactive")
    if not spec or m.direction != "outbound":
        return None
    from app.modules.conversations.gateway.whatsapp_interactive import build_interactive

    try:
        return build_interactive(spec)
    except ValidationError:
        return None


def _present_order(m) -> dict | None:
    """The cart a customer sent, re-read through the same checker that produced its summary.

    The stored webhook body never leaves as-is: only the checked shape does, so a hostile or
    broken payload cannot put anything else on the agent's screen. Customer messages only.
    """
    if m.content_type != "order" or m.direction != "inbound":
        return None
    payload = m.payload if isinstance(m.payload, dict) else {}
    from app.modules.conversations.gateway.whatsapp_order import parse_order

    return parse_order(payload.get("raw"))


def _present_structured(m) -> dict | None:
    """The checked structured payload of a WhatsApp message, or None.

    Rebuilt from the stored webhook body at read time, so a row written before this existed still
    shows its map pin or its contact card, and a row whose payload no longer passes (a shape Meta
    changed) falls back to its plain text instead of failing the thread.
    """
    if m.direction != "inbound":
        return None
    payload = m.payload if isinstance(m.payload, dict) else {}
    from app.modules.conversations.gateway.whatsapp_structured import structured_payload

    return structured_payload(str(m.content_type or ""), payload.get("raw"))


def _quick_replies(m) -> list[str]:
    raw = (m.provider_metadata or {}).get("instagram_quick_replies")
    return [t for t in raw if isinstance(t, str)] if isinstance(raw, list) else []


def _present_card(m) -> dict | None:
    """The shared post, the story someone replied to, the story that mentioned us, or the ad.

    Instagram sends these as links, not files. Only the known shapes leave here, with a web link
    (https) and a short title: the raw webhook body never reaches the browser. A Click-to-Messenger
    / Click-to-Direct referral rides the same field, because it is the same kind of thing — context
    about how the thread started, not a message the customer wrote.
    """
    referral = _present_referral(m)
    if referral is not None:
        return referral
    payload = m.payload if isinstance(m.payload, dict) else {}
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    ig = raw.get("_ig") if isinstance(raw.get("_ig"), dict) else {}
    for key in _CARD_KEYS:
        data = ig.get(key)
        if isinstance(
            data, str
        ):  # a reply-to-story arrives as {"story": {"url": ...}} or a bare url
            data = {"url": data}
        if not isinstance(data, dict):
            continue
        url = data.get("url")
        url = url if isinstance(url, str) and url.startswith("https://") else None
        title = data.get("title")
        title = title[:200] if isinstance(title, str) and title.strip() else None
        kind = data.get("kind") if key == "share" and isinstance(data.get("kind"), str) else key
        return {"type": key, "kind": kind, "url": url, "title": title}
    return None


def _provider_order(m) -> tuple:
    raw = ((m.payload or {}).get("raw") or {}).get("timestamp")
    try:
        provider_time = int(raw)
    except (TypeError, ValueError):
        provider_time = 0
    return (m.created_at, provider_time)


def _present_referral(m) -> dict | None:
    """The ad or m.me link that started the conversation, as a card, or None.

    `_referral_details` already checked the shape when the message was ingested; this reads the
    stored copy and keeps only printable strings, so an old row written before that check existed
    cannot put anything odd on the screen either.
    """
    stored = (getattr(m, "provider_metadata", None) or {}).get("referral")
    if not isinstance(stored, dict) or not stored:
        return None
    fields = {
        name: stored[name][:255]
        for name in ("source", "type", "ref", "ad_id", "ref_source", "headline")
        if isinstance(stored.get(name), str) and stored[name].strip()
    }
    if not fields:
        return None
    return {
        "type": "referral",
        "kind": "ad" if str(fields.get("source") or "").upper() == "ADS" else "link",
        "url": None,
        "title": fields.get("headline") or fields.get("ref") or fields.get("source"),
        **fields,
    }


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
    if conversation.channel not in _FILE_CHANNELS:
        raise ValidationError(
            "sending files is only available on WhatsApp, Instagram, Messenger and Telegram"
        )
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
    if conversation.channel == "instagram":
        # Instagram has its own formats and sizes (jpg/png only, pdf only, 8 MB per image):
        # WhatsApp's rules would let through files Instagram then refuses.
        try:
            ig = check_upload(request.headers.get("content-type"), bytes(chunks))
        except InstagramLimitError as exc:
            raise ValidationError(str(exc), details={"reason": exc.code}) from exc
        spec = OutboundMediaSpec(
            mime=ig.mime,
            # The inbox calls a PDF a "document"; Instagram's Send API calls it a "file".
            kind="document" if ig.kind == "file" else ig.kind,
            size=ig.size,
            filename=safe_filename(_decoded_filename(request.headers.get("x-filename"))),
        )
    elif conversation.channel in ("messenger", "telegram"):
        # Each has its own formats and sizes, and a file it would refuse must fail here, while
        # the agent can still pick another, not after it was "sent".
        check = (
            messenger_check_upload if conversation.channel == "messenger" else telegram_check_upload
        )
        try:
            up = check(request.headers.get("content-type"), bytes(chunks))
        except (MessengerLimitError, TelegramLimitError) as exc:
            raise ValidationError(str(exc), details={"reason": exc.code}) from exc
        spec = OutboundMediaSpec(
            mime=up.mime,
            # The inbox calls a Messenger "file" a "document".
            kind="document" if up.kind == "file" else up.kind,
            size=up.size,
            filename=safe_filename(_decoded_filename(request.headers.get("x-filename"))),
        )
    else:
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
    instagram_extra = body.instagram_heart or bool(body.instagram_share_post_id)
    if instagram_extra:
        if conversation.channel != "instagram":
            raise ValidationError("a heart or a shared post can only be sent on Instagram")
        if body.instagram_heart and body.instagram_share_post_id:
            raise ValidationError("send either a heart or a post, not both")
        if body.body or body.template_name or body.media_id is not None:
            raise ValidationError("a heart or a shared post carries nothing else")
    quick_replies = [t.strip() for t in (body.instagram_quick_replies or []) if t and t.strip()]
    if body.instagram_quick_replies is not None:
        if conversation.channel != "instagram":
            raise ValidationError("quick replies can only be sent on Instagram")
        if not quick_replies:
            raise ValidationError("a quick reply needs a title")
        if not body.body or body.media_id is not None or body.template_name or instagram_extra:
            raise ValidationError("quick replies go under a plain text message")
        if any(len(t) > 20 for t in quick_replies):
            raise ValidationError("a quick reply is at most 20 characters")
        if len(set(quick_replies)) != len(quick_replies):
            raise ValidationError("quick replies must be different from each other")
    interactive_text: str | None = None
    if body.interactive is not None:
        if conversation.channel != "whatsapp":
            raise ValidationError("buttons and lists can only be sent on WhatsApp")
        if body.template_name or body.media_id is not None or instagram_extra or quick_replies:
            raise ValidationError("an interactive message carries nothing else")
        # Its text lives in the spec; a separate `body` would be silently ignored.
        if body.body:
            raise ValidationError("write the text inside the interactive message, not beside it")
        from app.modules.conversations.gateway.whatsapp_interactive import preview_text

        interactive_text = preview_text(body.interactive)  # raises, naming the bad field
    if (
        not body.body
        and not body.template_name
        and body.media_id is None
        and not instagram_extra
        and interactive_text is None
    ):
        raise ValidationError("message needs body, media_id or template_name")
    if body.media_id is not None and body.template_name:
        raise ValidationError("a template cannot carry an uploaded file")
    if body.media_id is not None and conversation.channel == "instagram" and body.body:
        # An Instagram attachment is a message of its own: text beside it would be dropped
        # without a word, so it is refused. The text goes as its own message.
        raise ValidationError(
            "an Instagram file cannot have a caption; send the text as its own message",
            details={"reason": "caption_not_allowed"},
        )
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
    if body.instagram_heart:
        # Stored like an incoming heart (a sticker holding the heart): both look the same.
        caption = "\u2764\ufe0f"
        media_kwargs = {"content_type": "sticker", "provider_metadata": {"instagram_heart": True}}
    elif body.instagram_share_post_id:
        post_id = body.instagram_share_post_id.strip()
        if not post_id.isdigit():
            raise ValidationError("not an Instagram post id")
        caption = None
        media_kwargs = {
            "content_type": "share",
            "provider_metadata": {"instagram_share_post_id": post_id},
        }
    elif quick_replies:
        media_kwargs = {"provider_metadata": {"instagram_quick_replies": quick_replies}}
    elif interactive_text is not None:
        caption = interactive_text
        media_kwargs = {
            "content_type": "interactive",
            "provider_metadata": {"interactive": body.interactive},
        }
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
            # The size travels with the message so the send worker can check it against the
            # channel's limit (an Instagram signed link has no file extension to read it from).
            "provider_metadata": {"filename": media.filename, "media_size_bytes": media.size},
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
    if conversation.channel not in ("whatsapp", "instagram", "messenger"):
        raise ValidationError("reactions are only supported on WhatsApp, Instagram and Messenger")
    emoji = body.emoji.strip()
    if any(ch.isspace() for ch in emoji) or any(ch.isalnum() and ch.isascii() for ch in emoji):
        raise ValidationError("reaction must be a single emoji")
    if conversation.channel == "messenger" and emoji and emoji not in SENDABLE_REACTIONS:
        # Messenger takes a reaction as a sender action naming one of its six emoji, and Meta
        # refuses any other with an error. Refuse it here, with a message the agent can read.
        raise ValidationError("Messenger only accepts its own six reaction emoji")
    if conversation.channel == "instagram" and emoji and emoji not in ("\u2764\ufe0f", "\u2764"):
        # Instagram's Send API lets a business react with the heart only.
        raise ValidationError("Instagram only lets a business react with a heart")

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


@router.post("/conversations/{conversation_id}/read-signal")
async def send_read_signal(
    conversation_id: uuid.UUID,
    body: ReadSignalRequest,
    ctx: TenantContext = Depends(require_permission("conversations:write")),
):
    """Show the customer we read their chat (blue ticks, Seen) and, while we type, "typing…".

    WhatsApp and Instagram.

    This is separate from ``/read``, which only clears OUR unread badge. It needs
    the same rights as sending, because the customer sees it as the business acting.
    A failure is reported as ``sent: false`` and never raised: it is a courtesy.
    """
    from app.modules.conversations.read_signal_service import ReadSignalService

    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
    await _ensure_channel_send(ctx, conversation)
    result = await ReadSignalService.send(
        ctx.session,
        ctx.tenant_id,
        conversation,
        typing=body.typing,
        load_channel_config=lambda: _channel_access.channel_credentials_config(
            ctx.session, ctx.tenant_id, conversation.channel
        ),
    )
    return {"sent": result.sent, "skipped": result.skipped}


@router.post("/conversations/{conversation_id}/refresh-profile")
async def refresh_customer_profile(
    conversation_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("conversations:read")),
):
    """Learn who an Instagram or Messenger customer is (name, photo) when the chat shows a number.

    Meant to be called in the background when a chat row is a bare number or has no photo. It is
    rate-limited by what is already known (a week after a success, six hours after a refusal),
    never raises for a refusal, and does not touch the webhook or the message pipeline.
    """
    from app.modules.conversations.customer_profile import CustomerProfileService

    conversation = await ConversationService.get(ctx.session, ctx.tenant_id, conversation_id)
    await _ensure_channel_access(ctx, conversation)
    if conversation.channel not in ("instagram", "messenger") or conversation.customer_id is None:
        return {"updated": False, "reason": "not_supported_channel"}
    channel = conversation.channel
    config = await _channel_access.channel_credentials_config(ctx.session, ctx.tenant_id, channel)
    if not config or not config.get("api_key"):
        return {"updated": False, "reason": "not_connected"}
    enrich = (
        CustomerProfileService.enrich_messenger_for
        if channel == "messenger"
        else CustomerProfileService.enrich_instagram_for
    )
    updated = await enrich(ctx.session, ctx.tenant_id, conversation.customer_id, config)
    if updated is None:
        return {"updated": False, "reason": "no_customer"}
    return {"updated": updated}


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

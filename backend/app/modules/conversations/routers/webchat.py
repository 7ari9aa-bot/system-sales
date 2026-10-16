"""Public webchat visitor routes."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.routers._deps import DbSession
from app.modules.conversations.service import ConversationService

logger = logging.getLogger(__name__)

public_router = APIRouter(tags=["channels"])


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


@public_router.get("/webchat/{public_key}/messages")
async def webchat_list_messages(
    public_key: str,
    request: Request,
    session: DbSession,
    session_token: Annotated[str | None, Query(max_length=4096)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    after: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """Retrieve or poll messages for a webchat visitor conversation."""
    from app.core.db import bind_tenant
    from app.core.security import decode_visitor_token

    adapter = get_adapter("webchat")
    if adapter is None:
        raise NotFoundError("webchat disabled")
    tenant_id = await IngestService.resolve_tenant(session, "webchat", public_key)
    if tenant_id is None:
        raise NotFoundError("unknown widget key")

    token = session_token or request.headers.get("x-session-token")
    if not token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if not token:
        raise ValidationError("session_token required to fetch webchat messages")

    claims = decode_visitor_token(token)
    if claims.get("tenant_id") != str(tenant_id):
        raise PermissionDeniedError("visitor session belongs to another tenant")
    if claims.get("widget") != public_key:
        raise PermissionDeniedError("visitor session belongs to another widget")
    session_key = str(claims["sub"])

    await bind_tenant(session, tenant_id)

    conversation = await ConversationService.find_webchat_conversation(
        session, tenant_id, session_key
    )
    if conversation is None:
        return {"items": [], "next_cursor": None, "has_more": False}

    after_created_at, after_id = decode_cursor(after) if after else (None, None)
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)

    if after is not None:
        rows = await ConversationService.list_messages(
            session,
            tenant_id,
            conversation.id,
            limit=limit + 1,
            after_created_at=after_created_at,
            after_id=after_id,
        )
        has_more = len(rows) > limit
        items_to_show = rows[:limit]
        next_cursor = (
            encode_cursor(items_to_show[-1].created_at, items_to_show[-1].id)
            if items_to_show
            else after
        )
    else:
        rows = await ConversationService.list_messages(
            session,
            tenant_id,
            conversation.id,
            limit=limit + 1,
            before_created_at=before_created_at,
            before_id=before_id,
        )
        has_more = len(rows) > limit
        if has_more:
            items_to_show = rows[1:]
        else:
            items_to_show = rows
        next_cursor = (
            encode_cursor(items_to_show[-1].created_at, items_to_show[-1].id)
            if items_to_show
            else None
        )

    storage_keys = await ConversationService.attachment_storage_keys(
        session, tenant_id, [message.id for message in items_to_show]
    )
    media_urls: dict[uuid.UUID, str | None] = {}
    if storage_keys:
        from app.core.storage import get_storage

        storage = get_storage()
        for message_id, key in storage_keys.items():
            try:
                media_urls[message_id] = storage.signed_url(key)
            except Exception:
                logger.exception(
                    "media.signed_url_failed tenant=%s message=%s",
                    tenant_id,
                    message_id,
                )
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
                "content_type": m.content_type,
                "created_at": m.created_at.isoformat(),
            }
            for m in items_to_show
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }

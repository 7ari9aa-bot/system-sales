"""Real-time SSE feed of inbox state changes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.core.errors import PermissionDeniedError
from app.core.security import decode_token
from app.modules.conversations.routers._deps import AuthedUser, tenant_may_use_api

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inbox"])


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

    from app.core.db import SessionLocal

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
    user = await _stream_auth(request, token)

    async def event_stream():
        last_digest = None
        started = time.monotonic()
        try:
            while time.monotonic() - started < 300:  # recycle every 5 minutes
                if await request.is_disconnected():
                    return
                from sqlalchemy import select as sa_select

                from app.core.db import SessionLocal, bind_tenant
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

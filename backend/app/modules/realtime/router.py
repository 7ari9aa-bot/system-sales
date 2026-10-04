"""Realtime — Server-Sent Events gateway (§60, §149).

Architecture rules:
- SSE is READ-ONLY: the client never pushes data through this channel.
- Tenant isolation is DOUBLE-enforced: JWT claim + per-message tenant check.
- The gateway reads from Redis Streams (same streams the outbox relay writes).
  No event is created here; the gateway only fans-out what the domain already
  committed.
- The client reconnects with ?cursor=<last_id> to resume without missing events.
  The stream ID format is "<milliseconds>-<seq>" (Redis XREAD ID).
- Events are scoped to the authenticated user's tenant.

Streams consumed (default: all):
  message.events        – new messages, status changes
  conversation.events   – status / assignment changes
  notification.events   – in-app notifications
  order.events          – order status changes

Response format (text/event-stream):
  id:   <redis-stream-id>
  data: <json>
  (blank line)

Heartbeat (every 25 s) keeps the TCP connection alive through load balancers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy import text as sa_text

from app.core.errors import PermissionDeniedError, ValidationError
from app.core.events.schemas import deserialize
from app.core.redis import get_redis
from app.core.security import STREAM_TOKEN_TTL_SECONDS, create_stream_token, decode_token
from app.modules.identity.deps import AuthedUser, CurrentUserDep, tenant_may_use_api
from app.modules.identity.models import Tenant, TenantUser, User


async def _sse_auth(
    request: Request,
    token: Annotated[
        str | None,
        Query(description="Access token (SSE fallback — browsers can't send headers)"),
    ] = None,
) -> AuthedUser:
    """SSE-compatible auth: accepts ?token= query param OR Authorization: Bearer.

    EventSource (browser) cannot send custom headers, so the frontend passes
    the access token as ?token=.  Regular Bearer header still works (e.g. tests).

    S9: this endpoint used to validate the JWT signature and nothing else — it
    never checked that the user still exists, is still active, or is still a
    member of the tenant whose events it is about to stream. A removed or
    deactivated user kept a live firehose of that tenant's message bodies for
    the whole token lifetime.

    This deliberately opens its OWN short-lived session rather than taking the
    request-scoped `DbSession`: FastAPI tears dependency generators down only
    AFTER the response completes, so a request-scoped session would pin a
    pooled connection for the entire lifetime of the stream (hours) — a handful
    of open inboxes would exhaust the pool for the whole platform (the same
    failure class as R4).
    """
    # Try Authorization header first (standard Bearer)
    auth_header = request.headers.get("authorization", "")
    via_query = False
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header.split(" ", 1)[1].strip()
    elif token:
        raw_token = token
        via_query = True
    else:
        raise PermissionDeniedError("missing bearer token")

    try:
        payload = decode_token(raw_token)
        if via_query:
            # SEC-1 / ADR-059 R5: the query fallback carries ONLY the
            # short-lived stream-scoped credential now. An access token in a
            # URL is a replayable credential sitting in access logs, referrer
            # headers and proxy caches for its whole lifetime.
            if payload.get("type") != "stream":
                raise PermissionDeniedError(
                    "query tokens must be stream-scoped; mint one at "
                    "POST /api/v1/realtime/stream-token"
                )
        elif payload.get("type") != "access":
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

            # §48 (review N-09): the request path, the auth path and the workers
            # all read `lifecycle_state`; this endpoint did not — so a suspended
            # workspace kept a live firehose of its own events while every
            # ordinary request was refused. Checked AFTER membership so the state
            # is never disclosed to a non-member.
            lifecycle_state = (
                await session.execute(
                    sa_select(Tenant.lifecycle_state).where(Tenant.id == tenant_id)
                )
            ).scalar_one_or_none()
            if lifecycle_state is None:
                raise PermissionDeniedError("tenant not found")
            if not tenant_may_use_api(lifecycle_state):
                raise PermissionDeniedError(
                    f"workspace is {lifecycle_state} — realtime is unavailable"
                )

    return AuthedUser(id=user_id, tenant_id=tenant_id, role_code=payload.get("role"))


_SSEAuthDep = Annotated[AuthedUser, Depends(_sse_auth)]

logger = logging.getLogger(__name__)


async def _tenant_may_stream(tenant_id: str) -> bool:
    """Re-read the workspace state mid-stream (review N-09).

    A stream outlives the request that opened it, so a connect-time check alone
    leaves open exactly the window that matters: a workspace suspended WHILE its
    inbox is open. The re-check rides the existing heartbeat cadence, so it costs
    one indexed lookup per stream per `_HEARTBEAT_INTERVAL_S`.

    A transient failure keeps the stream alive and is logged loudly. This is a
    LIFECYCLE gate, not the isolation gate — isolation is enforced per frame from
    each event's own meta envelope — so the worst case of staying open is a
    suspended workspace receiving a few more of its OWN events, whereas failing
    closed would drop every stream on the platform over a blip.
    """
    from app.core.db import SessionLocal

    try:
        async with SessionLocal() as session:
            async with session.begin():
                state = (
                    await session.execute(
                        sa_select(Tenant.lifecycle_state).where(
                            Tenant.id == uuid.UUID(tenant_id)
                        )
                    )
                ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        logger.warning("sse.lifecycle_check_failed tenant=%s", tenant_id, exc_info=True)
        return True
    return tenant_may_use_api(state)

router = APIRouter(prefix="/realtime", tags=["realtime"])


class StreamTokenOut(BaseModel):
    stream_token: str
    expires_in: int


@router.post("/stream-token", response_model=StreamTokenOut)
async def mint_stream_token(user: CurrentUserDep) -> StreamTokenOut:
    """SEC-1 / ADR-059 R5: mint the credential the ?token= fallback accepts.

    Every other surface authenticates with the access token in the
    Authorization header. Only the browser EventSource path — which cannot
    send headers — needs a URL token, and a URL token must not be a
    30-minute replayable access credential. Five minutes, stream-only,
    bound to the caller's own tenant.
    """
    if not user.tenant_id:
        raise PermissionDeniedError("stream tokens require a tenant context")
    return StreamTokenOut(
        stream_token=create_stream_token(
            str(user.id), str(user.tenant_id), auth_version=user.auth_version
        ),
        expires_in=STREAM_TOKEN_TTL_SECONDS,
    )

# Streams the gateway fans-out.  Extend as new domain streams are added.
_ALL_STREAMS = [
    "message.events",
    "conversation.events",
    "notification.events",
    "order.events",
]

_HEARTBEAT_INTERVAL_S = 25   # seconds
_BLOCK_MS = 5_000             # Redis XREAD block timeout per poll
_MAX_PER_POLL = 50
# A client cursor older than this is clamped: `?cursor=0-0` must never replay
# the whole retained stream (cross-tenant history exfiltration risk).
_CURSOR_CLAMP_MS = 60_000


def _sse_frame(data: dict, *, event_id: str) -> bytes:
    """Encode one SSE data frame (id + data + blank line)."""
    payload = json.dumps(data, default=str)
    return f"id: {event_id}\ndata: {payload}\n\n".encode()


def _heartbeat() -> bytes:
    return b": heartbeat\n\n"


async def _build_cursor(cursor: str | None, streams: list[str]) -> dict[str, str]:
    """Translate a client cursor into per-stream XREAD start IDs (clamped).

    Redis stream IDs carry epoch milliseconds, so the clamp floor is computed
    from the wall clock: a cursor older than _CURSOR_CLAMP_MS is pulled up to
    the floor instead of replaying the entire retained stream.
    """
    floor_ms = int(time.time() * 1000) - _CURSOR_CLAMP_MS
    floor_id = f"{floor_ms}-0"
    if cursor:
        try:
            ms, seq = cursor.rsplit("-", 1)
            int(seq)  # reject a malformed cursor the same way as before
            # XREAD is ALREADY exclusive of the id it is given — the client's
            # cursor IS the last id it saw, so it is passed through unchanged.
            # Bumping the sequence here skipped the very next entry whenever
            # the two shared a millisecond (a burst is several events per ms),
            # so every reconnect silently dropped events (§149).
            next_id = cursor
            # Compare numerically on the ms component — "9" < "10" lexically.
            if int(ms) < floor_ms:
                next_id = floor_id
            return {s: next_id for s in streams}
        except (ValueError, AttributeError):
            pass
    # No cursor → start from "now" (only events after the connection opens).
    return {s: "$" for s in streams}


async def _event_stream(
    tenant_id: str,
    user_id: str,
    streams: list[str],
    cursor: str | None,
    request: Request,
) -> AsyncIterator[bytes]:
    """Core generator — reads Redis Streams and fans out to the SSE client."""
    redis = get_redis()
    last_ids = await _build_cursor(cursor, streams)
    heartbeat_due = asyncio.get_event_loop().time() + _HEARTBEAT_INTERVAL_S

    try:
        while True:
            # Respect client disconnect.
            if await request.is_disconnected():
                logger.debug("sse.disconnected user=%s", user_id)
                break

            now = asyncio.get_event_loop().time()
            time_to_heartbeat = max(0.0, heartbeat_due - now)
            block_ms = min(_BLOCK_MS, int(time_to_heartbeat * 1000))

            try:
                results = await asyncio.wait_for(
                    redis.xread(  # type: ignore[arg-type]
                        streams=last_ids,
                        count=_MAX_PER_POLL,
                        block=block_ms if block_ms > 0 else 1,
                    ),
                    timeout=(block_ms / 1000) + 3,
                )
            except TimeoutError:
                results = None
            except Exception as exc:  # noqa: BLE001
                logger.warning("sse.redis_error %s", exc)
                await asyncio.sleep(1)
                continue

            # Heartbeat if overdue. Also the point at which the workspace is
            # re-checked: a stream opened while the tenant was active must not
            # survive the tenant being suspended mid-session (review N-09).
            if asyncio.get_event_loop().time() >= heartbeat_due:
                if not await _tenant_may_stream(tenant_id):
                    logger.info("sse.tenant_blocked tenant=%s", tenant_id)
                    break
                yield _heartbeat()
                heartbeat_due = asyncio.get_event_loop().time() + _HEARTBEAT_INTERVAL_S

            if not results:
                continue

            for stream_name_raw, messages in results:
                stream_key = (
                    stream_name_raw.decode()
                    if isinstance(stream_name_raw, bytes)
                    else stream_name_raw
                )
                for msg_id_raw, fields in messages:
                    raw_id: str = (
                        msg_id_raw.decode()
                        if isinstance(msg_id_raw, bytes)
                        else msg_id_raw
                    )
                    last_ids[stream_key] = raw_id

                    # Decode payload AND meta — the outbox relay publishes
                    # them as two SEPARATE Redis fields (bus.py xadd), so the
                    # tenant claim lives in the meta field, not in the payload.
                    raw_payload = (
                        fields.get(b"payload")
                        or fields.get("payload")
                        or b"{}"
                    )
                    if isinstance(raw_payload, bytes):
                        raw_payload = raw_payload.decode()
                    raw_meta = fields.get(b"meta") or fields.get("meta") or b"{}"
                    if isinstance(raw_meta, bytes):
                        raw_meta = raw_meta.decode()

                    # Read the frame through the §19 envelope's read half so the
                    # gateway and the relay agree on field names and value types
                    # by construction (finding 2). A frame that is not a valid
                    # envelope is dropped — fail CLOSED.
                    try:
                        envelope = deserialize(
                            {"payload": raw_payload, "meta": raw_meta}
                        )
                    except (ValidationError, KeyError, TypeError, ValueError):
                        continue

                    # §149 Tenant isolation: fail CLOSED. The envelope carries
                    # the tenant claim; a missing or mismatched one never
                    # reaches a client.
                    if str(envelope.tenant_id) != tenant_id:
                        continue

                    yield _sse_frame(
                        {
                            "stream": stream_key,
                            "id": raw_id,
                            "payload": envelope.payload,
                        },
                        event_id=raw_id,
                    )

    except asyncio.CancelledError:
        logger.debug("sse.cancelled user=%s", user_id)
    except Exception:  # noqa: BLE001
        logger.exception("sse.fatal user=%s", user_id)


@router.get(
    "/events",
    summary="SSE stream — realtime domain events (§60, §149)",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}},
        401: {"description": "Unauthenticated"},
    },
)
async def stream_events(
    request: Request,
    current_user: _SSEAuthDep,
    streams: Annotated[
        list[str] | None,
        Query(description="Streams to subscribe to. Default: all."),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(description="Last Redis stream ID received — resumes from next event."),
    ] = None,
    token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> StreamingResponse:
    """Open a Server-Sent Events connection for realtime domain events.

    The client MUST send a valid `Authorization: Bearer <token>` header.
    Events are scoped to the tenant embedded in the token — cross-tenant
    leakage is structurally impossible.

    ### Reconnecting after disconnect
    Pass `?cursor=<last_id>` (the `id:` field from the last received frame)
    to resume without replaying already-processed events.

    ### Selecting streams
    `?streams=message.events&streams=conversation.events`
    Default: all four streams.
    """
    tenant_id = str(current_user.tenant_id) if current_user.tenant_id else ""
    user_id = str(current_user.id)
    selected = streams if streams else _ALL_STREAMS

    logger.info(
        "sse.open user=%s tenant=%s streams=%s cursor=%s",
        user_id, tenant_id, selected, cursor,
    )

    return StreamingResponse(
        _event_stream(
            tenant_id=tenant_id,
            user_id=user_id,
            streams=selected,
            cursor=cursor,
            request=request,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Nginx/Caddy: disable proxy buffering
            "Connection": "keep-alive",
        },
    )

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
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.core.redis import get_redis
from app.core.security import decode_token
from app.core.errors import PermissionDeniedError
from app.modules.identity.deps import AuthedUser, CurrentUserDep
import uuid


async def _sse_auth(
    request: Request,
    token: Annotated[str | None, Query(description="Access token (SSE fallback — browsers can't send headers)")] = None,
) -> AuthedUser:
    """SSE-compatible auth: accepts ?token= query param OR Authorization: Bearer.

    EventSource (browser) cannot send custom headers, so the frontend passes
    the access token as ?token=.  Regular Bearer header still works (e.g. tests).
    """
    # Try Authorization header first (standard Bearer)
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
        return AuthedUser(
            id=uuid.UUID(str(payload["sub"])),
            tenant_id=uuid.UUID(payload["tenant_id"]) if payload.get("tenant_id") else None,
            role_code=payload.get("role"),
        )
    except PermissionDeniedError:
        raise
    except Exception as exc:
        raise PermissionDeniedError("invalid token") from exc


_SSEAuthDep = Annotated[AuthedUser, Depends(_sse_auth)]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])

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


def _sse_frame(data: dict, *, event_id: str) -> bytes:
    """Encode one SSE data frame (id + data + blank line)."""
    payload = json.dumps(data, default=str)
    return f"id: {event_id}\ndata: {payload}\n\n".encode()


def _heartbeat() -> bytes:
    return b": heartbeat\n\n"


async def _build_cursor(cursor: str | None, streams: list[str]) -> dict[str, str]:
    """Translate a client cursor into per-stream XREAD start IDs."""
    if cursor:
        try:
            ms, seq = cursor.rsplit("-", 1)
            next_id = f"{ms}-{int(seq) + 1}"
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
            except asyncio.TimeoutError:
                results = None
            except Exception as exc:  # noqa: BLE001
                logger.warning("sse.redis_error %s", exc)
                await asyncio.sleep(1)
                continue

            # Heartbeat if overdue.
            if asyncio.get_event_loop().time() >= heartbeat_due:
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

                    # Decode payload.
                    raw_payload = (
                        fields.get(b"payload")
                        or fields.get("payload")
                        or b"{}"
                    )
                    if isinstance(raw_payload, bytes):
                        raw_payload = raw_payload.decode()
                    try:
                        payload: dict = json.loads(raw_payload)
                    except json.JSONDecodeError:
                        continue

                    # §149 Tenant isolation: every event envelope carries
                    # meta.tenant_id.  Drop cross-tenant events structurally.
                    meta = payload.get("meta", {})
                    event_tenant = str(meta.get("tenant_id", ""))
                    if event_tenant and tenant_id and event_tenant != tenant_id:
                        continue

                    yield _sse_frame(
                        {"stream": stream_key, "id": raw_id, "payload": payload},
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

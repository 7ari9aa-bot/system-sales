"""The control plane's HTTP surface: open a session, read it, interrupt it, hand it over, close it.

Nothing here carries audio. A browser or a phone asks the control plane for a session, the control
plane decides who the caller is and what they may do, and the media plane then connects with a
provider credential scoped to that one session. The persona is never read from the request body:
it comes from the authenticated principal, which is why a customer cannot ask for the merchant
assistant by sending ``persona: merchant_assistant``.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import (
    NotFoundError,
    PermissionDeniedError,
    StorageUnavailableError,
)
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.voice.application.browser_call import build_browser_call
from app.modules.voice.application.session_manager import VoiceSessionManager
from app.modules.voice.application.session_thread import ensure_session_thread
from app.modules.voice.application.transport import VoiceTransportService
from app.modules.voice.domain.personas import PrincipalType
from app.modules.voice.infrastructure.sql_store import SqlSessionStore
from app.modules.voice.runtime.gpt_live import GptLiveProtocolError, GptLiveUnavailable
from app.modules.voice.runtime.livekit import MediaPlaneUnavailable
from app.modules.voice.runtime.stream_ticket import (
    StreamTicketInvalid,
    StreamTicketIssuer,
    StreamTicketUnavailable,
)
from app.modules.voice.security.capabilities import ChannelType

router = APIRouter(prefix="/voice", tags=["voice"])

# A voice session is opened by a signed-in shop user; the capability resolver then narrows the
# scopes to what that user already holds, so this dependency is the floor, not the ceiling.
# Opening a voice session is opening the assistant, so it asks for the same permission the text
# assistant asks for (``AnalyticsAICtx`` in app/modules/ai/routers/_deps.py). It used to require
# ``orders:read``, which meant an employee allowed to see analytics but not orders could type to
# the assistant and not speak to it — one assistant, two different doors. What the session may
# then READ is decided per tool by the capability scopes, never by this gate.
VoiceCtx = Annotated[TenantContext, Depends(require_permission("analytics:read"))]


class StartSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: ChannelType = ChannelType.WEB_VOICE
    # The caller's own retry key (a phone leg id, a browser tab id). Two requests with the same key
    # return the same session instead of billing a second call.
    client_key: str | None = Field(default=None, max_length=128)


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    tenant_id: uuid.UUID
    persona: str
    state: str
    scopes: list[str]
    trace_id: str
    last_completed_turn: int


class CloseSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=120)


def _manager(ctx: TenantContext) -> VoiceSessionManager:
    return VoiceSessionManager(SqlSessionStore(ctx.session))


async def _authorized(ctx: TenantContext, session_id: uuid.UUID):
    """A session id from another shop answers exactly like an id that never existed."""
    try:
        return await _manager(ctx).for_tenant(session_id, ctx.tenant_id)
    except PermissionDeniedError as exc:
        raise NotFoundError("voice session not found") from exc


def _respond(record) -> SessionResponse:  # type: ignore[no-untyped-def]
    return SessionResponse(
        session_id=record.session_id,
        tenant_id=record.tenant_id,
        persona=record.persona.value,
        state=record.state.value,
        scopes=sorted(record.capability.scopes),
        trace_id=record.trace_id,
        last_completed_turn=record.last_completed_turn,
    )


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def start_session(ctx: VoiceCtx, body: StartSessionRequest) -> SessionResponse:
    record = await _manager(ctx).start(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        held_scopes=frozenset(ctx.permission_codes),
        channel=body.channel,
        client_key=body.client_key,
    )
    # The session owns a conversation from its first second: a spoken turn needs a thread to land
    # in, and a session that connects and stays silent must still be resumable. Idempotent, so a
    # client_key replay returns the thread the first request opened.
    await ensure_session_thread(ctx.session, ctx, session_id=record.session_id)
    return _respond(record)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def read_session(ctx: VoiceCtx, session_id: uuid.UUID) -> SessionResponse:
    return _respond(await _authorized(ctx, session_id))


@router.post("/sessions/{session_id}/interrupt", response_model=SessionResponse)
async def interrupt_session(ctx: VoiceCtx, session_id: uuid.UUID) -> SessionResponse:
    await _authorized(ctx, session_id)
    return _respond(await _manager(ctx).interrupt(session_id, tenant_id=ctx.tenant_id))


@router.post("/sessions/{session_id}/handoff", response_model=SessionResponse)
async def hand_off_session(ctx: VoiceCtx, session_id: uuid.UUID) -> SessionResponse:
    await _authorized(ctx, session_id)
    return _respond(await _manager(ctx).begin_handoff(session_id, tenant_id=ctx.tenant_id))


@router.post("/sessions/{session_id}/close", response_model=SessionResponse)
async def close_session(
    ctx: VoiceCtx, session_id: uuid.UUID, body: CloseSessionRequest
) -> SessionResponse:
    return _respond(
        await _manager(ctx).close(session_id, reason=body.reason, tenant_id=ctx.tenant_id)
    )


class TransportResponse(BaseModel):
    """Everything the client needs to join, and nothing about the shop behind the session."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    url: str
    token: str
    room: str
    identity: str
    expires_at: dt.datetime


def _transport() -> VoiceTransportService:
    return VoiceTransportService.from_settings()


@router.post("/sessions/{session_id}/transport", response_model=TransportResponse)
async def open_transport(ctx: VoiceCtx, session_id: uuid.UUID) -> TransportResponse:
    """Open the media path for a session the caller already owns.

    A session from another shop answers 404 exactly like an id that never existed, and a control
    plane with no media plane configured answers 503 rather than a credential that cannot connect.
    """
    record = await _authorized(ctx, session_id)
    try:
        credential = _transport().issue_for(record)
    except MediaPlaneUnavailable as exc:
        raise StorageUnavailableError("voice media plane is not configured") from exc
    return TransportResponse(
        provider=credential.provider,
        url=credential.url,
        token=credential.token,
        room=credential.room,
        identity=credential.identity,
        expires_at=credential.expires_at,
    )


class StreamTicketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: str
    expires_in: int
    path: str


def _stream_issuer() -> StreamTicketIssuer:
    return StreamTicketIssuer.from_settings()


def _call_factory():
    """The call builder; replaced in tests so no test opens a real gateway socket."""
    return build_browser_call


@router.post("/sessions/{session_id}/stream-ticket", response_model=StreamTicketResponse)
async def open_stream_ticket(ctx: VoiceCtx, session_id: uuid.UUID) -> StreamTicketResponse:
    """Mint the one-minute ticket a browser presents on the audio websocket.

    The browser cannot hold the gateway key, so it streams PCM to us and the
    socket to GPT-Live stays on the server. That door is a credential of its own:
    signed with the app secret, bound to this session and this shop, and valid for
    a minute — long enough to open one stream, too short to be worth stealing.
    """
    record = await _authorized(ctx, session_id)
    try:
        issuer = _stream_issuer()
    except StreamTicketUnavailable as exc:
        raise StorageUnavailableError("voice streaming is not configured") from exc
    return StreamTicketResponse(
        ticket=issuer.issue(session_id=record.id, tenant_id=record.tenant_id),
        expires_in=issuer.ttl_seconds,
        path=f"/api/v1/voice/sessions/{record.id}/stream",
    )


async def _pump(call, websocket: WebSocket) -> None:
    """Read model frames until the call closes or the transport breaks."""
    try:
        while not call.closed:
            await call.pump()
    except (GptLiveProtocolError, RuntimeError):
        return


@router.websocket("/sessions/{session_id}/stream")
async def stream_audio(websocket: WebSocket, session_id: uuid.UUID, ticket: str = "") -> None:
    """Carry one browser call: PCM in, model audio out.

    The ticket is the whole authentication story for this socket, so it is
    verified before a single byte of audio is read; a ticket for another session
    is refused exactly like a forged one. If the voice runtime is not configured
    the socket closes with 1011 instead of pretending to listen.
    """
    await websocket.accept()
    try:
        claims = _stream_issuer().verify(ticket, session_id=session_id)
    except (StreamTicketInvalid, StreamTicketUnavailable):
        await websocket.close(code=1008)
        return

    try:
        call = await _call_factory()(
            session_id=session_id,
            tenant_id=claims.tenant_id,
            send_audio=websocket.send_bytes,
        )
    except (GptLiveUnavailable, MediaPlaneUnavailable):
        await websocket.close(code=1011)
        return

    pump = asyncio.create_task(_pump(call, websocket))
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            chunk = message.get("bytes")
            if not chunk:
                continue
            try:
                await call.push_audio(chunk)
            except GptLiveProtocolError:
                break
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        await call.close()

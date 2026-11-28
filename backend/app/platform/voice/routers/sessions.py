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
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from app.core.ai_entitlement import require_ai_entitlement
from app.core.db import bind_tenant
from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    StorageUnavailableError,
)
from app.platform.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.platform.voice.application.browser_call import build_browser_call
from app.platform.voice.application.session_manager import VoiceSessionManager
from app.platform.voice.application.session_thread import ensure_session_thread
from app.platform.voice.application.transport import VoiceTransportService
from app.platform.voice.domain.personas import PrincipalType
from app.platform.voice.domain.states import IllegalTransition
from app.platform.voice.infrastructure.sql_store import SqlSessionStore
from app.platform.voice.infrastructure.stream_grants import (
    StreamGrantMissing,
    StreamGrantStore,
)
from app.platform.voice.runtime.gpt_live import GptLiveProtocolError, GptLiveUnavailable
from app.platform.voice.runtime.livekit import MediaPlaneUnavailable
from app.platform.voice.runtime.stream_ticket import (
    StreamTicketInvalid,
    StreamTicketIssuer,
    StreamTicketUnavailable,
)
from app.platform.voice.security.capabilities import ChannelType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# A voice session is opened by a signed-in shop user; the capability resolver then narrows the
# scopes to what that user already holds, so this dependency is the floor, not the ceiling.
# Opening a voice session is opening the assistant, so it asks for the same permission the text
# assistant asks for (``AnalyticsAICtx`` in app/modules/ai/routers/_deps.py). It used to require
# ``orders:read``, which meant an employee allowed to see analytics but not orders could type to
# the assistant and not speak to it — one assistant, two different doors. What the session may
# then READ is decided per tool by the capability scopes, never by this gate.
VoiceCtx = Annotated[TenantContext, Depends(require_permission("analytics:read"))]


class require_voice_ai:
    """The spoken assistant's two doors in one dependency: ``analytics:read`` and the plan gate.

    The routes that MINT something — a session, a media-plane credential, the one-minute stream
    ticket that opens the model socket — must carry the SAME plan gate the text assistant carries
    (``require_ai_entitlement``, ``CanUseAI``). The voice path used to check only
    ``analytics:read``, so a tenant whose plan does not sell the AI agents could open a paid
    realtime session the typed assistant would have refused at 403.

    It is ONE callable rather than two stacked ``Depends`` in the ``Annotated[...]`` because
    FastAPI applies only the LAST one (``fastapi/dependencies/utils.py::analyze_param`` keeps
    ``fastapi_specific_annotations[-1]``, in the pinned 0.142 and in current releases alike).
    Stacked that way the capability check is silently dropped — the shape ``AnalyticsAICtx`` has on
    the text side today. Composed here, both run in order and neither can be lost in a refactor:
    the permission first (403 ``missing permission: analytics:read``), then the plan gate
    (403 ``plan does not allow AI agents``, ``{"capability": "CanUseAI"}``) — the text path's own
    refusal, not a new one.

    The control routes (read, interrupt, handoff, close) deliberately stay on ``VoiceCtx``: a shop
    that downgrades mid-call must still be able to end the call it already started.
    """

    code = "CanUseAI"

    async def __call__(
        self,
        ctx: TenantCtxDep,
        capability: Annotated[TenantContext, Depends(require_permission("analytics:read"))],
        entitlement: Annotated[TenantContext, Depends(require_ai_entitlement())],
    ) -> TenantContext:
        return ctx


VoiceAICtx = Annotated[TenantContext, Depends(require_voice_ai())]


class StartSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: ChannelType = ChannelType.WEB_VOICE
    # The caller's own retry key (a phone leg id, a browser tab id). Two requests with the same key
    # return the same session instead of billing a second call.
    client_key: str | None = Field(default=None, max_length=128)
    # The conversation the merchant is already in. Given, the spoken turns join it instead of
    # opening a second conversation; omitted, the session opens its own thread as before.
    thread_id: uuid.UUID | None = None


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
async def start_session(ctx: VoiceAICtx, body: StartSessionRequest) -> SessionResponse:
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
    await ensure_session_thread(
        ctx.session, ctx, session_id=record.session_id, thread_id=body.thread_id
    )
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
async def open_transport(ctx: VoiceAICtx, session_id: uuid.UUID) -> TransportResponse:
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


async def _voice_config(tenant_id: str) -> dict[str, str]:
    """برومبت المكالمة: صوت المحل ولهجته وتعليمات التفويض.

    المفتاح هنا إن الـtenant ما بيوصلش للموديل: بيتقرا هنا، والـadapter بياخد نص جاهز.
    أي فشل في القراءة بيرجّع dict فاضي فالجلسة تفتح بالافتراضي بدل ما تسقط.
    """
    from app.core.db import get_sessionmaker
    from app.platform.voice.application.shop_voice import load_shop_voice_config

    try:
        async with get_sessionmaker()() as session:
            return await load_shop_voice_config(session, uuid.UUID(str(tenant_id)))
    except Exception:  # noqa: BLE001 - مكالمة من غير برومبت أحسن من مكالمة مرفوضة
        logger.exception("could not load the voice prompt for tenant %s", tenant_id)
        return {}


def _call_factory():
    """The call builder; replaced in tests so no test opens a real gateway socket."""
    return build_browser_call


def start_failure_reason(exc: BaseException) -> str:
    """Why a call never became real, in the vocabulary the row keeps.

    Every failure to open a call ends the session, so the reason has to be
    readable months later by somebody who was not here: the provider said no, the
    gateway refused the session, the network dropped, or something nobody
    anticipated. The last bucket is not laziness — the exception types a vendor
    transport can raise are not knowable, and a row left in CONFIGURING because
    the type was not on a list is worse than a row that says "provider_error".
    """
    name = type(exc).__name__
    if isinstance(exc, GptLiveProtocolError):
        return f"provider_protocol_error:{name}"
    if isinstance(exc, GptLiveUnavailable | MediaPlaneUnavailable):
        return f"provider_unavailable:{name}"
    if isinstance(exc, ConnectionError | TimeoutError):
        return f"provider_connection_error:{name}"
    return f"provider_error:{name}"


def _grant_store() -> StreamGrantStore:
    return StreamGrantStore.from_settings()


@router.post("/sessions/{session_id}/stream-ticket", response_model=StreamTicketResponse)
async def open_stream_ticket(ctx: VoiceAICtx, session_id: uuid.UUID) -> StreamTicketResponse:
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
    # Who the caller is is resolved HERE, once, by the same gate every other
    # endpoint uses; the socket redeems that resolution instead of repeating it.
    jti = await _grant_store().grant(
        session_id=record.session_id, tenant_id=record.tenant_id, user_id=ctx.user.id
    )
    return StreamTicketResponse(
        ticket=issuer.issue(session_id=record.session_id, tenant_id=record.tenant_id, jti=jti),
        expires_in=issuer.ttl_seconds,
        path=f"/api/v1/voice/sessions/{record.session_id}/stream",
    )


def _session_factory():  # noqa: ANN202 - a sessionmaker, replaced in tests
    """The sessionmaker the socket's own bookkeeping runs on.

    Kept behind a function so a test can drive the wiring without a database: the
    socket path is where the lifecycle is decided, and it must be testable on its own.
    """
    from app.core.db import get_sessionmaker

    return get_sessionmaker()


async def _lifecycle(tenant_id: uuid.UUID, step) -> None:  # noqa: ANN001 - a callable
    """Run one session-state step on its own short transaction.

    A socket that is already carrying audio is worth more than a tidy row, so a
    bookkeeping failure is logged and the call continues. The sweeper exists for
    exactly the rows this can leave behind: it runs every 5 minutes from
    ``scheduler_worker.GLOBAL_SWEEPERS`` and ends a session left in CONFIGURING
    or ACTIVE past its grace (``voice/application/session_sweeper.py``), so this
    failure leaves a row that is late, never one that is stuck forever.
    """
    try:
        async with _session_factory()() as session:
            await bind_tenant(session, tenant_id)
            await step(VoiceSessionManager(SqlSessionStore(session)))
            await session.commit()
    except Exception:  # noqa: BLE001 - bookkeeping never breaks a live call
        logger.warning("voice.lifecycle_step_failed tenant=%s", tenant_id, exc_info=True)


async def _connect_session(manager, session_id, provider_session_id: str) -> None:  # noqa: ANN001
    """Name the provider session, then say the call is live.

    CONFIGURING cannot reach ACTIVE directly — the state machine refuses that move —
    so both steps happen in one transaction: a row that records the provider and
    stays CONNECTING is just as wrong, only quieter.
    """
    await manager.attach_provider(session_id, provider_session_id)
    await manager.activate(session_id)


async def _end_session(
    manager,  # noqa: ANN001 - the manager is the only argument
    session_id,
    tenant_id,
    reason: str,
    *,
    failed: bool = False,
) -> None:
    """End the row the way the call actually ended.

    ``failed`` is for a call that never became real — no provider session was ever
    opened. Its ending is FAILED with the reason, said outright rather than inferred
    from the state machine refusing a move, because the caller asked us to record a
    failure and a store that tolerates the move would otherwise record a hangup.

    A socket that dies before the provider connected never reaches CLOSING, and a
    session that already ended needs nothing. Both become FAILED-with-a-reason or
    stay terminal; neither is left sitting in CONFIGURING.
    """
    if failed:
        try:
            await manager.fail(session_id, reason=reason)
            return
        except (ConflictError, IllegalTransition):
            logger.info("voice.session_already_ended session=%s", session_id)
            return
    try:
        await manager.close(session_id, reason=reason, tenant_id=tenant_id)
    except (ConflictError, IllegalTransition):
        try:
            await manager.fail(session_id, reason=reason)
        except (ConflictError, IllegalTransition):
            logger.info("voice.session_already_ended session=%s", session_id)


def control_frame(text: str) -> str | None:
    """The one control the browser may send on the audio socket: "interrupt".

    Anything else — malformed JSON, an unknown type, a field we do not act on — is
    ignored rather than guessed at, because a control frame that half-works is
    worse than one that is dropped.
    """
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return "interrupt" if payload.get("type") == "interrupt" else None


async def _pump(call, websocket: WebSocket) -> None:
    """Read model frames until the call closes or the transport breaks."""
    try:
        while not call.closed:
            await call.pump()
    except (GptLiveProtocolError, RuntimeError):
        return


@router.websocket("/sessions/{session_id}/stream")
async def stream_audio(websocket: WebSocket, session_id: uuid.UUID, ticket: str = "") -> None:
    """Carry one browser call: PCM in, model audio out — and record that it happened.

    The ticket is the whole authentication story for this socket, so it is
    verified before a single byte of audio is read; a ticket for another session
    is refused exactly like a forged one. If the voice runtime is not configured
    the socket closes with 1011 instead of pretending to listen.

    This is also the only place a session's state can be true: the provider session
    is named here, ACTIVE is claimed only once the transport really connected, and
    every ending — a hangup, a protocol error, a provider that never came up — is
    written as CLOSED or FAILED with its reason. A session that leaves here without
    an ending is the one thing the sweeper should never have to find.
    """
    await websocket.accept()
    try:
        claims = _stream_issuer().verify(ticket, session_id=session_id)
        grant = await _grant_store().take(claims.jti)
    except (StreamTicketInvalid, StreamTicketUnavailable, StreamGrantMissing):
        await websocket.close(code=1008)
        return
    if grant.session_id != str(session_id) or grant.tenant_id != claims.tenant_id:
        # The ticket and the grant must name the same call and the same shop.
        await websocket.close(code=1008)
        return

    tenant_id = uuid.UUID(str(grant.tenant_id))

    async def finish(reason: str, *, failed: bool = False) -> None:
        async def step(manager) -> None:  # noqa: ANN001 - the manager is the only argument
            await _end_session(manager, session_id, tenant_id, reason, failed=failed)

        await _lifecycle(tenant_id, step)

    try:
        config = await _voice_config(grant.tenant_id)
        call = await _call_factory()(
            session_id=session_id,
            tenant_id=grant.tenant_id,
            user_id=grant.user_id,
            send_audio=websocket.send_bytes,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 - every way a call can fail is an ending
        # The call never became real. Say so on the row instead of leaving it CONFIGURING:
        # an unlisted provider exception used to escape here entirely, so the session sat in
        # CONFIGURING until the sweeper found it and the client got a dead socket instead of
        # 1011. The reason names what happened; the row is ended either way.
        reason = start_failure_reason(exc)
        logger.warning(
            "voice.start_failed session=%s tenant=%s reason=%s",
            session_id,
            grant.tenant_id,
            reason,
            exc_info=True,
        )
        await finish(reason)
        await websocket.close(code=1011)
        return

    # The provider session the model actually opened is the one fact the row was
    # missing: without it a session cannot be resumed, reconnected or billed.
    provider_session_id = getattr(call, "provider_session_id", None)
    if provider_session_id:

        async def connected(manager) -> None:  # noqa: ANN001 - the manager is the only argument
            await _connect_session(manager, session_id, provider_session_id)

        await _lifecycle(tenant_id, connected)

    pump = asyncio.create_task(_pump(call, websocket))
    ending = "socket_closed"
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            control = message.get("text")
            if control:
                # Barge-in: the caller talked over the model. The loop stops
                # playing immediately; the model still owns its own turn.
                if control_frame(control) == "interrupt":
                    await call.interrupt()
                continue
            chunk = message.get("bytes")
            if not chunk:
                continue
            try:
                await call.push_audio(chunk)
            except GptLiveProtocolError:
                ending = "protocol_error"
                break
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        # close() and finish() are two different promises. Closing the transport is a courtesy
        # to the provider; recording the ending is the durable fact the control plane depends on.
        # They used to share one sequence, so a close() that raised (a socket already gone, a
        # transport that lost its task) skipped finish() and left a session that really ended
        # looking ACTIVE. The close error is logged and the ending still happens.
        try:
            try:
                await call.close()
            except Exception:  # noqa: BLE001 - a broken close must not cost the row its ending
                logger.warning("voice.call_close_failed session=%s", session_id, exc_info=True)
        finally:
            await finish(ending)

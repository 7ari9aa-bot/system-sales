"""The control plane's HTTP surface: open a session, read it, interrupt it, hand it over, close it.

Nothing here carries audio. A browser or a phone asks the control plane for a session, the control
plane decides who the caller is and what they may do, and the media plane then connects with a
provider credential scoped to that one session. The persona is never read from the request body:
it comes from the authenticated principal, which is why a customer cannot ask for the merchant
assistant by sending ``persona: merchant_assistant``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import (
    NotFoundError,
    PermissionDeniedError,
    StorageUnavailableError,
)
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.voice.application.session_manager import VoiceSessionManager
from app.modules.voice.application.transport import VoiceTransportService
from app.modules.voice.domain.personas import PrincipalType
from app.modules.voice.infrastructure.sql_store import SqlSessionStore
from app.modules.voice.runtime.livekit import MediaPlaneUnavailable
from app.modules.voice.security.capabilities import ChannelType

router = APIRouter(prefix="/voice", tags=["voice"])

# A voice session is opened by a signed-in shop user; the capability resolver then narrows the
# scopes to what that user already holds, so this dependency is the floor, not the ceiling.
VoiceCtx = Annotated[TenantContext, Depends(require_permission("orders:read"))]


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

"""One live voice session, from the moment a principal is proved to the moment it is closed.

The manager is the control plane: it decides who the session belongs to, which persona it runs,
which capability it holds and which state it is in. It never touches audio. That separation is
what lets the media plane scale on its own, and it is why every permission question is answered
here, once, at the start of the session and again on every tool call.

Two rules are enforced here rather than trusted from a caller:

* the tenant is fixed when the session is created (invariant 8) — a request that names another
  tenant is refused, never re-scoped;
* a session id handed twice for the same client key returns the session already open instead of
  opening a second one, so a retried "start" from a flaky phone cannot bill two sessions.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, replace
from typing import Protocol

from app.core.errors import ConflictError, NotFoundError
from app.modules.voice.domain.personas import PersonaType, PrincipalType
from app.modules.voice.domain.states import (
    VoiceSessionState,
    agent_may_speak,
    next_session_state,
    session_is_terminal,
)
from app.modules.voice.security.capabilities import (
    AuthenticationLevel,
    ChannelType,
    SessionCapability,
    ToolGateway,
    assert_same_tenant,
    resolve_capability,
)

_LIVE_STATES = frozenset(
    {
        VoiceSessionState.CREATED,
        VoiceSessionState.AUTHENTICATING,
        VoiceSessionState.CONFIGURING,
        VoiceSessionState.CONNECTING,
        VoiceSessionState.ACTIVE,
        VoiceSessionState.DEGRADED,
        VoiceSessionState.INTERRUPTED,
        VoiceSessionState.HANDOFF_PENDING,
        VoiceSessionState.HUMAN_ACTIVE,
        VoiceSessionState.CLOSING,
    }
)


@dataclass(frozen=True, slots=True)
class VoiceSessionRecord:
    """The durable shape of a session. Everything an operator needs to explain it later."""

    session_id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID | None
    capability: SessionCapability
    state: VoiceSessionState
    trace_id: str
    client_key: str | None = None
    provider_session_id: str | None = None
    provider_name: str | None = None
    created_at: dt.datetime = dt.datetime.min.replace(tzinfo=dt.UTC)
    updated_at: dt.datetime = dt.datetime.min.replace(tzinfo=dt.UTC)
    last_completed_turn: int = 0
    closed_reason: str | None = None

    @property
    def persona(self) -> PersonaType:
        return self.capability.persona

    @property
    def may_speak(self) -> bool:
        return agent_may_speak(self.state)


class SessionStore(Protocol):
    """Where records live. In-memory for tests, Postgres in the service."""

    async def get(self, session_id: uuid.UUID) -> VoiceSessionRecord | None: ...

    async def put(self, record: VoiceSessionRecord) -> None: ...

    async def find_by_client_key(
        self, tenant_id: uuid.UUID, client_key: str
    ) -> VoiceSessionRecord | None: ...


class InMemorySessionStore:
    """The store tests use, and the reference for the SQL one that follows it."""

    def __init__(self) -> None:
        self._records: dict[uuid.UUID, VoiceSessionRecord] = {}

    async def get(self, session_id: uuid.UUID) -> VoiceSessionRecord | None:
        return self._records.get(session_id)

    async def put(self, record: VoiceSessionRecord) -> None:
        self._records[record.session_id] = record

    async def find_by_client_key(
        self, tenant_id: uuid.UUID, client_key: str
    ) -> VoiceSessionRecord | None:
        for record in self._records.values():
            if record.tenant_id == tenant_id and record.client_key == client_key:
                return record
        return None


class VoiceSessionManager:
    """Creates sessions, moves them through the state machine, and refuses anything else."""

    def __init__(
        self,
        store: SessionStore,
        *,
        gateway: ToolGateway | None = None,
        clock: callable[[], dt.datetime] | None = None,
    ) -> None:
        self._store = store
        self._gateway = gateway or ToolGateway()
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    async def start(
        self,
        *,
        principal_type: PrincipalType,
        principal_id: uuid.UUID | None,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
        held_scopes: frozenset[str] = frozenset(),
        channel: ChannelType = ChannelType.WEB_VOICE,
        client_key: str | None = None,
        authentication_level: AuthenticationLevel = AuthenticationLevel.ANONYMOUS,
        agent_version_id: uuid.UUID | None = None,
        trace_id: str | None = None,
    ) -> VoiceSessionRecord:
        if client_key is not None:
            existing = await self._store.find_by_client_key(tenant_id, client_key)
            if existing is not None and existing.state in _LIVE_STATES:
                return existing

        capability = resolve_capability(
            principal_type=principal_type,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            held_scopes=held_scopes,
            channel=channel,
            authentication_level=authentication_level,
            agent_version_id=agent_version_id,
            issued_at=self._clock(),
        )
        now = self._clock()
        record = VoiceSessionRecord(
            session_id=capability.session_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            capability=capability,
            state=VoiceSessionState.CREATED,
            trace_id=trace_id or f"voice-{capability.session_id}",
            client_key=client_key,
            created_at=now,
            updated_at=now,
        )
        record = await self._move(record, VoiceSessionState.AUTHENTICATING)
        record = await self._move(record, VoiceSessionState.CONFIGURING)
        return record

    async def attach_provider(
        self, session_id: uuid.UUID, provider_session_id: str
    ) -> VoiceSessionRecord:
        record = await self.require(session_id)
        record = await self._move(
            replace(record, provider_session_id=provider_session_id),
            VoiceSessionState.CONNECTING,
        )
        return record

    async def rebind_provider(
        self, session_id: uuid.UUID, provider_session_id: str
    ) -> VoiceSessionRecord:
        """Point a live session at a new provider session after a media drop.

        No state move: the session was already past CONNECTING, and pretending it connects again
        would be a lie about what the caller experienced. Recovery degrades, rebinds, reactivates.
        """
        record = await self.require(session_id)
        return await self._save(replace(record, provider_session_id=provider_session_id))

    async def activate(self, session_id: uuid.UUID) -> VoiceSessionRecord:
        return await self._move(await self.require(session_id), VoiceSessionState.ACTIVE)

    async def degrade(self, session_id: uuid.UUID) -> VoiceSessionRecord:
        return await self._move(await self.require(session_id), VoiceSessionState.DEGRADED)

    async def interrupt(
        self, session_id: uuid.UUID, *, tenant_id: uuid.UUID | None = None
    ) -> VoiceSessionRecord:
        record = await self._authorized(session_id, tenant_id)
        return await self._move(record, VoiceSessionState.INTERRUPTED)

    async def resume(self, session_id: uuid.UUID) -> VoiceSessionRecord:
        return await self._move(await self.require(session_id), VoiceSessionState.ACTIVE)

    async def begin_handoff(
        self, session_id: uuid.UUID, *, tenant_id: uuid.UUID | None = None
    ) -> VoiceSessionRecord:
        record = await self._authorized(session_id, tenant_id)
        return await self._move(record, VoiceSessionState.HANDOFF_PENDING)

    async def human_takeover(self, session_id: uuid.UUID) -> VoiceSessionRecord:
        """The staff member owns the call now; the agent is silent until it is closed."""
        return await self._move(await self.require(session_id), VoiceSessionState.HUMAN_ACTIVE)

    async def close(
        self,
        session_id: uuid.UUID,
        *,
        reason: str = "caller_hangup",
        tenant_id: uuid.UUID | None = None,
    ) -> VoiceSessionRecord:
        record = await self._authorized(session_id, tenant_id)
        record = await self._move(record, VoiceSessionState.CLOSING)
        record = await self._move(record, VoiceSessionState.CLOSED)
        return await self._save(replace(record, closed_reason=reason))

    async def fail(self, session_id: uuid.UUID, *, reason: str) -> VoiceSessionRecord:
        record = await self.require(session_id)
        record = await self._move(record, VoiceSessionState.FAILED)
        return await self._save(replace(record, closed_reason=reason))

    async def note_turn_completed(self, session_id: uuid.UUID, sequence: int) -> VoiceSessionRecord:
        record = await self.require(session_id)
        return await self._save(
            replace(record, last_completed_turn=max(record.last_completed_turn, sequence))
        )

    async def _authorized(
        self, session_id: uuid.UUID, tenant_id: uuid.UUID | None
    ) -> VoiceSessionRecord:
        """A session reached from a request that names a tenant is checked against it.

        The SQL store leans on RLS, but the API must not: a by-id read that answers 200 for a
        foreign id teaches the caller the session exists, and an in-memory store would hand it
        over. Every router path goes through here.
        """
        record = await self.require(session_id)
        if tenant_id is not None:
            assert_same_tenant(record.capability, tenant_id)
        return record

    async def require(self, session_id: uuid.UUID) -> VoiceSessionRecord:
        record = await self._store.get(session_id)
        if record is None:
            raise NotFoundError("voice session not found")
        return record

    async def for_tenant(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> VoiceSessionRecord:
        """The only way to reach a session by id from a request that names a tenant."""
        record = await self.require(session_id)
        assert_same_tenant(record.capability, tenant_id)
        return record

    async def _move(
        self, record: VoiceSessionRecord, target: VoiceSessionState
    ) -> VoiceSessionRecord:
        if session_is_terminal(record.state):
            raise ConflictError(f"voice session is already {record.state}")
        state = next_session_state(record.state, target)
        return await self._save(replace(record, state=state))

    async def _save(self, record: VoiceSessionRecord) -> VoiceSessionRecord:
        record = replace(record, updated_at=self._clock())
        await self._store.put(record)
        return record

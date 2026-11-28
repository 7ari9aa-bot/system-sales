"""The durable store behind a voice session.

The manager talks to ``SessionStore``; this is the PostgreSQL one. It keeps two promises the
in-memory store cannot make: a session outlives the worker that opened it, and a phone that retries
the same client key finds the same open session instead of a second billable call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.voice.application.session_manager import VoiceSessionRecord
from app.modules.voice.domain.models import VoiceSessionRow
from app.modules.voice.domain.personas import PersonaType, PrincipalType
from app.modules.voice.domain.states import VoiceSessionState
from app.modules.voice.security.capabilities import (
    AuthenticationLevel,
    ChannelType,
    SessionCapability,
)

_LIVE = frozenset(
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
    }
)


class SqlSessionStore:
    """A ``SessionStore`` over the tenant's own session, so RLS decides what is visible."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, session_id: uuid.UUID) -> VoiceSessionRecord | None:
        row = await self._session.get(VoiceSessionRow, session_id)
        return _to_record(row) if row is not None else None

    async def find_by_client_key(
        self, tenant_id: uuid.UUID, client_key: str
    ) -> VoiceSessionRecord | None:
        row = (
            await self._session.execute(
                select(VoiceSessionRow).where(
                    VoiceSessionRow.tenant_id == tenant_id,
                    VoiceSessionRow.client_key == client_key,
                )
            )
        ).scalar_one_or_none()
        if row is None or VoiceSessionState(row.state) not in _LIVE:
            return None
        return _to_record(row)

    async def record_completed_turn(self, session_id: uuid.UUID, sequence: int) -> None:
        """Move the turn counter forward in one statement.

        Not ``put()``: a read-modify-write of the whole row would carry the state this worker read
        a moment ago back over a CLOSED or FAILED written in between. This UPDATE cannot move the
        counter backwards, and running it twice changes nothing the second time.
        """
        await self._session.execute(
            update(VoiceSessionRow)
            .where(
                VoiceSessionRow.id == session_id,
                VoiceSessionRow.last_completed_turn < sequence,
            )
            .values(last_completed_turn=sequence, updated_at=datetime.now(UTC))
        )
        await self._session.flush()

    async def put(self, record: VoiceSessionRecord) -> None:
        values = {
            "id": record.session_id,
            "tenant_id": record.tenant_id,
            "workspace_id": record.workspace_id,
            "principal_type": record.capability.principal_type.value,
            "principal_id": record.capability.principal_id,
            "persona": record.capability.persona.value,
            "channel": record.capability.channel.value,
            "state": record.state.value,
            "authentication_level": int(record.capability.authentication_level),
            "scopes": sorted(record.capability.scopes),
            "agent_version_id": record.capability.agent_version_id,
            "ai_chat_thread_id": record.capability.ai_chat_thread_id,
            "policy_version": record.capability.policy_version,
            "provider_session_id": record.provider_session_id,
            "provider_name": record.provider_name,
            "trace_id": record.trace_id,
            "client_key": record.client_key,
            "last_completed_turn": record.last_completed_turn,
            "close_reason": record.closed_reason,
            "expires_at": record.capability.expires_at,
            "updated_at": datetime.now(UTC),
        }
        existing = await self._session.get(VoiceSessionRow, record.session_id)
        if existing is None and record.client_key is not None:
            # The key belongs to one live call. A finished call on the same screen keeps its row
            # but must let go of the key, otherwise the next press hits
            # ux_voice_sessions_client_key and the merchant gets a 500 for pressing again.
            await self._session.execute(
                update(VoiceSessionRow)
                .where(
                    VoiceSessionRow.tenant_id == record.tenant_id,
                    VoiceSessionRow.client_key == record.client_key,
                    VoiceSessionRow.id != record.session_id,
                    VoiceSessionRow.state.not_in([state.value for state in _LIVE]),
                )
                .values(client_key=None)
            )
        if existing is None:
            self._session.add(VoiceSessionRow(**values))
        else:
            await self._session.execute(
                update(VoiceSessionRow)
                .where(VoiceSessionRow.id == record.session_id)
                .values(**{k: v for k, v in values.items() if k != "id"})
            )
        await self._session.flush()


def _to_record(row: VoiceSessionRow) -> VoiceSessionRecord:
    capability = SessionCapability(
        session_id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        principal_type=PrincipalType(row.principal_type),
        principal_id=row.principal_id,
        persona=PersonaType(row.persona),
        scopes=frozenset(row.scopes or ()),
        channel=ChannelType(row.channel),
        authentication_level=AuthenticationLevel(row.authentication_level),
        agent_version_id=row.agent_version_id,
        ai_chat_thread_id=row.ai_chat_thread_id,
        policy_version=row.policy_version,
        issued_at=row.started_at,
        expires_at=row.expires_at,
    )
    return VoiceSessionRecord(
        session_id=row.id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        capability=capability,
        state=VoiceSessionState(row.state),
        trace_id=row.trace_id,
        provider_session_id=row.provider_session_id,
        provider_name=row.provider_name,
        client_key=row.client_key,
        last_completed_turn=row.last_completed_turn,
        closed_reason=row.close_reason,
        created_at=row.started_at,
        updated_at=row.updated_at,
    )

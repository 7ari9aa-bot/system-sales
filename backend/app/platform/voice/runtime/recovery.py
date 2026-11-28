"""Bringing a live session back after the media path dies.

The session id, the tenant, the persona and the capability survive; only the provider session is
replaced. That is the whole point of keeping provider session ids in their own column: recovery is
a rebind, not a new conversation, and it never re-issues a capability with wider scopes.
"""

from __future__ import annotations

import uuid

from app.platform.voice.application.session_manager import VoiceSessionManager
from app.platform.voice.domain.contracts import AudioPath
from app.platform.voice.domain.states import session_is_terminal
from app.platform.voice.runtime.providers import ProviderRouter, ResumePlan


class SessionRecovery:
    def __init__(self, manager: VoiceSessionManager, router: ProviderRouter) -> None:
        self._manager = manager
        self._router = router

    async def recover(
        self,
        session_id: uuid.UUID,
        *,
        path: AudioPath,
        language: str,
        prefer: str | None = None,
        unavailable: frozenset[str] = frozenset(),
    ) -> ResumePlan:
        record = await self._manager.require(session_id)
        if session_is_terminal(record.state):
            raise ValueError(f"session {session_id} is already {record.state}")

        entry = self._router.choose(
            path=path, language=language, prefer=prefer, unavailable=unavailable
        )
        provider_session_id = await entry.provider.create_session(
            {
                "tenant_id": str(record.tenant_id),
                "persona": record.persona.value,
                "trace_id": record.trace_id,
                "resume_from_turn": record.last_completed_turn,
                "scopes": sorted(record.capability.scopes),
            }
        )
        degraded = await self._manager.degrade(session_id)
        await self._manager.rebind_provider(session_id, provider_session_id)
        active = await self._manager.activate(session_id)
        return ResumePlan(
            session_id=str(active.session_id),
            provider_session_id=provider_session_id,
            resume_from_turn=degraded.last_completed_turn,
            state=active.state,
        )

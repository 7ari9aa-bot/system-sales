"""Voice that arrives as a finished file: WhatsApp notes, Instagram and Messenger media.

The realtime runtime cannot serve these: the audio is already recorded, there is nobody to
interrupt, and the reply is a message rather than a stream. So they go through one asynchronous
pipeline that transcribes, runs the same capability-checked turn logic, and writes the answer back
into the conversation the customer already has, whatever channel it started on.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.platform.voice.application.session_manager import (
    VoiceSessionManager,
    VoiceSessionRecord,
)
from app.platform.voice.domain.channels import contract_for
from app.platform.voice.security.capabilities import (
    AuthenticationLevel,
    ChannelType,
    PrincipalType,
)
from app.platform.voice.security.channel_identity import (
    ChannelHandle,
    ChannelIdentityResolver,
)


@dataclass(frozen=True, slots=True)
class InboundVoiceNote:
    """One recorded message, exactly as the channel handed it over."""

    tenant_id: uuid.UUID
    channel: ChannelType
    external_id: str
    media_ref: str
    seconds: int
    conversation_id: uuid.UUID | None = None
    thread_id: uuid.UUID | None = None
    client_key: str | None = None
    language: str = "ar-EG"


@dataclass(frozen=True, slots=True)
class VoiceNoteResult:
    session: VoiceSessionRecord
    transcript: str
    reply: str | None
    conversation_id: uuid.UUID | None
    thread_id: uuid.UUID | None
    channel: ChannelType
    customer_id: uuid.UUID | None
    level: AuthenticationLevel
    identity_reason: str


class Transcriber(Protocol):
    async def transcribe(self, media_ref: str, *, language: str) -> str: ...


Responder = Callable[[str, VoiceSessionRecord], Awaitable[str]]


class AsyncVoicePipeline:
    """One entry point for every channel that delivers a finished recording."""

    def __init__(
        self,
        *,
        resolver: ChannelIdentityResolver,
        sessions: VoiceSessionManager,
        transcriber: Transcriber,
        responder: Responder,
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._resolver = resolver
        self._sessions = sessions
        self._transcriber = transcriber
        self._responder = responder
        self._clock = clock

    async def handle(self, note: InboundVoiceNote) -> VoiceNoteResult:
        contract = contract_for(note.channel)
        contract.check_note(note.seconds)

        handle = ChannelHandle(
            channel=note.channel, external_id=note.external_id, tenant_id=note.tenant_id
        )
        resolution = await self._resolver.resolve(handle)

        session = await self._sessions.start(
            principal_type=PrincipalType.CUSTOMER,
            principal_id=resolution.customer_id,
            tenant_id=note.tenant_id,
            held_scopes=frozenset(),
            channel=note.channel,
            client_key=note.client_key or note.media_ref,
            authentication_level=resolution.level,
        )

        transcript = await self._transcriber.transcribe(note.media_ref, language=note.language)
        if not transcript.strip():
            # An empty transcript is not a question. Answering anyway would invent one.
            return VoiceNoteResult(
                session=session,
                transcript="",
                reply=None,
                conversation_id=note.conversation_id,
                thread_id=note.thread_id,
                channel=note.channel,
                customer_id=resolution.customer_id,
                level=resolution.level,
                identity_reason=resolution.reason,
            )

        reply = await self._responder(transcript, session)
        return VoiceNoteResult(
            session=session,
            transcript=transcript,
            reply=reply,
            conversation_id=note.conversation_id,
            thread_id=note.thread_id,
            channel=note.channel,
            customer_id=resolution.customer_id,
            level=resolution.level,
            identity_reason=resolution.reason,
        )

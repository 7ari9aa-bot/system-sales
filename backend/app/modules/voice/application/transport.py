"""Handing a live session its media credential, or refusing to.

A credential is issued only for a session that is about to carry live audio, and only on a channel
that carries live audio at all. A WhatsApp voice note is a file that arrives after the fact, so
asking it for a room is a mistake worth an answer rather than a silently degraded experience.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.errors import ConflictError
from app.modules.voice.application.session_manager import VoiceSessionRecord
from app.modules.voice.domain.states import VoiceSessionState
from app.modules.voice.runtime.livekit import (
    LiveKitCredentials,
    LiveKitTokenIssuer,
    MediaPlaneUnavailable,
    RoomGrant,
    TransportCredential,
)
from app.modules.voice.security.capabilities import ChannelType

# A room may be opened or re-opened while the session still expects audio. A closed, failed or
# rejected session does not get a door back: it gets a new session with its own identity.
TRANSPORT_STATES = frozenset(
    {
        VoiceSessionState.CONFIGURING,
        VoiceSessionState.CONNECTING,
        VoiceSessionState.ACTIVE,
        VoiceSessionState.DEGRADED,
        VoiceSessionState.INTERRUPTED,
        VoiceSessionState.HANDOFF_PENDING,
        VoiceSessionState.HUMAN_ACTIVE,
    }
)

# Channels that carry live audio. whatsapp_voice arrives as a recorded note instead.
REALTIME_CHANNELS = frozenset(
    {
        ChannelType.WEB_VOICE,
        ChannelType.CHAT_VOICE,
        ChannelType.PSTN,
        ChannelType.MOBILE,
    }
)


class VoiceTransportService:
    """Turns an authorized session into a join credential, or says why it cannot."""

    def __init__(self, issuer_factory: Callable[[], LiveKitTokenIssuer]) -> None:
        self._issuer_factory = issuer_factory

    @classmethod
    def from_settings(cls) -> VoiceTransportService:
        def build() -> LiveKitTokenIssuer:
            credentials = LiveKitCredentials.from_settings()
            if credentials is None:
                raise MediaPlaneUnavailable("voice media plane is not configured")
            return LiveKitTokenIssuer(credentials)

        return cls(build)

    def issue_for(self, record: VoiceSessionRecord) -> TransportCredential:
        channel = record.capability.channel
        if channel not in REALTIME_CHANNELS:
            raise ConflictError(f"channel {channel.value} carries voice as a file, not as a room")
        if record.state not in TRANSPORT_STATES:
            raise ConflictError(f"session is {record.state.value}, so it has no media path")
        issuer = self._issuer_factory()
        # The room is the session id. The identity is the session, not the person: a participant
        # name that repeated a phone number would put the caller back inside the credential.
        return issuer.issue(
            RoomGrant(room=str(record.session_id), identity=f"session-{record.session_id}")
        )

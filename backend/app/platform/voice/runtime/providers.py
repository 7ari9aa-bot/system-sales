"""Which provider serves this session, and what happens when it stops answering.

A session never belongs to a provider. The router picks one from the capabilities the provider
declared, and when that provider fails the session keeps its identity and its completed turns and
continues on another path. The caller may have to repeat one sentence; they never get a second
identity, a second tenant, or a "resumed" conversation that quietly lost its history.

The fake provider below is what the tests drive: it records what it was asked to say, and it can
be told to drop, so recovery is proven instead of assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.platform.voice.domain.contracts import (
    AudioPath,
    ProviderCapabilities,
    RealtimeSpeechProvider,
)
from app.platform.voice.domain.states import VoiceSessionState


class NoProviderAvailable(Exception):
    """Raised when no configured provider can serve the path the session needs."""


@dataclass(frozen=True, slots=True)
class ProviderEntry:
    name: str
    capabilities: ProviderCapabilities
    provider: RealtimeSpeechProvider


@dataclass(slots=True)
class ProviderRouter:
    """Deny-by-default selection: a provider serves only what it declared it can serve."""

    entries: list[ProviderEntry] = field(default_factory=list)

    def register(self, name: str, capabilities: ProviderCapabilities, provider) -> None:
        self.entries.append(ProviderEntry(name=name, capabilities=capabilities, provider=provider))

    def choose(
        self,
        *,
        path: AudioPath,
        language: str,
        prefer: str | None = None,
        unavailable: frozenset[str] = frozenset(),
    ) -> ProviderEntry:
        candidates = [
            entry
            for entry in self.entries
            if entry.name not in unavailable and entry.capabilities.can_serve(path, language)
        ]
        if prefer is not None:
            candidates.sort(key=lambda entry: entry.name != prefer)
        if not candidates:
            raise NoProviderAvailable(
                f"no provider serves {path} in {language!r}"
                + (f" (unavailable: {sorted(unavailable)})" if unavailable else "")
            )
        return candidates[0]


@dataclass(slots=True)
class FakeRealtimeProvider:
    """Records the conversation and can be told to drop mid-session."""

    up: bool = True
    created: list[dict] = field(default_factory=list)
    spoken: list[tuple[str, str]] = field(default_factory=list)
    interrupted: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    dropped_at: str | None = None

    async def create_session(self, config: dict) -> str:
        if not self.up:
            raise ConnectionError("realtime provider is down")
        session_id = f"fake-{len(self.created) + 1}"
        self.created.append({"session_id": session_id, **config})
        return session_id

    async def stream_audio(self, session_id: str, audio: bytes) -> None:
        if not self.up:
            raise ConnectionError("realtime provider dropped the stream")

    async def say(self, session_id: str, text: str) -> None:
        if not self.up:
            self.dropped_at = session_id
            raise ConnectionError("realtime provider dropped before speaking")
        self.spoken.append((session_id, text))

    async def interrupt(self, session_id: str) -> None:
        self.interrupted.append(session_id)

    async def close_session(self, session_id: str) -> None:
        self.closed.append(session_id)


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """What a recovered session continues from: the last completed turn, nothing older."""

    session_id: str
    provider_session_id: str
    resume_from_turn: int
    state: VoiceSessionState
    note: str = "the caller may be asked to repeat the sentence that was in flight"

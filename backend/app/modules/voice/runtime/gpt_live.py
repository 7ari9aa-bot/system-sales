"""GPT-Live through the Vercel AI Gateway: a live voice session whose turns belong to the model.

Two facts about GPT-Live shape this adapter and are enforced here rather than documented:

* input is audio only. A caller's microphone bytes go in as PCM16 and nothing is ever sent as if
  it were speech, because the gateway rejects a text frame outright and the session dies with it.
* the model starts and stops its own turns. ``interrupt`` therefore stops the audio we play and
  tells the model to stop; it does not cancel a response the way the turn-based Realtime API
  allows. Pretending otherwise would show the caller silence we cannot actually produce.

The transport is injected, so the whole protocol is testable without a socket.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# The rate the model expects and returns. PCM16 mono, so a frame must always be an even length.
PCM_RATE = 24000
DEFAULT_URL = "wss://ai-gateway.vercel.sh/v1/live/sessions"
DEFAULT_MODEL = "openai/gpt-live-1.1"
DEFAULT_VOICE = "marin"


class GptLiveUnavailable(Exception):
    """No gateway credentials, so no voice session can be opened."""


class GptLiveProtocolError(Exception):
    """The gateway refused the session or answered with something we cannot use."""


@dataclass(frozen=True, slots=True)
class GptLiveConfig:
    api_key: str
    url: str = DEFAULT_URL
    model: str = DEFAULT_MODEL
    voice: str = DEFAULT_VOICE

    def __post_init__(self) -> None:
        if not self.url.startswith("wss://"):
            raise GptLiveProtocolError("the live session url must be a secure websocket url")
        if not self.api_key:
            raise GptLiveUnavailable("a gateway key is required to open a voice session")
        if not self.model or not self.voice:
            raise GptLiveProtocolError("model and voice are both required")

    @classmethod
    def from_settings(cls) -> GptLiveConfig | None:
        from app.core.config import get_settings

        settings = get_settings()
        key = (getattr(settings, "gpt_live_api_key", "") or "").strip()
        if not key:
            return None
        return cls(
            api_key=key,
            url=(getattr(settings, "gpt_live_url", "") or DEFAULT_URL).strip(),
            model=(getattr(settings, "gpt_live_model", "") or DEFAULT_MODEL).strip(),
            voice=(getattr(settings, "gpt_live_voice", "") or DEFAULT_VOICE).strip(),
        )


class GptLiveTransport(Protocol):
    """The four things this adapter needs from a socket, and nothing more."""

    async def send_json(self, payload: dict[str, Any]) -> None: ...

    async def recv_event(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


@dataclass(slots=True)
class GptLiveSession:
    """What one live session accumulates between frames."""

    session_id: str
    spoken: bytearray = field(default_factory=bytearray)
    pending_input: bytes = b""
    interrupted: bool = False


class GptLiveProvider:
    """A ``RealtimeSpeechProvider`` backed by GPT-Live over a websocket."""

    def __init__(
        self,
        config: GptLiveConfig,
        transport_factory: Callable[[GptLiveConfig], GptLiveTransport],
    ) -> None:
        self._config = config
        self._transport_factory = transport_factory
        self._transports: dict[str, GptLiveTransport] = {}
        self._sessions: dict[str, GptLiveSession] = {}

    @property
    def model(self) -> str:
        return self._config.model

    async def create_session(self, config: dict[str, Any]) -> str:
        """Open a session and wait for ``session.started``.

        ``config`` may carry conversation instructions. It may not carry a tenant, a persona or an
        identity: those belong to the control plane and never travel to the voice model.
        """
        forbidden = {"tenant_id", "persona", "principal_id", "capability"} & set(config)
        if forbidden:
            raise GptLiveProtocolError(f"{sorted(forbidden)} must not be sent to the voice model")
        transport = self._transport_factory(self._config)
        await transport.send_json(
            {
                "type": "session.start",
                "event_id": f"start-{uuid.uuid4().hex[:12]}",
                "session": {
                    "model": self._config.model,
                    "instructions": str(config.get("instructions", "")),
                    "audio": {
                        "format": {"type": "audio/pcm", "rate": PCM_RATE},
                        "output": {"voice": self._config.voice},
                    },
                },
            }
        )
        for _ in range(20):
            event = await transport.recv_event()
            kind = event.get("type")
            if kind == "session.started":
                session_id = str(event.get("session", {}).get("id") or uuid.uuid4())
                self._transports[session_id] = transport
                self._sessions[session_id] = GptLiveSession(session_id=session_id)
                return session_id
            if kind == "error":
                await transport.close()
                raise GptLiveProtocolError(str(event.get("error", "session refused")))
        await transport.close()
        raise GptLiveProtocolError("the session never reached session.started")

    async def stream_audio(self, session_id: str, audio: bytes) -> None:
        """Send caller audio, keeping PCM16 frames whole across calls."""
        session = self._session(session_id)
        buffer = session.pending_input + audio
        usable = len(buffer) - (len(buffer) % 2)
        session.pending_input = buffer[usable:]
        if not usable:
            return
        await self._transport(session_id).send_json(
            {
                "type": "session.input_audio.append",
                "audio": base64.b64encode(buffer[:usable]).decode("ascii"),
            }
        )

    async def collect_output(self, session_id: str, events: int = 200) -> bytes:
        """Read until the model stops speaking, returning the audio it produced."""
        session = self._session(session_id)
        session.spoken = bytearray()
        transport = self._transport(session_id)
        for _ in range(events):
            event = await transport.recv_event()
            kind = event.get("type")
            if kind == "session.output_audio.delta":
                session.spoken.extend(base64.b64decode(event.get("delta", "")))
                continue
            if kind == "error":
                raise GptLiveProtocolError(str(event.get("error", "stream failed")))
            if kind == "session.closed":
                break
            if session.spoken:
                # Any non-audio event after audio means the model finished this turn.
                break
        return bytes(session.spoken)

    async def interrupt(self, session_id: str) -> None:
        """Stop playing, and note that the model owns the end of its own turn."""
        self._session(session_id).interrupted = True

    async def close_session(self, session_id: str) -> None:
        transport = self._transports.pop(session_id, None)
        self._sessions.pop(session_id, None)
        if transport is None:
            return
        try:
            await transport.send_json({"type": "session.close"})
        finally:
            await transport.close()

    def _session(self, session_id: str) -> GptLiveSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise GptLiveProtocolError(f"no live session {session_id}")
        return session

    def _transport(self, session_id: str) -> GptLiveTransport:
        transport = self._transports.get(session_id)
        if transport is None:
            raise GptLiveProtocolError(f"no transport for {session_id}")
        return transport

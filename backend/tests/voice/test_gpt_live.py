"""GPT-Live over a fake socket: the frames we send, and the frames we refuse to send.

Nothing here needs a network. The point is the protocol contract: audio only in, PCM16 frames kept
whole, model-owned turns, and no tenant or persona inside a request that leaves our backend.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from app.modules.voice.runtime.gpt_live import (
    PCM_RATE,
    GptLiveConfig,
    GptLiveProtocolError,
    GptLiveProvider,
    GptLiveUnavailable,
)

STARTED = {"type": "session.started", "session": {"id": "live_test_1"}}


class FakeTransport:
    """Records what we send and replays a scripted list of events."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.events = list(events or [])
        self.closed = False

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def recv_event(self) -> dict[str, Any]:
        if not self.events:
            return {"type": "session.idle"}
        return self.events.pop(0)

    async def close(self) -> None:
        self.closed = True


def _provider(events: list[dict[str, Any]] | None = None) -> tuple[GptLiveProvider, FakeTransport]:
    transport = FakeTransport(events if events is not None else [STARTED])
    config = GptLiveConfig(api_key="vck_test", model="openai/gpt-live-1.1", voice="marin")
    return GptLiveProvider(config, lambda _config: transport), transport


class TestTheStartFrame:
    async def test_it_names_the_model_the_voice_and_the_pcm_rate(self) -> None:
        provider, transport = _provider()
        await provider.create_session({"instructions": "اتكلم بالمصري."})
        start = transport.sent[0]
        assert start["type"] == "session.start"
        session = start["session"]
        assert session["model"] == "openai/gpt-live-1.1"
        assert session["audio"]["output"]["voice"] == "marin"
        assert session["audio"]["format"] == {"type": "audio/pcm", "rate": PCM_RATE}
        assert session["instructions"] == "اتكلم بالمصري."

    async def test_it_refuses_to_carry_a_tenant_or_a_persona(self) -> None:
        provider, transport = _provider()
        with pytest.raises(GptLiveProtocolError) as refused:
            await provider.create_session({"tenant_id": "t-1", "persona": "merchant_assistant"})
        assert "tenant_id" in str(refused.value)
        assert transport.sent == []

    async def test_a_refused_session_reports_the_gateway_reason(self) -> None:
        provider, transport = _provider(
            [{"type": "error", "error": {"message": "model not available"}}]
        )
        with pytest.raises(GptLiveProtocolError) as refused:
            await provider.create_session({})
        assert "model not available" in str(refused.value)
        assert transport.closed is True

    async def test_a_silent_gateway_never_leaves_a_session_half_open(self) -> None:
        provider, transport = _provider([])
        with pytest.raises(GptLiveProtocolError):
            await provider.create_session({})
        assert transport.closed is True


class TestTheAudioPath:
    async def test_frames_never_split_a_pcm16_sample(self) -> None:
        provider, transport = _provider()
        session_id = await provider.create_session({})
        await provider.stream_audio(session_id, b"\x01\x02\x03")
        await provider.stream_audio(session_id, b"\x04\x05\x06")
        frames = [f for f in transport.sent if f["type"] == "session.input_audio.append"]
        lengths = [len(base64.b64decode(f["audio"])) for f in frames]
        # The odd byte waits for its partner: 2 bytes, then the leftover plus the next three.
        assert lengths == [2, 4]
        assert sum(lengths) == 6

    async def test_a_single_odd_byte_sends_nothing_yet(self) -> None:
        provider, transport = _provider()
        session_id = await provider.create_session({})
        await provider.stream_audio(session_id, b"\x01")
        assert [f for f in transport.sent if f["type"] == "session.input_audio.append"] == []

    async def test_the_audio_the_model_returns_is_concatenated(self) -> None:
        events = [
            STARTED,
            {"type": "session.output_audio.delta", "delta": base64.b64encode(b"\xaa\xbb").decode()},
            {"type": "session.output_audio.delta", "delta": base64.b64encode(b"\xcc\xdd").decode()},
            {"type": "session.transcript.delta", "delta": "أهلاً"},
        ]
        provider, _transport = _provider(events)
        session_id = await provider.create_session({})
        audio = await provider.collect_output(session_id)
        assert audio == b"\xaa\xbb\xcc\xdd"


class TestTurnsBelongToTheModel:
    async def test_interrupt_sends_nothing_and_only_stops_our_playback(self) -> None:
        provider, transport = _provider()
        session_id = await provider.create_session({})
        await provider.interrupt(session_id)
        assert [f["type"] for f in transport.sent] == ["session.start"]

    async def test_closing_sends_session_close_and_forgets_the_session(self) -> None:
        provider, transport = _provider()
        session_id = await provider.create_session({})
        await provider.close_session(session_id)
        assert transport.sent[-1] == {"type": "session.close"}
        assert transport.closed is True
        with pytest.raises(GptLiveProtocolError):
            await provider.stream_audio(session_id, b"\x01\x02")


class TestConfiguration:
    def test_a_plain_http_url_is_refused(self) -> None:
        with pytest.raises(GptLiveProtocolError):
            GptLiveConfig(api_key="k", url="https://ai-gateway.vercel.sh/v1/live/sessions")

    def test_no_key_means_no_voice_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "gpt_live_api_key", "", raising=False)
        assert GptLiveConfig.from_settings() is None

    def test_an_empty_key_is_refused(self) -> None:
        with pytest.raises(GptLiveUnavailable):
            GptLiveConfig(api_key="")


class TestTheSessionVoice:
    async def test_a_session_voice_overrides_the_configured_default(self) -> None:
        provider, transport = _provider()
        await provider.create_session({"voice": "nuri", "instructions": "x"})
        assert transport.sent[0]["session"]["audio"]["output"]["voice"] == "nuri"

    async def test_no_session_voice_keeps_the_configured_one(self) -> None:
        provider, transport = _provider()
        await provider.create_session({})
        assert transport.sent[0]["session"]["audio"]["output"]["voice"] == "marin"

    async def test_an_empty_session_voice_is_refused(self) -> None:
        provider, transport = _provider()
        with pytest.raises(GptLiveProtocolError):
            await provider.create_session({"voice": "   "})
        assert transport.sent == []

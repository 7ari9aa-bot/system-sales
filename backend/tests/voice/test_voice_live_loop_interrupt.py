"""Barge-in: pressing interrupt must actually silence the speaker.

Measured defect: ``GptLiveProvider.interrupt`` only set a flag on the provider
session and ``LiveCallLoop.pump`` never read it, so model audio kept reaching the
sink after the caller interrupted. Barge-in was a launch requirement, so the loop
owns it locally: the deltas are dropped, and playing resumes when the caller talks
again or when a delegation is answered.
"""

from __future__ import annotations

import base64

import pytest

from app.modules.voice.application.live_loop import LiveCallLoop
from app.modules.voice.runtime.gpt_live import GptLiveProtocolError

AUDIO = base64.b64encode(b"\x01\x02" * 240).decode()


class FakeProvider:
    def __init__(self, frames: list[dict]) -> None:
        self._frames = list(frames)
        self.interrupts: list[str] = []

    async def create_session(self, config):
        return "provider-1"

    async def next_event(self, session_id):
        return self._frames.pop(0)

    async def stream_audio(self, session_id, pcm):
        return None

    async def interrupt(self, session_id):
        # Async on purpose: the real provider's interrupt is a coroutine, and
        # calling it without awaiting it was the bug this test would have missed.
        self.interrupts.append(session_id)

    async def close_session(self, session_id):
        return None


class FakeDelegations:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def on_event(self, session_id, event, *, transcript):
        self.seen.append(transcript)
        return "answered"


def _loop(frames):
    sink: list[bytes] = []
    provider = FakeProvider(frames)
    loop = LiveCallLoop(provider, FakeDelegations(), audio_sink=sink.append)
    return loop, provider, sink


@pytest.mark.asyncio
async def test_audio_after_an_interrupt_is_not_played():
    loop, provider, sink = _loop([{"type": "session.output_audio.delta", "delta": AUDIO}])
    await loop.start(voice_session_id="vs-1", config={})

    await loop.interrupt()
    outcome = await loop.pump()

    assert outcome == "muted"
    assert sink == []
    assert loop.muted is True
    assert provider.interrupts == ["provider-1"]


@pytest.mark.asyncio
async def test_the_caller_talking_again_brings_the_speaker_back():
    loop, _provider, sink = _loop(
        [
            {"type": "session.input_transcript.delta", "delta": " لأ"},
            {"type": "session.output_audio.delta", "delta": AUDIO},
        ]
    )
    await loop.start(voice_session_id="vs-1", config={})
    await loop.interrupt()

    assert await loop.pump() == "transcript"
    assert await loop.pump() == "audio"
    assert sink and loop.muted is False


@pytest.mark.asyncio
async def test_an_answer_is_not_swallowed_by_the_mute():
    loop, _provider, sink = _loop(
        [
            {"type": "session.delegation.created", "id": "item_1", "target": "client"},
            {"type": "session.output_audio.delta", "delta": AUDIO},
        ]
    )
    await loop.start(voice_session_id="vs-1", config={})
    await loop.interrupt()

    assert await loop.pump() == "answered"
    assert await loop.pump() == "audio"
    assert sink


@pytest.mark.asyncio
async def test_interrupting_a_closed_call_does_nothing():
    loop, provider, _sink = _loop([])
    await loop.start(voice_session_id="vs-1", config={})
    await loop.close()

    await loop.interrupt()

    assert loop.muted is False
    assert provider.interrupts == []


@pytest.mark.asyncio
async def test_audio_still_flows_when_nobody_interrupted():
    loop, _provider, sink = _loop([{"type": "session.output_audio.delta", "delta": AUDIO}])
    await loop.start(voice_session_id="vs-1", config={})

    assert await loop.pump() == "audio"
    assert sink


@pytest.mark.asyncio
async def test_a_closed_call_still_refuses_audio():
    loop, _provider, _sink = _loop([])
    await loop.start(voice_session_id="vs-1", config={})
    await loop.close()

    with pytest.raises(GptLiveProtocolError):
        await loop.push_audio(b"\x00\x00")

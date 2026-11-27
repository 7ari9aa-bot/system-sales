"""One live call, driven from our side: audio out, delegations answered, one close.

The loop is the piece that makes the earlier work real — without it a delegation
is parsed by nobody and model audio reaches no speaker. These tests pin the
pump's contract with a scripted provider: frames it understands are acted on,
frames it does not are left alone, and a closed call accepts nothing.
"""

from __future__ import annotations

import base64

import pytest

from app.modules.voice.application.live_loop import LiveCallLoop
from app.modules.voice.runtime.gpt_live import GptLiveProtocolError

VOICE_SESSION = "11111111-1111-1111-1111-111111111111"


class _Provider:
    def __init__(self, events=None):
        self.events = list(events or [])
        self.sent: list[bytes] = []
        self.closes = 0

    async def create_session(self, config):
        return "prov_1"

    async def stream_audio(self, session_id, pcm):
        self.sent.append(pcm)

    async def next_event(self, session_id):
        return self.events.pop(0)

    async def close_session(self, session_id):
        self.closes += 1


class _Delegations:
    def __init__(self, outcome="answered"):
        self.outcome = outcome
        self.seen: list[tuple[str, str]] = []

    async def on_event(self, session_id, event, *, transcript):
        self.seen.append((session_id, transcript))
        return self.outcome


def _said(text: str) -> dict:
    return {"type": "session.input_transcript.delta", "delta": text}


def _spoken(text: str) -> dict:
    return {"type": "session.output_transcript.delta", "delta": text}


def _delegation(delegation_id: str) -> dict:
    return {
        "type": "session.delegation.created",
        "delegation": {"id": delegation_id, "target": "client"},
    }


def _delta(pcm: bytes) -> dict:
    return {"type": "session.output_audio.delta", "delta": base64.b64encode(pcm).decode()}


async def test_model_audio_reaches_the_speaker_and_caller_audio_reaches_the_model():
    sink: list[bytes] = []
    provider = _Provider([_delta(b"\x01\x02" * 10)])
    loop = LiveCallLoop(provider, _Delegations(), audio_sink=sink.append)

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})
    await loop.push_audio(b"\x00\x01" * 5)
    outcome = await loop.pump()

    assert outcome == "audio"
    assert sink == [b"\x01\x02" * 10]
    assert provider.sent == [b"\x00\x01" * 5]


async def test_a_delegation_is_answered_with_what_the_caller_said():
    delegations = _Delegations()
    provider = _Provider(
        [{"type": "session.delegation.created", "delegation": {"id": "item_1", "target": "client"}}]
    )
    loop = LiveCallLoop(
        provider,
        delegations,
        audio_sink=lambda pcm: None,
        transcript_provider=lambda: "كام مبيعات النهاردة؟",
    )

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})
    outcome = await loop.pump()

    assert outcome == "answered"
    assert delegations.seen == [("prov_1", "كام مبيعات النهاردة؟")]
    assert loop.counts == {"answered": 1}


async def test_a_closed_call_accepts_no_more_audio():
    provider = _Provider([{"type": "session.closed", "reason": "idle_timeout"}])
    loop = LiveCallLoop(provider, _Delegations(), audio_sink=lambda pcm: None)

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})
    assert await loop.pump() == "closed"

    assert loop.closed is True
    assert await loop.pump() == "closed"
    with pytest.raises(GptLiveProtocolError):
        await loop.push_audio(b"\x00\x01")


async def test_an_unknown_frame_is_ignored_rather_than_guessed():
    provider = _Provider([{"type": "session.something_new"}])
    loop = LiveCallLoop(provider, _Delegations(), audio_sink=lambda pcm: None)

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})

    assert await loop.pump() == "ignored"
    assert loop.closed is False


async def test_audio_that_is_not_base64_is_refused_not_silently_dropped():
    provider = _Provider([{"type": "session.output_audio.delta", "delta": "%%%not-base64%%%"}])
    loop = LiveCallLoop(provider, _Delegations(), audio_sink=lambda pcm: None)

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})

    with pytest.raises(GptLiveProtocolError):
        await loop.pump()


async def test_the_call_is_closed_once_even_if_close_is_called_twice():
    provider = _Provider()
    loop = LiveCallLoop(provider, _Delegations(), audio_sink=lambda pcm: None)

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})
    await loop.close()
    await loop.close()

    assert provider.closes == 1
    assert loop.closed is True


async def test_the_callers_words_come_from_the_transcript_fragments():
    """A delegation is answered with what was said, not with an invented question."""
    delegations = _Delegations()
    provider = _Provider(
        [
            _said("كام "),
            _said("مبيعات النهاردة؟"),
            _spoken("هقولك حالًا"),
            _delegation("item_1"),
        ]
    )
    loop = LiveCallLoop(provider, delegations, audio_sink=lambda pcm: None)

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})
    assert await loop.pump() == "transcript"
    assert await loop.pump() == "transcript"
    # What the MODEL said is never fed back to it as the question.
    assert await loop.pump() == "ignored"
    assert await loop.pump() == "answered"

    assert delegations.seen == [("prov_1", "كام مبيعات النهاردة؟")]


async def test_the_second_delegation_is_not_answered_with_the_first_question():
    delegations = _Delegations()
    provider = _Provider(
        [
            _said("كام مبيعات النهاردة؟"),
            _delegation("item_1"),
            _said("وإيه أكتر منتج مبيع؟"),
            _delegation("item_2"),
        ]
    )
    loop = LiveCallLoop(provider, delegations, audio_sink=lambda pcm: None)

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})
    for _ in range(4):
        await loop.pump()

    assert [t for _, t in delegations.seen] == [
        "كام مبيعات النهاردة؟",
        "وإيه أكتر منتج مبيع؟",
    ]


async def test_a_delegation_with_no_fresh_fragment_uses_the_recent_history():
    """The caller may delegate before a fragment lands; the call's tail answers it."""
    delegations = _Delegations()
    provider = _Provider(
        [
            _said("أنا عايز أعرف المبيعات"),
            _delegation("item_1"),
            _delegation("item_2"),
        ]
    )
    loop = LiveCallLoop(provider, delegations, audio_sink=lambda pcm: None)

    await loop.start(voice_session_id=VOICE_SESSION, config={"instructions": "x"})
    for _ in range(3):
        await loop.pump()

    # The second delegation has nothing new to say, so it falls back to the tail
    # rather than sending an empty question that would cost a paid turn.
    assert [t for _, t in delegations.seen] == [
        "أنا عايز أعرف المبيعات",
        "أنا عايز أعرف المبيعات",
    ]


def test_the_transcript_history_is_bounded():
    from app.modules.voice.application.live_loop import TranscriptBuffer

    buffer = TranscriptBuffer(limit=50)
    for _ in range(40):
        buffer.append("كلمة كتير ")

    assert len(buffer.take()) <= 50

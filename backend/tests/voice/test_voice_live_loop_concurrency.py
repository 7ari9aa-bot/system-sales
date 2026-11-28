"""A slow answer must not stop the call from hearing the caller.

Measured defect: ``LiveCallLoop.pump`` awaited ``ClientDelegationService.on_event``,
which awaits the whole analytic assistant turn. While that ran, no provider frame was
read at all: the caller talking over the answer (the barge-in), the model's audio and a
second question all queued behind the analytic work. The pump's own docstring promised
"a slow delegation never blocks audio for longer than one frame" — it did.

These tests pin the fix:

* the delegated turn runs as a cancellable background task, so ``pump`` keeps reading
  provider frames while the answer is being written;
* a newer spoken turn, an interrupt or the end of the call cancels the work in flight;
* the answer to a question the caller has moved past is never spoken, which is the
  ``spoken_turns`` supersede rule from #118 — and a turn that survives cancellation
  (a DB call that cannot be aborted) is still dropped by that same ledger check.

Every test here is pure Python: no database, no network, no gateway key.
"""

from __future__ import annotations

import asyncio
import base64

from app.modules.voice.application.client_delegation import ClientDelegationService
from app.modules.voice.application.live_loop import LiveCallLoop
from app.modules.voice.application.spoken_turns import TurnLedger

SESSION = "11111111-1111-1111-1111-111111111111"
PROVIDER_SESSION = "prov_1"
AUDIO = base64.b64encode(b"\x01\x02" * 4).decode()


def _said(text: str) -> dict:
    return {"type": "session.input_transcript.delta", "delta": text}


def _delta(pcm: bytes = b"\x01\x02" * 4) -> dict:
    return {"type": "session.output_audio.delta", "delta": base64.b64encode(pcm).decode()}


def _delegation(delegation_id: str) -> dict:
    return {
        "type": "session.delegation.created",
        "delegation": {"id": delegation_id, "target": "client"},
    }


class SocketProvider:
    """A provider whose ``next_event`` blocks when the queue is empty, like a socket."""

    def __init__(self, frames: list[dict]) -> None:
        self._frames: asyncio.Queue[dict] = asyncio.Queue()
        for frame in frames:
            self._frames.put_nowait(frame)
        self.consumed = 0
        self.frames: list[tuple[str, str, str]] = []
        self.interrupts: list[str] = []
        self.closes = 0

    async def create_session(self, config):
        return PROVIDER_SESSION

    async def next_event(self, session_id):
        event = await self._frames.get()
        self.consumed += 1
        return event

    async def stream_audio(self, session_id, pcm):
        return None

    async def interrupt(self, session_id):
        self.interrupts.append(session_id)

    async def close_session(self, session_id):
        self.closes += 1

    async def append_thinking(self, session_id, *, delegation_id, content, event_id=None):
        self.frames.append(("thinking", delegation_id, content))
        return "e"

    async def append_commentary(self, session_id, *, delegation_id, content, event_id=None):
        self.frames.append(("commentary", delegation_id, content))
        return "e"

    def commentaries(self) -> list[tuple[str, str]]:
        return [
            (delegation_id, content)
            for kind, delegation_id, content in self.frames
            if kind == "commentary"
        ]


class SlowDelegations:
    """An assistant turn that takes as long as the test wants it to."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def on_event(self, session_id, event, *, transcript):
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        self.finished.set()
        return "answered"


async def _started(loop) -> None:
    await loop.start(voice_session_id=SESSION, config={"instructions": "x"})


async def test_the_pump_keeps_reading_while_an_answer_is_being_written():
    """The reproduction: a barge-in and model audio must not queue behind the answer."""
    delegations = SlowDelegations()
    provider = SocketProvider([_delegation("item_1"), _said("لأ استنى"), _delta()])
    sink: list[bytes] = []
    loop = LiveCallLoop(provider, delegations, audio_sink=sink.append)
    await _started(loop)

    first = await asyncio.wait_for(loop.pump(), timeout=1)
    assert first == "delegating"
    await asyncio.wait_for(delegations.started.wait(), timeout=1)
    assert not delegations.finished.is_set()

    # The caller talks over the answer. That frame is the barge-in and it must be
    # read NOW, not once the analytic answer is done.
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "transcript"
    # And the model's audio keeps flowing to the speaker in the same window.
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "audio"
    assert sink == [b"\x01\x02" * 4]
    assert provider.consumed == 3
    # The answer is STILL running: none of the above waited for it.
    assert not delegations.finished.is_set()

    delegations.release.set()
    await loop.drain()
    assert loop.counts["answered"] == 1


async def test_an_interrupt_is_honoured_while_the_answer_is_still_running():
    delegations = SlowDelegations()
    provider = SocketProvider([_delegation("item_1"), _delta()])
    sink: list[bytes] = []
    loop = LiveCallLoop(provider, delegations, audio_sink=sink.append)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(delegations.started.wait(), timeout=1)

    await loop.interrupt()

    assert loop.muted is True
    assert provider.interrupts == [PROVIDER_SESSION]
    # The audio the model had already queued is dropped, not played late.
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "muted"
    assert sink == []
    # The answer nobody is waiting for any more is cancelled, not left running.
    await asyncio.wait_for(delegations.cancelled.wait(), timeout=1)
    await loop.drain()
    assert loop.counts["cancelled"] == 1
    assert loop.counts.get("answered") is None


async def test_a_newer_spoken_turn_cancels_the_answer_in_flight():
    """The caller asks something else: the old answer is cancelled and never spoken."""
    provider = SocketProvider([_delegation("item_1"), _delegation("item_2")])
    ledger = TurnLedger()
    seen: list[str] = []
    started = asyncio.Event()
    cancelled = asyncio.Event()
    first_turn: list = []

    async def runner(request) -> str:
        seen.append(request.idempotency_key)
        if request.idempotency_key == "delegation:item_1":
            first_turn.append(request.turn)
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        return "الجواب التاني"

    service = ClientDelegationService(provider, runner, call_id=SESSION, ledger=ledger)
    loop = LiveCallLoop(provider, service, audio_sink=lambda pcm: None)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(started.wait(), timeout=1)
    assert ledger.is_current(first_turn[0]) is True

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    await loop.drain()

    # The first question was taken over before its answer existed, so nothing about
    # it reached the speaker — and the second answer did.
    assert [d for d, _ in provider.commentaries()] == ["item_2"]
    assert provider.commentaries() == [("item_2", "الجواب التاني")]
    assert ledger.is_current(first_turn[0]) is False
    assert seen == ["delegation:item_1", "delegation:item_2"]


async def test_a_stale_answer_that_survives_cancellation_is_still_not_spoken():
    """A DB call that cannot be aborted must not turn a cancelled turn into speech.

    The task is cancelled, but the runner had already finished its paid work. The
    ledger is what decides: the turn is no longer current, so the answer is recorded
    ``superseded`` and never handed to the model to say.
    """
    provider = SocketProvider([_delegation("item_1"), _delegation("item_2")])
    ledger = TurnLedger()
    started = asyncio.Event()

    async def runner(request) -> str:
        if request.idempotency_key == "delegation:item_1":
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # The answer was already paid for; the abort landed too late to stop it.
                pass
            return "جواب قديم"
        return "جواب جديد"

    service = ClientDelegationService(provider, runner, call_id=SESSION, ledger=ledger)
    loop = LiveCallLoop(provider, service, audio_sink=lambda pcm: None)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(started.wait(), timeout=1)
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await loop.drain()

    assert ("item_1", "جواب قديم") not in provider.commentaries()
    assert provider.commentaries() == [("item_2", "جواب جديد")]
    assert loop.counts["superseded"] == 1


async def test_closing_the_call_cancels_the_answer_in_flight():
    delegations = SlowDelegations()
    provider = SocketProvider([_delegation("item_1")])
    loop = LiveCallLoop(provider, delegations, audio_sink=lambda pcm: None)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(delegations.started.wait(), timeout=1)

    await loop.close()
    await asyncio.wait_for(delegations.cancelled.wait(), timeout=1)
    await loop.drain()

    assert provider.closes == 1
    assert loop.counts["cancelled"] == 1


async def test_a_redelivered_delegation_does_not_cancel_its_own_answer():
    """A duplicate is not a newer question: it must not drop the answer in flight."""
    delegations = SlowDelegations()
    provider = SocketProvider([_delegation("item_1"), _delegation("item_1")])
    loop = LiveCallLoop(provider, delegations, audio_sink=lambda pcm: None)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(delegations.started.wait(), timeout=1)
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "duplicate"

    delegations.release.set()
    await loop.drain()

    assert delegations.cancelled.is_set() is False
    assert loop.counts["answered"] == 1


async def test_a_failing_delegated_turn_does_not_kill_the_pump():
    provider = SocketProvider([_delegation("item_1"), _delta()])
    sink: list[bytes] = []

    class Exploding:
        async def on_event(self, session_id, event, *, transcript):
            raise RuntimeError("the assistant is down")

    loop = LiveCallLoop(provider, Exploding(), audio_sink=sink.append)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await loop.drain()
    # The failure is counted, and the call keeps carrying audio.
    assert loop.counts["failed"] == 1
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "audio"
    assert sink


# ------------------------------- the caller's own voice is the barge-in -------------------
#
# Measured defect: caller speech only appended to the transcript buffer and lifted the mute.
# The answer being prepared kept being prepared, and the model's audio kept being played, until
# a NEW delegation arrived or somebody pressed the interrupt button — i.e. the assistant talked
# over the person who was interrupting it, and only stopped once they had finished their
# sentence. These pin the fix: the first words of the caller stop the speaker, immediately.


async def test_the_speaker_stops_the_moment_the_caller_starts_talking():
    """The user-visible contract: audio in the sink, the caller speaks, audio stops.

    Read as a call, frame by frame: the model is answering (its audio reaches the speaker), the
    caller talks over it, and from that frame on nothing else is played — without a delegation,
    without an interrupt button, and without waiting for the caller's sentence to end.
    """
    provider = SocketProvider([_delegation("item_1"), _delta(), _said("استنى"), _delta()])
    delegations = SlowDelegations()
    sink: list[bytes] = []
    loop = LiveCallLoop(provider, delegations, audio_sink=sink.append)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(delegations.started.wait(), timeout=1)
    # the model's answer is now audible
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "audio"
    assert len(sink) == 1

    # ONE word from the caller is the barge-in: the speaker goes down on this frame.
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "barged_in"
    assert loop.muted is True

    # and everything the model had queued behind that word is dropped, not played late
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "muted"
    assert len(sink) == 1, "no model audio may reach the speaker after the caller speaks"


async def test_the_speaker_stays_down_while_the_caller_keeps_talking():
    """A barge-in is not one frame: the caller's next words must not bring the speaker back."""
    provider = SocketProvider([_delegation("item_1"), _delta(), _said("استنى"), _said("شوية")])
    delegations = SlowDelegations()
    sink: list[bytes] = []
    loop = LiveCallLoop(provider, delegations, audio_sink=sink.append)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "audio"
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "barged_in"
    # the second fragment is more of the same interruption, not a new turn
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "transcript"
    assert loop.muted is True


async def test_the_answer_the_caller_overtalked_is_cancelled_not_finished():
    """The answer still being written when the caller interrupts is cancelled, not paid for."""
    provider = SocketProvider([_delegation("item_1"), _delta(), _said("لأ خلاص")])
    delegations = SlowDelegations()
    loop = LiveCallLoop(provider, delegations, audio_sink=lambda _pcm: None)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(delegations.started.wait(), timeout=1)
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "audio"

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "barged_in"
    await asyncio.wait_for(delegations.cancelled.wait(), timeout=1)
    await loop.drain()
    assert loop.counts["cancelled"] == 1
    assert loop.counts.get("answered") is None


async def test_an_answer_being_written_is_cancelled_once_the_tail_grace_has_passed():
    """The other half: no audio yet, but the caller has clearly moved on to a new utterance.

    A provider flushes the end of an utterance after it has already delegated, so speech inside
    the grace belongs to the question being answered. Speech after it does not: the caller is
    saying something else, and the answer to the old question must stop being written.
    """
    provider = SocketProvider([_delegation("item_1"), _said("طيب وامتى")])
    delegations = SlowDelegations()
    loop = LiveCallLoop(provider, delegations, audio_sink=lambda _pcm: None)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(delegations.started.wait(), timeout=1)
    # the answer has been running long enough that this is a new utterance
    loop._now = lambda: loop._delegated_at + 5  # noqa: SLF001 — the test's clock

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "barged_in"
    await asyncio.wait_for(delegations.cancelled.wait(), timeout=1)
    await loop.drain()
    assert loop.counts["cancelled"] == 1


async def test_a_flushed_tail_does_not_cancel_the_answer_to_the_question_just_asked():
    """The regression the grace exists to prevent: silence with no second delegation coming."""
    provider = SocketProvider([_delegation("item_1"), _said("كمان")])
    delegations = SlowDelegations()
    loop = LiveCallLoop(provider, delegations, audio_sink=lambda _pcm: None)
    await _started(loop)

    assert await asyncio.wait_for(loop.pump(), timeout=1) == "delegating"
    await asyncio.wait_for(delegations.started.wait(), timeout=1)
    # no clock advance: this is the tail of the same sentence
    assert await asyncio.wait_for(loop.pump(), timeout=1) == "transcript"
    assert not delegations.cancelled.is_set()

    delegations.release.set()
    await loop.drain()
    assert loop.counts["answered"] == 1
    assert loop.counts.get("cancelled") is None

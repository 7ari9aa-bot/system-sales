"""One live call, driven from our side.

GPT-Live holds the microphone and the speaker; this loop holds the CALL. It owns
the provider session, pushes caller audio in, takes model audio out to the sink,
and hands every delegation to ``ClientDelegationService`` — which answers with the
same assistant turn the text path runs.

What it deliberately does NOT do: decide who the caller is, which shop they
reached, what they may see, or whether the call may continue. Those are the
control plane's, and by the time a frame reaches this loop they are already
decided.

The one thing this loop must never do is stop listening while it thinks. A spoken
answer is a paid assistant turn that takes seconds, and the caller is still in the
conversation while it runs: they talk over the model, ask something else, or hang
up. So a delegation is not awaited here. It is started as a task and the pump goes
straight back to the socket; a newer spoken turn or an interrupt cancels the task
in flight, and the answer to a question the caller has moved past is never spoken
— ``spoken_turns`` owns that decision and it is checked again before anything is
sent.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app.modules.voice.application.client_delegation import DELEGATION_CREATED, parse_delegation
from app.modules.voice.runtime.gpt_live import GptLiveProtocolError

logger = logging.getLogger(__name__)

OUTPUT_AUDIO_DELTA = "session.output_audio.delta"
INPUT_TRANSCRIPT_DELTA = "session.input_transcript.delta"
OUTPUT_TRANSCRIPT_DELTA = "session.output_transcript.delta"
SESSION_CLOSED = "session.closed"

#: What ``pump`` returns when it has handed a delegation to a background task. The
#: answer itself arrives later, as a commentary frame, and is counted then.
DELEGATING = "delegating"

#: How many delegation ids this loop remembers. The service keeps its own memory;
#: this one exists so a redelivery cannot be mistaken for a newer question while
#: the first copy is still starting up in the background.
REMEMBERED_DELEGATIONS = 256

#: How much of what the caller said is kept. Enough to understand "yes", a
#: correction like "الخميس مش الجمعة", or a detail given three sentences ago;
#: short enough that one long call cannot grow without bound.
TRANSCRIPT_HISTORY_CHARS = 2000


class TranscriptBuffer:
    """What the caller said, so a delegation can be answered with it.

    The gateway sends transcript fragments, never the task text on the delegation
    itself, and a fragment is not a turn. Two things are therefore kept apart:

    * ``pending`` — everything said since the last answered delegation, which is
      the question being asked right now;
    * ``history`` — a bounded tail of the whole call, used when a delegation
      arrives before any fresh fragment (the caller was already talking).

    ``take()`` empties ``pending`` so the next delegation cannot be answered with
    the previous question.
    """

    def __init__(self, limit: int = TRANSCRIPT_HISTORY_CHARS) -> None:
        self._limit = limit
        self._pending: list[str] = []
        self._history: list[str] = []

    def append(self, text: str) -> None:
        if not text:
            return
        self._pending.append(text)
        self._history.append(text)
        self._trim()

    def take(self) -> str:
        """The current question, and forget it."""
        question = "".join(self._pending).strip()
        self._pending.clear()
        if question:
            return question
        return "".join(self._history)[-self._limit :].strip()

    def _trim(self) -> None:
        # Both sides are bounded: a caller who talks for ten minutes before a
        # delegation must not turn the question into an unbounded prompt.
        for name in ("_history", "_pending"):
            joined = "".join(getattr(self, name))
            if len(joined) > self._limit:
                setattr(self, name, [joined[-self._limit :]])


class LiveCallLoop:
    """The pump between one GPT-Live session and one voice session."""

    def __init__(
        self,
        provider,
        delegations,
        *,
        audio_sink: Callable[[bytes], None],
        transcript_provider: Callable[[], str] | None = None,
    ) -> None:
        self._provider = provider
        self._delegations = delegations
        self._audio_sink = audio_sink
        self._transcripts = TranscriptBuffer()
        self._transcript_provider = transcript_provider
        self._voice_session_id: str | None = None
        self._provider_session: str | None = None
        self._closed = False
        #: True between a caller's interrupt and the model's next turn. The model
        #: owns the end of its own turn, so we cannot ask it to stop; what we can
        #: do is stop playing it. Dropping the deltas IS the barge-in.
        self._muted = False
        #: The delegation whose answer is being written right now. One per call: a
        #: newer question makes it stale, and stale work is cancelled rather than
        #: stacked, so the speaker can only ever be waiting for the newest answer.
        self._turn_task: asyncio.Task | None = None
        #: Tasks that were cancelled and have not finished unwinding yet. Kept until
        #: they are done so a cancellation cannot leave an unretrieved exception
        #: behind, and so ``drain`` can honestly say the call has nothing running.
        self._retiring: set[asyncio.Task] = set()
        #: Delegation ids already handed to a task, claimed synchronously with the
        #: frame. A redelivery is not a newer question and must not cancel the answer
        #: its own first copy is still writing.
        self._remembered: dict[str, None] = {}
        self.counts: dict[str, int] = {}

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def provider_session_id(self) -> str | None:
        """The provider's id for this call, or ``None`` before the model session opened.

        The control plane records this on the session row. Without it a session only
        says "we asked for a call"; with it, the row names the call that actually ran.
        """
        return self._provider_session

    async def start(self, *, voice_session_id, config: dict[str, Any]) -> str:
        """Open the model session. Returns the provider's session id."""
        if self._provider_session is not None:
            raise GptLiveProtocolError("this call already has a session")
        self._voice_session_id = str(voice_session_id)
        self._provider_session = await self._provider.create_session(config)
        logger.info(
            "voice.live_started voice_session=%s provider_session=%s",
            self._voice_session_id,
            self._provider_session,
        )
        return self._provider_session

    async def interrupt(self) -> None:
        """The caller talked over the model: silence our side and stop the answer.

        The provider is told as well (it owns the turn), but the guarantee this
        loop makes is local and immediate: no further model audio reaches the
        sink until the caller speaks again or a delegation is answered.

        Silencing the speaker is only half of a barge-in. The answer being
        computed for the question the caller just talked over is still running,
        and it would be handed to the model as soon as it finished — so the turn
        in flight is dropped from the ledger AND cancelled here. That is what
        makes the rest of the interruption hold after the audio has stopped: the
        work stops too, instead of burning a paid turn to say something the caller
        has already talked over.
        """
        if self._closed:
            return
        self._muted = True
        await self._drop_in_flight()
        interrupt = getattr(self._provider, "interrupt", None)
        if interrupt is not None and self._provider_session is not None:
            # The provider's interrupt is a coroutine: awaiting it is the whole
            # point. Calling it without await left the model session unaware and
            # printed "coroutine was never awaited" on a real run.
            result = interrupt(self._provider_session)
            if asyncio.iscoroutine(result):
                await result

    @property
    def muted(self) -> bool:
        return self._muted

    async def push_audio(self, pcm: bytes) -> None:
        """Send caller audio. A closed call accepts nothing: silence is not a frame."""
        if self._closed or self._provider_session is None:
            raise GptLiveProtocolError("the call is closed")
        await self._provider.stream_audio(self._provider_session, pcm)

    async def pump(self) -> str:
        """Read one frame and do what it asks. Returns what happened.

        The caller owns the loop: it decides how many frames to read and when to
        stop. A delegation is the one frame whose work is not finished here — it
        is started as a task and ``DELEGATING`` is returned immediately, so a slow
        analytic answer never stops the next frame (the caller's barge-in, the
        model's audio, a newer question) from being read.
        """
        if self._closed or self._provider_session is None:
            return "closed"
        event = await self._provider.next_event(self._provider_session)
        kind = str(event.get("type") or "")

        if kind == OUTPUT_AUDIO_DELTA:
            delta = event.get("delta")
            if not (isinstance(delta, str) and delta):
                return "ignored"
            if self._muted:
                # The caller interrupted: the rest of this model turn is not played.
                return self._count("muted")
            self._audio_sink(_decode(delta))
            return self._count("audio")

        if kind == INPUT_TRANSCRIPT_DELTA:
            # Only the caller's own words answer a delegation; what the model said
            # is never fed back to it as the question.
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                self._transcripts.append(delta)
                # The caller talking again is a new turn: the speaker comes back.
                self._muted = False
                return self._count("transcript")
            return "ignored"

        if kind == OUTPUT_TRANSCRIPT_DELTA:
            return "ignored"

        if kind == SESSION_CLOSED:
            # The model closed the call (timeout, provider decision). Nothing is
            # sent after this: the loop reports it and the control plane closes
            # the voice session, so usage stops with the call.
            self._closed = True
            return self._count("closed")

        if kind == DELEGATION_CREATED:
            # An answer is about to be spoken, so the mute must not swallow it.
            self._muted = False
            return self._count(await self._delegate(self._provider_session, event))

        return "ignored"

    async def close(self) -> None:
        """End the call once. Closing twice is not an error, it is a repeat.

        An answer still being written for a call nobody is on any more is cancelled
        rather than finished: the runner's own transaction rolls back, so a hung-up
        caller does not pay for a turn that no speaker will ever hear.
        """
        if self._closed:
            return
        self._closed = True
        self._cancel_turn()
        if self._provider_session is not None:
            await self._provider.close_session(self._provider_session)

    async def drain(self) -> None:
        """Wait until no delegated answer is in flight.

        The pump never needs this — not waiting is the whole point of the task — but
        a shutdown and a test do: it is the only way to say "nothing of this call is
        still running".
        """
        while True:
            pending = [
                task
                for task in (self._turn_task, *self._retiring)
                if task is not None and not task.done()
            ]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    async def _delegate(self, session_id: str, event: dict[str, Any]) -> str:
        """Start answering one delegation, or refuse to start it twice."""
        request = parse_delegation(event)
        if request is None:
            # A delegation with no id has nothing to reply to; inventing one is what
            # the gateway rejects. Left alone here exactly as the service leaves it.
            return "ignored"
        if request.delegation_id in self._remembered:
            logger.info(
                "voice.delegation_duplicate_in_flight session=%s delegation=%s",
                session_id,
                request.delegation_id,
            )
            return "duplicate"
        self._remember(request.delegation_id)

        # A newer question ends the previous one BEFORE this frame returns: from this
        # moment the answer being written is stale, whether or not it is still running.
        await self._drop_in_flight()

        task = asyncio.create_task(
            self._answer(session_id, event, self._current_transcript()),
            name=f"voice-delegation:{request.delegation_id}",
        )
        self._turn_task = task
        task.add_done_callback(self._turn_done)
        return DELEGATING

    async def _answer(self, session_id: str, event: dict[str, Any], transcript: str) -> str:
        """Answer one delegation away from the pump, and count what happened."""
        try:
            outcome = await self._delegations.on_event(session_id, event, transcript=transcript)
        except asyncio.CancelledError:
            # The caller moved on, or the call ended, before this answer existed. The
            # turn's rows belong to the runner, whose transaction rolls back; nothing
            # is spoken here and nothing is written here.
            self._count("cancelled")
            raise
        except Exception:  # noqa: BLE001 — a failed answer must not kill the call
            logger.exception("voice.delegation_task_failed session=%s", session_id)
            return self._count("failed")
        return self._count(outcome)

    async def _drop_in_flight(self) -> None:
        """Make the answer being written stale, then stop it.

        The ledger goes first on purpose. An answer that has already passed its last
        cancellation point cannot be un-run, but it can still be recognised as stale
        and refused a speaker — and that is the ledger's decision, not the
        scheduler's. Cancelling second is what stops the work that has not finished.
        """
        drop_turn = getattr(self._delegations, "interrupt", None)
        if drop_turn is not None and self._provider_session is not None:
            # Await it when it is a coroutine, so a refusal cannot be swallowed by a
            # missing await.
            result = drop_turn(self._provider_session)
            if asyncio.iscoroutine(result):
                await result
        self._cancel_turn()

    def _cancel_turn(self) -> None:
        task = self._turn_task
        if task is None:
            return
        self._turn_task = None
        if task.done():
            return
        # Held until it has unwound: a cancelled task that nobody awaits is a warning
        # waiting to happen, and `drain` has to be able to wait for it.
        self._retiring.add(task)
        task.cancel()

    def _turn_done(self, task: asyncio.Task) -> None:
        if task is self._turn_task:
            self._turn_task = None
        self._retiring.discard(task)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:  # pragma: no cover - a task that cancelled itself
            return
        if error is not None:  # pragma: no cover — _answer already logs and counts it
            logger.warning("voice.delegation_task_crashed", exc_info=error)

    def _remember(self, delegation_id: str) -> None:
        self._remembered[delegation_id] = None
        while len(self._remembered) > REMEMBERED_DELEGATIONS:
            self._remembered.pop(next(iter(self._remembered)))

    def _current_transcript(self) -> str:
        """What the caller asked, taken from the buffer unless a caller overrides it."""
        if self._transcript_provider is not None:
            return self._transcript_provider()
        return self._transcripts.take()

    def _count(self, outcome: str) -> str:
        self.counts[outcome] = self.counts.get(outcome, 0) + 1
        return outcome


def _decode(delta: str) -> bytes:
    """Gateway audio deltas are base64 PCM16; anything else is refused, not guessed."""
    import base64
    import binascii

    try:
        return base64.b64decode(delta, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GptLiveProtocolError("an audio delta was not base64 PCM16") from exc

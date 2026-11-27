"""One live call, driven from our side.

GPT-Live holds the microphone and the speaker; this loop holds the CALL. It owns
the provider session, pushes caller audio in, takes model audio out to the sink,
and hands every delegation to ``ClientDelegationService`` — which answers with the
same assistant turn the text path runs.

What it deliberately does NOT do: decide who the caller is, which shop they
reached, what they may see, or whether the call may continue. Those are the
control plane's, and by the time a frame reaches this loop they are already
decided.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.modules.voice.application.client_delegation import DELEGATION_CREATED
from app.modules.voice.runtime.gpt_live import GptLiveProtocolError

logger = logging.getLogger(__name__)

OUTPUT_AUDIO_DELTA = "session.output_audio.delta"
INPUT_TRANSCRIPT_DELTA = "session.input_transcript.delta"
OUTPUT_TRANSCRIPT_DELTA = "session.output_transcript.delta"
SESSION_CLOSED = "session.closed"

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
        self.counts: dict[str, int] = {}

    @property
    def closed(self) -> bool:
        return self._closed

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

    async def push_audio(self, pcm: bytes) -> None:
        """Send caller audio. A closed call accepts nothing: silence is not a frame."""
        if self._closed or self._provider_session is None:
            raise GptLiveProtocolError("the call is closed")
        await self._provider.stream_audio(self._provider_session, pcm)

    async def pump(self) -> str:
        """Read one frame and do what it asks. Returns what happened.

        The caller owns the loop: it decides how many frames to read and when to
        stop, so a slow delegation never blocks audio for longer than one frame.
        """
        if self._closed or self._provider_session is None:
            return "closed"
        event = await self._provider.next_event(self._provider_session)
        kind = str(event.get("type") or "")

        if kind == OUTPUT_AUDIO_DELTA:
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                self._audio_sink(_decode(delta))
                return self._count("audio")
            return "ignored"

        if kind == INPUT_TRANSCRIPT_DELTA:
            # Only the caller's own words answer a delegation; what the model said
            # is never fed back to it as the question.
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                self._transcripts.append(delta)
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
            outcome = await self._delegations.on_event(
                self._provider_session,
                event,
                transcript=self._current_transcript(),
            )
            return self._count(outcome)

        return "ignored"

    async def close(self) -> None:
        """End the call once. Closing twice is not an error, it is a repeat."""
        if self._closed:
            return
        self._closed = True
        if self._provider_session is not None:
            await self._provider.close_session(self._provider_session)

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

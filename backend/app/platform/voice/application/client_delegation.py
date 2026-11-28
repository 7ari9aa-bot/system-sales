"""GPT-Live listens and speaks; the thinking is ours.

Client delegation is the whole architecture in one event: the voice model says
"the caller wants something I must not answer myself", and hands us a
``session.delegation.created`` carrying an id and a target — never the task text.
We assemble what was said, run the SAME assistant turn the text path runs, and
send the answer back with ``session.commentary.append`` so the model says it in
its own voice. Progress that should not be spoken goes through
``session.thinking.append``.

Two rules this module exists to enforce:

* the model never touches the database or the tools — it only delegates;
* one delegation is answered once. The id is claimed before the work starts and
  is also the turn's idempotency key, so a redelivered event cannot buy the same
  answer twice.

A third rule was missing and is the reason barge-in used to leak: an answer is
only worth speaking while it is still the answer to the question being asked.
Every delegation therefore begins a turn (``spoken_turns``), which mints the turn
id and makes it the call's current turn — superseding whatever was being answered
— and the answer is handed to the model only if that turn is still current. A
caller who interrupts with the button clears the current turn outright. The work
itself keeps running; it is the SPEAKING that stops, which is what the caller
asked for.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.platform.voice.application.spoken_turns import SpokenTurn, TurnLedger

logger = logging.getLogger(__name__)

DELEGATION_CREATED = "session.delegation.created"

#: How many answered delegation ids are remembered per process. Idempotency in
#: the database is the real guard; this only stops a redelivery in the same call
#: from even reaching the turn.
REMEMBERED_DELEGATIONS = 256

#: What the caller hears when the backend could not finish. Never a silent hole:
#: the model is told something went wrong so it can say so and keep listening.
FAILURE_NOTE = "حصلت مشكلة وأنا بجيب البيانات، هحاول تاني."

#: What the outcome is called when the caller moved on before the answer existed.
SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class TurnRequest:
    """One spoken question on its way to the assistant.

    It carries the turn id so the answer can be attributed to the question it
    answers: the runner passes it on, the assistant marks the answer with it when
    a newer turn has taken over, and this service checks it again before saying
    anything out loud.
    """

    session_id: str
    turn: SpokenTurn
    transcript: str
    idempotency_key: str


#: A turn runner answers one spoken delegation and returns the text to speak.
#: An empty string is not spoken: it means the turn produced nothing sayable.
TurnRunner = Callable[[TurnRequest], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    delegation_id: str
    target: str
    offset_ms: int | None = None


def parse_delegation(event: dict[str, Any]) -> DelegationRequest | None:
    """Read a delegation out of an event, or None when it is not one.

    A malformed delegation (no id) is refused here rather than answered: without
    an id there is nothing to reply to, and inventing one is exactly what the
    gateway rejects.
    """
    if not isinstance(event, dict) or event.get("type") != DELEGATION_CREATED:
        return None
    delegation = event.get("delegation")
    if not isinstance(delegation, dict):
        return None
    delegation_id = str(delegation.get("id") or "").strip()
    if not delegation_id:
        return None
    offset = event.get("offset_ms")
    return DelegationRequest(
        delegation_id=delegation_id,
        target=str(delegation.get("target") or ""),
        offset_ms=offset if isinstance(offset, int) else None,
    )


class ClientDelegationService:
    """Answers GPT-Live's delegations with the assistant's real brain."""

    def __init__(
        self,
        provider,
        turn_runner: TurnRunner,
        *,
        call_id: str | None = None,
        ledger: TurnLedger | None = None,
    ) -> None:
        self._provider = provider
        self._turn_runner = turn_runner
        #: The call as the turn path names it — the voice session id. The provider's own session
        #: id is what frames are addressed by, and the two are not the same string; the ledger has
        #: to be keyed by the one the assistant turn also uses, or every turn would look unknown
        #: and be dropped.
        self._call_id = str(call_id) if call_id is not None else None
        self._ledger = ledger if ledger is not None else TurnLedger()
        self._handled: dict[str, None] = {}

    async def on_event(self, session_id: str, event: dict[str, Any], *, transcript: str) -> str:
        """Handle one gateway event. Returns what happened, for the caller's log.

        ``transcript`` is what the caller actually said, assembled by the caller
        from the transcript events: the delegation itself never carries the task
        text, so guessing it from the event would be inventing the question.
        """
        request = parse_delegation(event)
        if request is None:
            return "ignored"
        if request.delegation_id in self._handled:
            logger.info(
                "voice.delegation_duplicate session=%s delegation=%s",
                session_id,
                request.delegation_id,
            )
            return "duplicate"
        self._claim(request.delegation_id)

        # The caller's question becomes a turn with an id of its own HERE, before a penny is spent
        # on it. Beginning it also makes it the call's current turn, which is what tells the answer
        # still being written for the previous question that nobody is waiting for it any more.
        turn = self._ledger.begin(self._call_id or session_id)

        # Acknowledge immediately with an empty thinking frame, exactly as the
        # protocol asks: it tells the model the work has started, so it keeps
        # listening instead of repeating the request.
        await self._provider.append_thinking(
            session_id, delegation_id=request.delegation_id, content=""
        )

        try:
            answer = await self._turn_runner(
                TurnRequest(
                    session_id=turn.session_id,
                    turn=turn,
                    transcript=transcript,
                    idempotency_key=f"delegation:{request.delegation_id}",
                )
            )
        except Exception:  # noqa: BLE001 — a failed turn must still be spoken about
            logger.exception(
                "voice.delegation_failed session=%s delegation=%s",
                session_id,
                request.delegation_id,
            )
            await self._provider.append_thinking(
                session_id, delegation_id=request.delegation_id, content=FAILURE_NOTE
            )
            return "failed"

        if not self._ledger.is_current(turn):
            # The caller asked something else while this one was being answered (or interrupted it
            # outright). The work is kept in the conversation as cancelled; handing it to the model
            # now would make it answer a question nobody is asking any more. Checked here as well as
            # in the turn, because this is the last moment before the words leave for the speaker.
            logger.info(
                "voice.delegation_superseded session=%s delegation=%s turn=%s",
                session_id,
                request.delegation_id,
                turn.turn_id,
            )
            return SUPERSEDED

        if not (answer or "").strip():
            # An empty answer is not an answer: say nothing rather than let the
            # model fill the silence with something we never verified.
            await self._provider.append_thinking(
                session_id, delegation_id=request.delegation_id, content=FAILURE_NOTE
            )
            return "failed"

        await self._provider.append_commentary(
            session_id, delegation_id=request.delegation_id, content=answer
        )
        return "answered"

    def interrupt(self, session_id: str) -> str | None:
        """The caller talked over the answer: stop waiting for it.

        The current turn is dropped, so the answer still being written for it is
        no longer current: the turn records itself as cancelled when it finishes,
        and this service will not speak what it returns. Nothing is written here —
        the rows belong to the turn, which is the one writer.

        Returns the turn id that was dropped, or ``None`` when the call had
        nothing in flight.
        """
        dropped = self._ledger.supersede(self._call_id or session_id)
        if dropped is not None:
            logger.info("voice.delegation_interrupted session=%s turn=%s", session_id, dropped)
        return None if dropped is None else str(dropped)

    def _claim(self, delegation_id: str) -> None:
        self._handled[delegation_id] = None
        while len(self._handled) > REMEMBERED_DELEGATIONS:
            self._handled.pop(next(iter(self._handled)))

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
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DELEGATION_CREATED = "session.delegation.created"

#: How many answered delegation ids are remembered per process. Idempotency in
#: the database is the real guard; this only stops a redelivery in the same call
#: from even reaching the turn.
REMEMBERED_DELEGATIONS = 256

#: What the caller hears when the backend could not finish. Never a silent hole:
#: the model is told something went wrong so it can say so and keep listening.
FAILURE_NOTE = "حصلت مشكلة وأنا بجيب البيانات، هحاول تاني."

#: A turn runner answers one spoken delegation and returns the text to speak.
TurnRunner = Callable[[str, str], Awaitable[str]]


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

    def __init__(self, provider, turn_runner: TurnRunner) -> None:
        self._provider = provider
        self._turn_runner = turn_runner
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

        # Acknowledge immediately with an empty thinking frame, exactly as the
        # protocol asks: it tells the model the work has started, so it keeps
        # listening instead of repeating the request.
        await self._provider.append_thinking(
            session_id, delegation_id=request.delegation_id, content=""
        )

        try:
            answer = await self._turn_runner(transcript, f"delegation:{request.delegation_id}")
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

    def _claim(self, delegation_id: str) -> None:
        self._handled[delegation_id] = None
        while len(self._handled) > REMEMBERED_DELEGATIONS:
            self._handled.pop(next(iter(self._handled)))

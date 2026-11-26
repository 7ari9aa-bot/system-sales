"""One turn: what the caller said, which tools it may reach, and what may be spoken back.

The orchestrator is the only place where a model's intent becomes an action, so it is also the
place where two of the invariants live:

* every tool call is authorized by the gateway at the moment of the call, not at session start
  (invariant 7) — a permission revoked mid-call stops working on the next turn;
* a tool result that arrives after the caller interrupted is kept for the record but never
  spoken as if it answered the new request (the failure table in §13.3).

Nothing here decides permissions itself: it asks the capability and the gateway.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.voice.domain.states import (
    TurnState,
    next_turn_state,
    turn_is_terminal,
)
from app.modules.voice.security.capabilities import SessionCapability, ToolGateway


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TurnRecord:
    sequence: int
    state: TurnState = TurnState.LISTENING
    transcript: str = ""
    spoken: str | None = None
    tool_calls: list[str] = field(default_factory=list)
    dropped_results: list[str] = field(default_factory=list)
    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    completed_at: dt.datetime | None = None

    @property
    def interrupted(self) -> bool:
        return self.state is TurnState.INTERRUPTED


class ToolRunner(Protocol):
    """Runs an authorized tool. The gateway has already said yes by the time this is called."""

    async def __call__(self, call: ToolCall) -> dict[str, Any]: ...


class TurnOrchestrator:
    def __init__(self, gateway: ToolGateway, runner: ToolRunner) -> None:
        self._gateway = gateway
        self._runner = runner

    def begin(self, sequence: int, transcript: str) -> TurnRecord:
        turn = TurnRecord(sequence=sequence)
        for target in (TurnState.ENDPOINTED, TurnState.UNDERSTANDING):
            turn.state = next_turn_state(turn.state, target)
        turn.transcript = transcript
        return turn

    async def call_tool(
        self, turn: TurnRecord, capability: SessionCapability, call: ToolCall
    ) -> dict[str, Any]:
        """Authorize, then run. A refusal is raised, never swallowed into an empty answer."""
        if turn.interrupted:
            # The caller already moved on; running a read now would bill work nobody hears.
            turn.dropped_results.append(call.name)
            return {"dropped": True, "tool": call.name}

        self._gateway.authorize(capability, call.name)
        turn.state = next_turn_state(turn.state, TurnState.TOOL_PENDING)
        turn.tool_calls.append(call.name)
        result = await self._runner(call)
        turn.state = next_turn_state(turn.state, TurnState.GENERATING)
        return result

    def speak(self, turn: TurnRecord, text: str) -> TurnRecord:
        """Say the answer, unless the turn was interrupted before we got here."""
        if turn.interrupted:
            turn.dropped_results.append("speech")
            return turn
        turn.state = next_turn_state(turn.state, TurnState.SPEAKING)
        turn.spoken = text
        turn.state = next_turn_state(turn.state, TurnState.COMPLETED)
        turn.completed_at = dt.datetime.now(dt.UTC)
        return turn

    def interrupt(self, turn: TurnRecord) -> TurnRecord:
        if not turn_is_terminal(turn.state):
            turn.state = next_turn_state(turn.state, TurnState.INTERRUPTED)
            turn.completed_at = dt.datetime.now(dt.UTC)
        return turn

    def fail(self, turn: TurnRecord, reason: str) -> TurnRecord:
        turn.state = next_turn_state(turn.state, TurnState.FAILED)
        turn.dropped_results.append(reason)
        turn.completed_at = dt.datetime.now(dt.UTC)
        return turn

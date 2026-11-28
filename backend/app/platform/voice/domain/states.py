"""Session and turn states, and the moves between them that are legal.

A voice session is long-lived and survives a lot of bad moments: a dropped socket, a provider that
times out, a human who takes over mid-sentence. Without a written state machine every one of those
becomes an ad-hoc boolean somewhere in the worker, and the first symptom is an agent that keeps
talking to a customer whose call a staff member already answered.

Two machines, deliberately separate. The session machine knows whether audio should exist at all;
the turn machine knows where one utterance got to. A turn can be interrupted a dozen times inside
one ACTIVE session, and a session can be HANDOFF_PENDING while its current turn is COMPLETED.

Both machines are pure functions over values here: the worker persists them, but the legality of
a move is decided in one place that tests can pin (invariants 9 and 14).
"""

from __future__ import annotations

import enum
from types import MappingProxyType
from typing import Final


class VoiceSessionState(enum.StrEnum):
    CREATED = "CREATED"
    AUTHENTICATING = "AUTHENTICATING"
    CONFIGURING = "CONFIGURING"
    REJECTED = "REJECTED"
    CONNECTING = "CONNECTING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    INTERRUPTED = "INTERRUPTED"
    HANDOFF_PENDING = "HANDOFF_PENDING"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class TurnState(enum.StrEnum):
    LISTENING = "LISTENING"
    ENDPOINTED = "ENDPOINTED"
    UNDERSTANDING = "UNDERSTANDING"
    TOOL_PENDING = "TOOL_PENDING"
    GENERATING = "GENERATING"
    SPEAKING = "SPEAKING"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


# Terminal session states: nothing follows them, and a worker that finds a session here must not
# resurrect it. CLOSED is the only graceful ending; the rest are endings anyway.
SESSION_TERMINAL: Final[frozenset[VoiceSessionState]] = frozenset(
    {VoiceSessionState.CLOSED, VoiceSessionState.FAILED, VoiceSessionState.REJECTED}
)

# Terminal turn states: a new utterance starts a NEW turn rather than reopening this one, which is
# what keeps "what did I already say" answerable after an interruption.
TURN_TERMINAL: Final[frozenset[TurnState]] = frozenset(
    {TurnState.COMPLETED, TurnState.INTERRUPTED, TurnState.FAILED}
)

_SESSION_MOVES: Final[dict[VoiceSessionState, frozenset[VoiceSessionState]]] = {
    VoiceSessionState.CREATED: frozenset(
        {VoiceSessionState.AUTHENTICATING, VoiceSessionState.REJECTED, VoiceSessionState.FAILED}
    ),
    VoiceSessionState.AUTHENTICATING: frozenset(
        {VoiceSessionState.CONFIGURING, VoiceSessionState.REJECTED, VoiceSessionState.FAILED}
    ),
    # A caller may ask for a human before the agent ever speaks, so the two pre-live states can go
    # straight to HANDOFF_PENDING. What they may never do is reach ACTIVE without a media path.
    VoiceSessionState.CONFIGURING: frozenset(
        {
            VoiceSessionState.CONNECTING,
            VoiceSessionState.HANDOFF_PENDING,
            VoiceSessionState.REJECTED,
            VoiceSessionState.FAILED,
        }
    ),
    VoiceSessionState.CONNECTING: frozenset(
        {
            VoiceSessionState.ACTIVE,
            VoiceSessionState.HANDOFF_PENDING,
            VoiceSessionState.FAILED,
            VoiceSessionState.CLOSING,
        }
    ),
    # DEGRADED is the state a session lives in when the media path lost quality but the call is
    # real: it may recover, it may end, but it never pretends to be healthy again by itself.
    VoiceSessionState.ACTIVE: frozenset(
        {
            VoiceSessionState.DEGRADED,
            VoiceSessionState.INTERRUPTED,
            VoiceSessionState.HANDOFF_PENDING,
            VoiceSessionState.CLOSING,
            VoiceSessionState.FAILED,
        }
    ),
    VoiceSessionState.DEGRADED: frozenset(
        {
            VoiceSessionState.ACTIVE,
            VoiceSessionState.INTERRUPTED,
            VoiceSessionState.HANDOFF_PENDING,
            VoiceSessionState.CLOSING,
            VoiceSessionState.FAILED,
        }
    ),
    VoiceSessionState.INTERRUPTED: frozenset(
        {
            VoiceSessionState.ACTIVE,
            VoiceSessionState.DEGRADED,
            VoiceSessionState.HANDOFF_PENDING,
            VoiceSessionState.CLOSING,
            VoiceSessionState.FAILED,
        }
    ),
    VoiceSessionState.HANDOFF_PENDING: frozenset(
        {
            VoiceSessionState.HUMAN_ACTIVE,
            VoiceSessionState.ACTIVE,  # no staff answered: the agent resumes, deliberately
            VoiceSessionState.CLOSING,
            VoiceSessionState.FAILED,
        }
    ),
    # The one-way door: once a human holds the call the agent cannot take it back on its own.
    VoiceSessionState.HUMAN_ACTIVE: frozenset(
        {VoiceSessionState.CLOSING, VoiceSessionState.FAILED}
    ),
    VoiceSessionState.CLOSING: frozenset({VoiceSessionState.CLOSED, VoiceSessionState.FAILED}),
}

_TURN_MOVES: Final[dict[TurnState, frozenset[TurnState]]] = {
    TurnState.LISTENING: frozenset({TurnState.ENDPOINTED, TurnState.FAILED, TurnState.INTERRUPTED}),
    TurnState.ENDPOINTED: frozenset(
        {TurnState.UNDERSTANDING, TurnState.FAILED, TurnState.INTERRUPTED}
    ),
    TurnState.UNDERSTANDING: frozenset(
        {
            TurnState.TOOL_PENDING,
            TurnState.GENERATING,
            TurnState.FAILED,
            TurnState.INTERRUPTED,
        }
    ),
    # A tool may finish after the user cut in: the result is kept, the reply is not spoken.
    TurnState.TOOL_PENDING: frozenset(
        {
            TurnState.GENERATING,
            TurnState.SPEAKING,
            TurnState.FAILED,
            TurnState.INTERRUPTED,
        }
    ),
    TurnState.GENERATING: frozenset({TurnState.SPEAKING, TurnState.FAILED, TurnState.INTERRUPTED}),
    TurnState.SPEAKING: frozenset({TurnState.COMPLETED, TurnState.FAILED, TurnState.INTERRUPTED}),
}

SESSION_MOVES: Final[MappingProxyType[VoiceSessionState, frozenset[VoiceSessionState]]] = (
    MappingProxyType(_SESSION_MOVES)
)
TURN_MOVES: Final[MappingProxyType[TurnState, frozenset[TurnState]]] = MappingProxyType(_TURN_MOVES)


class IllegalTransition(Exception):
    """A move the machine does not allow — a bug in the worker, never a user's fault."""

    def __init__(self, machine: str, current: str, target: str) -> None:
        super().__init__(f"{machine}: {current} -> {target} is not a legal move")
        self.machine = machine
        self.current = current
        self.target = target


def next_session_state(current: VoiceSessionState, target: VoiceSessionState) -> VoiceSessionState:
    """Return ``target`` when the move is legal, raise otherwise."""
    if target not in SESSION_MOVES.get(current, frozenset()):
        raise IllegalTransition("voice_session", current.value, target.value)
    return target


def next_turn_state(current: TurnState, target: TurnState) -> TurnState:
    if target not in TURN_MOVES.get(current, frozenset()):
        raise IllegalTransition("voice_turn", current.value, target.value)
    return target


def session_is_terminal(state: VoiceSessionState) -> bool:
    return state in SESSION_TERMINAL


def turn_is_terminal(state: TurnState) -> bool:
    return state in TURN_TERMINAL


def agent_may_speak(state: VoiceSessionState) -> bool:
    """The single question the audio egress asks before playing anything.

    HUMAN_ACTIVE is absent on purpose: a staff member holding the call is the whole point of the
    handoff, and an agent that keeps talking underneath them is the failure this prevents.
    """
    return state in (
        VoiceSessionState.ACTIVE,
        VoiceSessionState.DEGRADED,
        VoiceSessionState.INTERRUPTED,
    )

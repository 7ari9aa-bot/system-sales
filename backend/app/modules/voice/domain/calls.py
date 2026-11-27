"""Call and leg states, using the vocabulary the existing tables already allow.

`calls.status` accepts ringing | in_progress | completed | failed | no_answer | busy and
`call_legs.status` accepts ringing | answered | completed | failed | no_answer | busy, so this
module speaks those words instead of inventing a second dialect the database would reject.

A call is the phone call; a leg is one connection inside it. A transfer makes a second leg, it
does not make a second call, and the call ends only when no leg can still be answered.
"""

from __future__ import annotations

import enum
from typing import Final


class CallStatus(enum.StrEnum):
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"


class LegStatus(enum.StrEnum):
    RINGING = "ringing"
    ANSWERED = "answered"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"


class LegType(enum.StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    TRANSFER = "transfer"


CALL_TERMINAL: Final[frozenset[CallStatus]] = frozenset(
    {CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.NO_ANSWER, CallStatus.BUSY}
)
LEG_TERMINAL: Final[frozenset[LegStatus]] = frozenset(
    {LegStatus.COMPLETED, LegStatus.FAILED, LegStatus.NO_ANSWER, LegStatus.BUSY}
)


_CALL_MOVES: Final[dict[CallStatus, frozenset[CallStatus]]] = {
    CallStatus.RINGING: frozenset(
        {CallStatus.IN_PROGRESS, CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.FAILED}
    ),
    # A call in progress can finish, fail, or lose the caller. It never goes back to ringing: the
    # phone already rang once and the caller's experience is not rewound.
    CallStatus.IN_PROGRESS: frozenset({CallStatus.COMPLETED, CallStatus.FAILED}),
    CallStatus.COMPLETED: frozenset(),
    CallStatus.FAILED: frozenset(),
    CallStatus.NO_ANSWER: frozenset(),
    CallStatus.BUSY: frozenset(),
}

_LEG_MOVES: Final[dict[LegStatus, frozenset[LegStatus]]] = {
    LegStatus.RINGING: frozenset(
        {LegStatus.ANSWERED, LegStatus.NO_ANSWER, LegStatus.BUSY, LegStatus.FAILED}
    ),
    LegStatus.ANSWERED: frozenset({LegStatus.COMPLETED, LegStatus.FAILED}),
    LegStatus.COMPLETED: frozenset(),
    LegStatus.FAILED: frozenset(),
    LegStatus.NO_ANSWER: frozenset(),
    LegStatus.BUSY: frozenset(),
}


class IllegalCallTransition(Exception):
    """A move the phone system cannot make, refused before it reaches the database."""


def next_call_status(current: CallStatus, target: CallStatus) -> CallStatus:
    if target not in _CALL_MOVES[current]:
        raise IllegalCallTransition(f"call cannot move {current} -> {target}")
    return target


def next_leg_status(current: LegStatus, target: LegStatus) -> LegStatus:
    if target not in _LEG_MOVES[current]:
        raise IllegalCallTransition(f"leg cannot move {current} -> {target}")
    return target

"""Which spoken turn is the one the caller is still waiting for.

A voice call is not one question and one answer. The caller talks over the model, corrects
themselves, asks something else — and the answer to the question they abandoned must never be
spoken once they have moved on. Silencing the speaker is not enough: the delegation that produced
that answer keeps running, and when it finishes it hands the model a line to say. The old answer is
still there, still paid for, and still wrong to say out loud.

So every spoken question gets a turn id of its own, and a call keeps exactly ONE current turn:

* a newer question takes the call over the moment it begins (``begin``);
* an explicit barge-in drops the current turn without starting a new one (``supersede``);
* anything that was in flight is then no longer current, and every place that could deliver it
  asks ``is_current`` first — ``assistant_turn.run_voice_turn`` before it records the answer, and
  ``client_delegation`` before it hands that answer to the model to be spoken.

The check is deliberately fail-closed: a turn this ledger has never heard of is not current, so a
caller that forgets to share the ledger drops answers instead of speaking stale ones.

The ledger is per process on purpose. One websocket owns one call and the process that answers its
delegations is the process that owns that socket, so the process is the scope in which "the newest
question" is decided. The durable half of the same fact — the abandoned answer is written as
``cancelled`` so the timeline still says so after the call — lives in ``transcript_sync``, which
owns those rows.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass

#: How many calls the ledger remembers at once. A turn leaves the map when a newer one begins or
#: when the caller interrupts, so this only bounds the calls that finished cleanly and were never
#: followed by another question.
REMEMBERED_CALLS = 512


@dataclass(frozen=True, slots=True)
class SpokenTurn:
    """One spoken question, from the moment it is heard until its answer is spoken or dropped."""

    turn_id: uuid.UUID
    #: What the call is addressed by where the turn began. The delegation boundary names a call by
    #: its voice session id; a turn minted deeper in the path uses the same id, so both halves of
    #: the path agree on which call a turn belongs to.
    session_id: str


class TurnLedger:
    """The newest spoken turn per call, and nothing else."""

    def __init__(self, capacity: int = REMEMBERED_CALLS) -> None:
        self._capacity = capacity
        self._current: OrderedDict[str, uuid.UUID] = OrderedDict()

    def begin(self, session_id, turn_id: uuid.UUID | None = None) -> SpokenTurn:
        """Start a turn, minting its id unless the caller already has one.

        Whatever was current stops being current: the newer question wins. Beginning the turn that
        is already current changes nothing, so a path that starts a turn and then hands it down the
        call cannot cancel itself.
        """
        turn = SpokenTurn(turn_id=turn_id or uuid.uuid4(), session_id=_key(session_id))
        self._current[turn.session_id] = turn.turn_id
        self._current.move_to_end(turn.session_id)
        while len(self._current) > self._capacity:
            self._current.popitem(last=False)
        return turn

    def is_current(self, turn: SpokenTurn | None) -> bool:
        """Whether ``turn`` is still the question this call is answering."""
        if turn is None:
            return False
        return self._current.get(turn.session_id) == turn.turn_id

    def current(self, session_id) -> uuid.UUID | None:
        """The turn id this call is on, or ``None`` when nothing is being answered."""
        return self._current.get(_key(session_id))

    def supersede(self, session_id) -> uuid.UUID | None:
        """Drop the turn in flight. Returns the id it had, or ``None`` if there was none.

        This is the barge-in: the caller spoke over the answer, so the answer being written for
        them is no longer wanted. No new turn starts here — the question that interrupted arrives
        as its own delegation and begins one.
        """
        return self._current.pop(_key(session_id), None)


def _key(session_id) -> str:
    """One spelling per call, whatever type the id arrives as."""
    return str(session_id)


#: The ledger a call uses when nothing injected another one. One instance, because a call's two
#: halves — the delegation that starts a turn and the turn that finishes it — must consult the same
#: map even when neither was handed one.
DEFAULT_LEDGER = TurnLedger()

__all__ = ["DEFAULT_LEDGER", "REMEMBERED_CALLS", "SpokenTurn", "TurnLedger"]

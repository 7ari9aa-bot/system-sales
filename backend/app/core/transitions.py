"""§183 — one transition guard for every state machine.

A machine is a dict of state → the set of states reachable from it. This
guard is the only place a transition is validated, so a vocabulary cannot
drift between a dict copy in one module and a hand-written ``if`` in another
(gap CC5). The tables themselves stay with the domain that owns the states —
the guard owns only the rule "a legal move or a ConflictError".
"""

from __future__ import annotations

from app.core.errors import ConflictError

TransitionTable = dict[str, set[str]]


def require_transition(
    table: TransitionTable,
    current: str,
    target: str,
    *,
    noun: str = "transition",
) -> str:
    """Return ``target`` when the move is legal; ConflictError otherwise.

    ``noun`` keeps each domain's historical error text byte-for-byte (the
    orders contract tests pin them): "illegal transition a -> b",
    "illegal shipment transition a -> b", "illegal saga transition a -> b".

    Fails CLOSED on hostile input: a ``current`` or ``target`` that is not a
    string (None, a list, a dict — a request body can carry any of them) can
    never be a legal move, so it raises the same ConflictError instead of
    letting an unhashable value escape the membership test as a raw TypeError
    (which a handler would surface as a bare 500).
    """
    if not isinstance(current, str) or not isinstance(target, str):
        raise ConflictError(f"illegal {noun} {current!r} -> {target!r}")
    if target not in table.get(current, set()):
        raise ConflictError(f"illegal {noun} {current} -> {target}")
    return target


def allowed(table: TransitionTable, current: str) -> set[str]:
    """The states reachable from ``current`` — for docs and error hints.

    Never a licence to re-implement the guard beside it.
    """
    return set(table.get(current, set()))

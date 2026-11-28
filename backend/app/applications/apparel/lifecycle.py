"""The states a workspace's apparel installation moves through.

Every support question about a shop starts with "what state is it in": bought
but not installed, installed but not set up, running, suspended for a bill,
read-only after a lapse, or removed. Naming those states once, with the moves
between them, is what keeps the licence, the router gate and the onboarding
screen from each inventing their own answer (industry-applications §15).

An unknown state is not a state. ``allows_reads`` and ``allows_writes`` refuse
anything they do not recognise, so a typo or a row written by an older release
fails closed instead of opening a store.
"""

from __future__ import annotations

import enum


class AppState(enum.StrEnum):
    """The lifecycle of one application installation in one workspace."""

    AVAILABLE = "available"
    LICENSED = "licensed"
    PROVISIONING = "provisioning"
    SETUP_REQUIRED = "setup_required"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    READ_ONLY = "read_only"
    UNINSTALLED = "uninstalled"


class IllegalTransition(ValueError):
    """A move the lifecycle does not allow."""


#: Every allowed move. Same-state is always allowed (idempotent provisioning).
TRANSITIONS: dict[AppState, frozenset[AppState]] = {
    AppState.AVAILABLE: frozenset({AppState.LICENSED}),
    AppState.LICENSED: frozenset({AppState.PROVISIONING, AppState.UNINSTALLED}),
    AppState.PROVISIONING: frozenset({AppState.SETUP_REQUIRED, AppState.LICENSED}),
    AppState.SETUP_REQUIRED: frozenset({AppState.ACTIVE, AppState.SUSPENDED}),
    AppState.ACTIVE: frozenset({AppState.SUSPENDED, AppState.READ_ONLY, AppState.UNINSTALLED}),
    AppState.SUSPENDED: frozenset({AppState.ACTIVE, AppState.READ_ONLY, AppState.UNINSTALLED}),
    AppState.READ_ONLY: frozenset({AppState.ACTIVE, AppState.SUSPENDED, AppState.UNINSTALLED}),
    # Reinstalling after removal returns to the licence, never straight to active:
    # the workspace must be set up again, because its setup data was exported, not kept.
    AppState.UNINSTALLED: frozenset({AppState.LICENSED}),
}

#: States in which the shop's data may be read.
READABLE = frozenset({AppState.ACTIVE, AppState.READ_ONLY, AppState.SETUP_REQUIRED})

#: The only state in which the shop's data may change.
WRITABLE = frozenset({AppState.ACTIVE})


def parse(state: str) -> AppState | None:
    """``"active"`` -> ``AppState.ACTIVE``; anything unknown -> ``None``."""
    try:
        return AppState(state)
    except ValueError:
        return None


def can_transition(current: AppState | str, target: AppState | str) -> bool:
    here, there = _both(current), _both(target)
    return here == there or there in TRANSITIONS[here]


def transition(current: AppState | str, target: AppState | str) -> AppState:
    """The state after the move, or ``IllegalTransition``.

    Moving to the state you are already in is allowed and returns it: a retried
    provisioning job must not fail because it already finished.
    """
    here, there = _both(current), _both(target)
    if here == there:
        return here
    if there not in TRANSITIONS[here]:
        raise IllegalTransition(f"{here.value} -> {there.value} is not allowed")
    return there


def allows_reads(state: AppState | str) -> bool:
    """May the shop's data be read in ``state``? Unknown states refuse."""
    parsed = parse(str(state))
    return parsed is not None and parsed in READABLE


def allows_writes(state: AppState | str) -> bool:
    """May the shop's data change in ``state``? Only a running shop may."""
    parsed = parse(str(state))
    return parsed is not None and parsed in WRITABLE


def _both(value: AppState | str) -> AppState:
    parsed = parse(str(value))
    if parsed is None:
        raise IllegalTransition(f"unknown application state: {value!r}")
    return parsed

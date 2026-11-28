"""The installation lifecycle must be a closed set of legal moves.

Every case here is one the architecture names: a workspace cannot jump from
"available" to "active", a lapsed licence falls to read-only instead of being
deleted, and an unknown state opens nothing.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.lifecycle import (
    READABLE,
    TRANSITIONS,
    WRITABLE,
    AppState,
    IllegalTransition,
    allows_reads,
    allows_writes,
    can_transition,
    parse,
    transition,
)


def test_every_state_has_declared_moves() -> None:
    assert set(TRANSITIONS) == set(AppState)


def test_a_licence_is_never_active_without_provisioning_and_setup() -> None:
    with pytest.raises(IllegalTransition):
        transition(AppState.AVAILABLE, AppState.ACTIVE)
    with pytest.raises(IllegalTransition):
        transition(AppState.LICENSED, AppState.ACTIVE)
    assert transition(AppState.LICENSED, AppState.PROVISIONING) is AppState.PROVISIONING
    assert transition(AppState.PROVISIONING, AppState.SETUP_REQUIRED) is AppState.SETUP_REQUIRED
    assert transition(AppState.SETUP_REQUIRED, AppState.ACTIVE) is AppState.ACTIVE


def test_a_lapsed_licence_falls_to_read_only_not_to_deletion() -> None:
    assert transition(AppState.ACTIVE, AppState.READ_ONLY) is AppState.READ_ONLY
    assert allows_reads(AppState.READ_ONLY) is True
    assert allows_writes(AppState.READ_ONLY) is False


def test_reinstalling_goes_back_through_setup() -> None:
    assert transition(AppState.ACTIVE, AppState.UNINSTALLED) is AppState.UNINSTALLED
    assert transition(AppState.UNINSTALLED, AppState.LICENSED) is AppState.LICENSED
    with pytest.raises(IllegalTransition):
        transition(AppState.UNINSTALLED, AppState.ACTIVE)


def test_a_retried_step_is_idempotent() -> None:
    assert transition(AppState.PROVISIONING, AppState.PROVISIONING) is AppState.PROVISIONING
    assert can_transition(AppState.ACTIVE, AppState.ACTIVE) is True


def test_only_a_running_shop_may_change_data() -> None:
    assert WRITABLE == frozenset({AppState.ACTIVE})
    assert allows_writes(AppState.ACTIVE) is True
    for state in AppState:
        if state is AppState.ACTIVE:
            continue
        assert allows_writes(state) is False, state


def test_setup_required_may_read_but_not_trade() -> None:
    assert AppState.SETUP_REQUIRED in READABLE
    assert allows_reads(AppState.SETUP_REQUIRED) is True
    assert allows_writes(AppState.SETUP_REQUIRED) is False


def test_an_unknown_state_opens_nothing() -> None:
    assert parse("expired") is None
    assert allows_reads("expired") is False
    assert allows_writes("") is False
    with pytest.raises(IllegalTransition, match="unknown"):
        transition("expired", AppState.ACTIVE)

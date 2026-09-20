"""Spec §48 — the tenant lifecycle state machine.

The platform used to have a single boolean (`is_active`): a two-state answer to
a lifecycle with eight states, so suspending for non-payment, a grace period
and offboarding were all impossible, and nothing recorded WHY a tenant was
disabled. These tests pin the two things that make the state machine usable:

1. the transition table is a real graph — every state reachable, no unknown
   targets, `deleted` terminal; and
2. the capability policy is what makes suspension different from "turn it all
   off" — a suspended tenant still reaches its data, which is what makes an
   export-then-delete offboarding possible.

Pure unit tests — no database. The two validation-before-IO checks use a
session stand-in that fails if anything reaches the database.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.errors import ValidationError
from app.modules.identity.models import Tenant
from app.modules.identity.service import (
    ALLOWED_TRANSITIONS,
    STATE_POLICIES,
    TENANT_INITIAL_STATE,
    TENANT_LIFECYCLE_STATES,
    TENANT_OPERATIONAL_STATES,
    TenantCapabilityPolicy,
    TenantLifecycleService,
)


class _NoDb:
    """Session stand-in that fails loudly if validation lets a query through."""

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("validation must run before the database is touched")


# --- the transition table ---------------------------------------------------


def test_every_lifecycle_state_has_a_capability_policy() -> None:
    assert set(STATE_POLICIES) == set(TENANT_LIFECYCLE_STATES)
    for state in TENANT_LIFECYCLE_STATES:
        assert isinstance(TenantLifecycleService.policy_for(state), TenantCapabilityPolicy)


def test_transitions_only_ever_target_known_states() -> None:
    known = set(ALLOWED_TRANSITIONS)
    assert known == set(TENANT_LIFECYCLE_STATES)
    for state, targets in ALLOWED_TRANSITIONS.items():
        assert targets <= known, (state, targets - known)


def test_every_state_is_reachable() -> None:
    """No dead state: the graph must be able to reach all eight from the start."""
    reachable = {TENANT_INITIAL_STATE}
    for targets in ALLOWED_TRANSITIONS.values():
        reachable |= targets
    assert reachable == set(TENANT_LIFECYCLE_STATES)


def test_deleted_is_terminal() -> None:
    assert ALLOWED_TRANSITIONS["deleted"] == frozenset()


def test_no_state_transitions_to_itself() -> None:
    for state, targets in ALLOWED_TRANSITIONS.items():
        assert state not in targets, state


def test_a_suspended_tenant_can_be_reactivated() -> None:
    """Suspension is reversible — otherwise it would be indistinguishable from
    deletion and the only recovery would be to recreate the tenant."""
    assert "active" in ALLOWED_TRANSITIONS["suspended"]


# --- the capability policy --------------------------------------------------


def test_active_suspended_and_deleted_policies_all_differ() -> None:
    active = TenantLifecycleService.policy_for("active")
    suspended = TenantLifecycleService.policy_for("suspended")
    deleted = TenantLifecycleService.policy_for("deleted")
    assert len({active, suspended, deleted}) == 3
    assert active != suspended and suspended != deleted and active != deleted


def test_suspension_keeps_data_export_but_stops_the_business() -> None:
    """The whole point of §48: suspension is NOT 'disable everything'.

    A suspended admin must still be able to export their data — that is what
    makes offboarding possible instead of holding the customer's data hostage.
    """
    suspended = TenantLifecycleService.policy_for("suspended")
    assert suspended.allows_data_access is True
    assert suspended.allows_login is False
    assert suspended.allows_api is False
    assert suspended.allows_ai is False
    assert suspended.allows_channels is False
    assert suspended.allows_automation is False


def test_offboarding_allows_login_and_export_only() -> None:
    policy = TenantLifecycleService.policy_for("offboarding")
    assert policy.allows_login is True
    assert policy.allows_data_access is True
    assert policy.allows_api is False
    assert policy.allows_ai is False
    assert policy.allows_channels is False
    assert policy.allows_automation is False


def test_an_unknown_state_has_no_policy() -> None:
    with pytest.raises(ValidationError):
        TenantLifecycleService.policy_for("banana")


def test_is_state_reads_the_lifecycle_state() -> None:
    tenant = Tenant(lifecycle_state="suspended")
    assert TenantLifecycleService.is_state(tenant, "suspended")
    assert not TenantLifecycleService.is_state(tenant, "active")


# --- the coarse flag stays consistent with the detailed state ---------------


def test_coarse_flag_is_false_only_for_restrictive_states() -> None:
    assert TENANT_OPERATIONAL_STATES == {
        "provisioning",
        "trial",
        "active",
        "past_due",
        "grace",
    }
    for state in ("suspended", "offboarding", "deleted"):
        assert TenantLifecycleService.is_coarse_active(state) is False
    for state in TENANT_LIFECYCLE_STATES:
        assert TenantLifecycleService.is_coarse_active(state) == (
            state in TENANT_OPERATIONAL_STATES
        )


# --- validation happens before any I/O --------------------------------------


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("banana", "whatever"),  # unknown target
        ("suspended", None),  # restrictive state, no reason given
        ("deleted", "   "),  # blank reason is not a reason
    ],
)
def test_bad_transitions_are_refused_before_touching_the_database(
    target: str, reason: str | None
) -> None:
    with pytest.raises(ValidationError):
        asyncio.run(
            TenantLifecycleService.transition(
                _NoDb(), uuid.uuid4(), target, reason=reason
            )
        )

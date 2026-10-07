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


@pytest.mark.parametrize(
    "target",
    [None, ["active"], {"state": "active"}, 7, True],
)
def test_hostile_target_types_fail_closed_not_as_a_raw_typeerror(
    target: object,
) -> None:
    """§183 contract (core/transitions.require_transition), applied here.

    The vocabulary check used to be a bare ``target not in STATE_POLICIES``,
    so an unhashable target — a list or dict a service-level caller can hand
    over — escaped as a raw TypeError and surfaced as a bare 500 instead of
    the domain refusal every other illegal transition gets. A None/int target
    is refused the same way rather than depending on hashing accidents.
    """
    with pytest.raises(ValidationError, match="unknown tenant lifecycle state"):
        asyncio.run(TenantLifecycleService.transition(_NoDb(), uuid.uuid4(), target))


@pytest.mark.parametrize("reason", [["closing shop"], {"reason": "closing shop"}, 7])
def test_a_non_string_reason_fails_closed(reason: object) -> None:
    """Same posture for the reason: a list reached ``.strip()`` as an
    AttributeError (500) before the guard existed."""
    with pytest.raises(ValidationError):
        asyncio.run(
            TenantLifecycleService.transition(
                _NoDb(), uuid.uuid4(), "suspended", reason=reason
            )
        )


# --- route-level authority (external audit finding 1) ------------------------
#
# The transition ROUTE used to be gated by settings:write alone, so ANY
# owner/admin could move their own tenant past_due -> active (billing bypass),
# suspended -> active (self-unsuspension) or -> deleted. The authority split
# lives in the route, so these tests drive `transition_tenant_lifecycle`
# directly with a hand-built TenantContext — the same DB-verified
# AuthedUser.is_platform_admin the require_platform_admin dependency reads.

from app.core.errors import PermissionDeniedError  # noqa: E402
from app.modules.identity.deps import AuthedUser, TenantContext  # noqa: E402
from app.modules.identity.router import (  # noqa: E402
    LifecycleTransitionRequest,
    transition_tenant_lifecycle,
)


def _owner_ctx(db, tenant_ctx, *, is_platform_admin: bool = False) -> TenantContext:
    return TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            is_platform_admin=is_platform_admin,
            is_active=True,
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"settings:write"},
    )


@pytest.mark.parametrize("target", ["active", "past_due", "grace", "deleted"])
async def test_billing_controlled_transitions_require_platform_admin(
    db, tenant_ctx, target: str
):
    """→active/→past_due/→grace/→deleted restore service or steer billing."""
    body = LifecycleTransitionRequest(state=target, reason="self-service attempt")
    with pytest.raises(PermissionDeniedError, match="platform admin"):
        await transition_tenant_lifecycle(tenant_ctx.tenant_id, body, _owner_ctx(db, tenant_ctx))


async def test_suspend_is_not_owner_requestable_either(db, tenant_ctx):
    """Suspension is the billing system's and the platform's lever, not the
    tenant's — a tenant-side settings:write holder may request ONE thing:
    their own offboarding."""
    body = LifecycleTransitionRequest(state="suspended", reason="going dark myself")
    with pytest.raises(PermissionDeniedError, match="only request offboarding"):
        await transition_tenant_lifecycle(tenant_ctx.tenant_id, body, _owner_ctx(db, tenant_ctx))


async def test_offboarding_requires_the_password_step_up(db, tenant_ctx):
    """§146 step-up on the one tenant-side-requestable transition.

    Offboarding starts the deletion countdown, so a bearer token alone must
    not suffice — the same posture mfa/enroll takes.
    """
    with pytest.raises(PermissionDeniedError, match="re-authentication"):
        await transition_tenant_lifecycle(
            tenant_ctx.tenant_id,
            LifecycleTransitionRequest(state="offboarding", reason="closing shop"),
            _owner_ctx(db, tenant_ctx),
        )
    with pytest.raises(PermissionDeniedError, match="step-up failed"):
        await transition_tenant_lifecycle(
            tenant_ctx.tenant_id,
            LifecycleTransitionRequest(
                state="offboarding", reason="closing shop", password="wrong-password"
            ),
            _owner_ctx(db, tenant_ctx),
        )


async def test_owner_offboarding_with_the_password_transitions(
    db, tenant_ctx, app_sessions_on_test_connection
):
    """The happy path: password verified, the tenant moves to offboarding."""
    body = LifecycleTransitionRequest(
        state="offboarding", reason="closing shop", password="secret-password"
    )
    out = await transition_tenant_lifecycle(
        tenant_ctx.tenant_id, body, _owner_ctx(db, tenant_ctx)
    )
    assert out.lifecycle_state == "offboarding"
    assert out.deletion_scheduled_at is not None


async def test_platform_admin_member_may_move_the_state(
    db, tenant_ctx, app_sessions_on_test_connection
):
    """A platform admin who is ALSO a member transitions with full authority —
    the DB-verified flag is what unlocks the billing-controlled targets."""
    body = LifecycleTransitionRequest(state="suspended", reason="chargeback hold")
    out = await transition_tenant_lifecycle(
        tenant_ctx.tenant_id, body, _owner_ctx(db, tenant_ctx, is_platform_admin=True)
    )
    assert out.lifecycle_state == "suspended"


# --- the mandated full transition matrix (package 1.2 closing test) ---------
#
# Every lifecycle target × every actor kind, driven through the REAL HTTP
# route (create_app + the real middleware stack) so each cell's verdict is the
# status the API actually answers: 200 served, 403 refused on authority, 409
# refused on the state machine. Actor kinds, in this codebase's vocabulary:
#
#   owner          — tenant member holding settings:write, NOT a platform
#                    admin. The one requestable target is offboarding, and it
#                    requires the §146 password step-up (the body carries it).
#   manager        — the admin-class tenant role WITHOUT settings:write
#                    (ROLE_MATRIX grants manager settings:read only), so every
#                    cell is refused at the RBAC gate before the lifecycle
#                    authority split is even reached.
#   platform_admin — a member whose DB-verified platform flag is set: full
#                    authority over every target, so the STATE MACHINE is the
#                    only gate left — allowed moves are 200, moves the graph
#                    does not draw from `active` are 409.
#   anonymous      — no credentials at all: refused before any tenant context
#                    exists.
#
# The fixture tenant is in `active` (the column's server_default), so the
# platform-admin row exercises exactly the edges ALLOWED_TRANSITIONS["active"]
# draws: past_due, suspended, offboarding, deleted.

import httpx  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.identity.deps import get_db, get_tenant_ctx  # noqa: E402

_LIFECYCLE_TARGETS = (
    "provisioning",
    "trial",
    "active",
    "past_due",
    "grace",
    "suspended",
    "offboarding",
    "deleted",
)
_MATRIX_ACTORS = ("owner", "manager", "platform_admin", "anonymous")

# (target, actor) -> the status the route must answer. EVERY cell has a verdict.
TRANSITION_MATRIX: dict[tuple[str, str], int] = {
    (target, actor): expected
    for target in _LIFECYCLE_TARGETS
    for actor, expected in (
        # offboarding is the owner's single requestable target, and the body's
        # password satisfies the step-up; every other target is a 403 refusal
        # naming the platform admin's authority (or the single permitted move).
        ("owner", 200 if target == "offboarding" else 403),
        # The RBAC gate fires first for a settings:write-less member.
        ("manager", 403),
        # Full authority → the state machine decides: from `active` the graph
        # only draws past_due / suspended / offboarding / deleted.
        (
            "platform_admin",
            200 if target in ("past_due", "suspended", "offboarding", "deleted") else 409,
        ),
        # No credentials → no tenant context → refused outright.
        ("anonymous", 403),
    )
}


def _matrix_ctx(db, tenant_ctx, actor: str) -> TenantContext:
    """The hand-built TenantContext for one matrix actor.

    Identity mirrors what ``get_current_user`` would have DB-verified: the
    owner row is an ordinary member, the platform-admin row carries the
    verified flag on the AuthedUser (the exact value ``require_platform_admin``
    reads). Permissions mirror ROLE_MATRIX for the actor's role.
    """
    if actor == "platform_admin":
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id,
                tenant_id=tenant_ctx.tenant_id,
                role_code="owner",
                is_platform_admin=True,
                is_active=True,
            ),
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            permission_codes={"settings:write"},
        )
    if actor == "manager":
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id,
                tenant_id=tenant_ctx.tenant_id,
                role_code="manager",
                is_active=True,
            ),
            tenant_id=tenant_ctx.tenant_id,
            role_code="manager",
            # manager: everything settings EXCEPT the write (provision.py).
            permission_codes={"settings:read"},
        )
    return _owner_ctx(db, tenant_ctx)


def _matrix_app(db, tenant_ctx, actor: str):
    """The real app with sessions bound to the test transaction.

    For ``anonymous`` no identity dependency is overridden: the real auth
    chain runs, finds no token and refuses — that refusal IS the cell.
    """
    app = create_app()

    async def _session():
        yield db

    app.dependency_overrides[get_db] = _session
    if actor != "anonymous":
        ctx = _matrix_ctx(db, tenant_ctx, actor)
        app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    return app


@pytest.mark.parametrize(("target", "actor"), sorted(TRANSITION_MATRIX))
async def test_transition_matrix_target_x_actor(
    db,
    tenant_ctx,
    app_sessions_on_test_connection,
    target: str,
    actor: str,
) -> None:
    """Every cell of the mandated matrix has one expected verdict, pinned here.

    200 → the transition happened (the response names the new state);
    403 → the actor has no authority over this target (or no credentials);
    409 → the state machine refuses a move the graph does not draw.
    """
    expected = TRANSITION_MATRIX[(target, actor)]
    app = _matrix_app(db, tenant_ctx, actor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/tenants/{tenant_ctx.tenant_id}/lifecycle",
            json={"state": target, "reason": "matrix probe", "password": "secret-password"},
        )

    assert response.status_code == expected, (
        f"matrix cell (target={target!r}, actor={actor!r}): expected "
        f"{expected}, got {response.status_code}: {response.text}"
    )
    if expected == 200:
        assert response.json()["lifecycle_state"] == target


def test_the_matrix_covers_every_target_and_actor_exactly_once() -> None:
    """The matrix is complete by construction: 8 targets × 4 actors, no gaps.

    This is the guard that keeps the parametrized test above honest — a new
    lifecycle state or actor kind added to the system without extending the
    matrix fails HERE, loudly.
    """
    assert set(_LIFECYCLE_TARGETS) == set(TENANT_LIFECYCLE_STATES)
    assert set(_MATRIX_ACTORS) == {"owner", "manager", "platform_admin", "anonymous"}
    assert len(TRANSITION_MATRIX) == len(_LIFECYCLE_TARGETS) * len(_MATRIX_ACTORS)
    assert {verdict for verdict in TRANSITION_MATRIX.values()} <= {200, 403, 409}

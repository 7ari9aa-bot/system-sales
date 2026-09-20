"""§48 tenant lifecycle enforcement on the request path (review N-02).

Before this, nothing on the request path read the tenant's lifecycle state at
all: `get_current_user` checked `User.is_active` and `get_tenant_ctx` checked
membership, but a tenant set to `suspended` or `deleted` kept full API access
indefinitely. The state machine and `TenantCapabilityPolicy` already existed and
were simply never consulted.

Two layers are tested:

* `get_tenant_ctx` — the `allows_api` gate for everything after sign-in.
* `AuthService._assert_tenant_allows_login` — the `allows_login` gate for
  login / refresh / switch-tenant, which run before any tenant context exists.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.errors import PermissionDeniedError
from app.modules.identity.deps import (
    AuthedUser,
    _policy_for,
    _tenant_recovery_path,
    get_tenant_ctx,
)
from app.modules.identity.models import Tenant
from app.modules.identity.service import STATE_POLICIES, AuthService


def _request(path: str) -> Request:
    """A minimal ASGI scope — enough for `request.url.path`."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


async def _set_state(db: AsyncSession, tenant_id: uuid.UUID, state: str) -> None:
    """Force the lifecycle state directly.

    `TenantLifecycleService.transition` is the real writer and has its own
    tests; here we only need the column the gate reads to hold a given value.
    """
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    tenant.lifecycle_state = state
    await db.flush()


def _authed(tenant_ctx) -> AuthedUser:
    return AuthedUser(
        id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"
    )


# ----------------------------------------------------- pure allowlist -----


def test_recovery_paths_cover_the_escape_hatches() -> None:
    for path in (
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/billing/subscription",
        "/api/v1/privacy/requests",
        "/api/v1/notifications",
        "/healthz",
    ):
        assert _tenant_recovery_path(path), path


def test_business_routes_are_not_recovery_paths() -> None:
    """The allowlist must not accidentally swallow normal business routes."""
    for path in (
        "/api/v1/customers",
        "/api/v1/orders",
        "/api/v1/conversations",
        "/api/v1/tasks",
        "/api/v1/products",
        "/api/v1/ai/agents",
    ):
        assert not _tenant_recovery_path(path), path


def test_policy_lookup_fails_closed_on_an_unknown_state() -> None:
    assert _policy_for("active") is STATE_POLICIES["active"]
    assert _policy_for("suspended") is STATE_POLICIES["suspended"]
    # Unknown -> None so the caller denies, rather than raising a 400.
    assert _policy_for("not-a-real-state") is None


def test_offboarding_keeps_login_but_not_the_api() -> None:
    """The deliberate asymmetry: a suspended admin must still export."""
    assert STATE_POLICIES["suspended"].allows_login is False
    assert STATE_POLICIES["offboarding"].allows_login is True
    assert STATE_POLICIES["offboarding"].allows_api is False
    assert STATE_POLICIES["offboarding"].allows_data_access is True


# ---------------------------------------------- get_tenant_ctx (allows_api) --


async def test_active_tenant_reaches_a_business_route(db: AsyncSession, tenant_ctx):
    ctx = await get_tenant_ctx(_request("/api/v1/customers"), db, _authed(tenant_ctx))
    assert ctx.tenant_id == tenant_ctx.tenant_id


@pytest.mark.parametrize("state", ["suspended", "offboarding", "deleted"])
async def test_non_operational_tenant_is_blocked_from_business_routes(
    db: AsyncSession, tenant_ctx, state: str
):
    await _set_state(db, tenant_ctx.tenant_id, state)

    with pytest.raises(PermissionDeniedError) as exc:
        await get_tenant_ctx(_request("/api/v1/customers"), db, _authed(tenant_ctx))
    assert state in str(exc.value)


@pytest.mark.parametrize("state", ["suspended", "offboarding", "deleted"])
async def test_non_operational_tenant_still_reaches_recovery_routes(
    db: AsyncSession, tenant_ctx, state: str
):
    """Export and billing must keep working, or the tenant can never recover."""
    await _set_state(db, tenant_ctx.tenant_id, state)

    ctx = await get_tenant_ctx(
        _request("/api/v1/billing/subscription"), db, _authed(tenant_ctx)
    )
    assert ctx.tenant_id == tenant_ctx.tenant_id


async def test_unknown_lifecycle_state_denies_business_routes(
    db: AsyncSession, tenant_ctx
):
    """Fail closed: an uninterpretable state must not grant access."""
    await _set_state(db, tenant_ctx.tenant_id, "who-knows")

    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(_request("/api/v1/orders"), db, _authed(tenant_ctx))


async def test_blocked_tenant_is_checked_before_the_tenant_guc_is_bound(
    db: AsyncSession, tenant_ctx
):
    """A blocked tenant must not end up with a queryable RLS context."""
    await _set_state(db, tenant_ctx.tenant_id, "suspended")

    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(_request("/api/v1/customers"), db, _authed(tenant_ctx))

    bound = (
        await db.execute(sa.text("SELECT current_setting('app.tenant_id', true)"))
    ).scalar_one()
    assert bound in (None, ""), f"tenant GUC was bound for a blocked tenant: {bound!r}"


# ------------------------------------------ login gate (allows_login) -------


async def test_login_gate_allows_an_active_tenant(db: AsyncSession, tenant_ctx):
    await AuthService._assert_tenant_allows_login(db, tenant_ctx.tenant_id)


async def test_login_gate_allows_offboarding(db: AsyncSession, tenant_ctx):
    """Deliberate: the admin has to sign in to export before deletion."""
    await _set_state(db, tenant_ctx.tenant_id, "offboarding")
    await AuthService._assert_tenant_allows_login(db, tenant_ctx.tenant_id)


@pytest.mark.parametrize("state", ["suspended", "deleted"])
async def test_login_gate_blocks_suspended_and_deleted(
    db: AsyncSession, tenant_ctx, state: str
):
    await _set_state(db, tenant_ctx.tenant_id, state)

    with pytest.raises(PermissionDeniedError) as exc:
        await AuthService._assert_tenant_allows_login(db, tenant_ctx.tenant_id)
    assert state in str(exc.value)


async def test_login_gate_blocks_an_unknown_state(db: AsyncSession, tenant_ctx):
    await _set_state(db, tenant_ctx.tenant_id, "who-knows")
    with pytest.raises(PermissionDeniedError):
        await AuthService._assert_tenant_allows_login(db, tenant_ctx.tenant_id)


async def test_login_gate_is_a_noop_without_a_tenant(db: AsyncSession):
    """A user with no membership yet must still be able to sign in."""
    await AuthService._assert_tenant_allows_login(db, None)

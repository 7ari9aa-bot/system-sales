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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.core.db import bind_tenant
from app.core.errors import PermissionDeniedError
from app.core.security import create_access_token, decode_token
from app.modules.identity.deps import (
    AuthedUser,
    _policy_for,
    _tenant_recovery_path,
    get_tenant_ctx,
    tenant_may_use_api,
)
from app.modules.identity.models import Role, Tenant, TenantUser
from app.modules.identity.service import STATE_POLICIES, AuthService
from app.modules.realtime.router import _sse_auth, _tenant_may_stream


def _request(path: str, *, authorization: str | None = None) -> Request:
    """A minimal ASGI scope — enough for `request.url.path` and the auth header."""
    headers = [(b"authorization", authorization.encode())] if authorization else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
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
        "/api/v1/tenants/00000000-0000-0000-0000-000000000001/offboarding/export",
        "/api/v1/tenants/00000000-0000-0000-0000-000000000001/offboarding/status",
        "/healthz",
    ):
        assert _tenant_recovery_path(path), path


def test_the_lifecycle_route_is_not_a_recovery_path() -> None:
    """POST /tenants/{id}/lifecycle must stay behind the suspended-tenant gate.

    It used to be exempt, which — combined with settings:write gating the whole
    state machine — let a suspended owner restore their own service by API call
    (external audit finding 1). Restoration is the platform admin's job via the
    §147 break-glass route now; a blocked tenant gets nothing on this surface.
    """
    assert not _tenant_recovery_path(
        "/api/v1/tenants/00000000-0000-0000-0000-000000000001/lifecycle"
    )


def test_business_routes_are_not_recovery_paths() -> None:
    """The allowlist must not accidentally swallow normal business routes."""
    for path in (
        "/api/v1/customers",
        "/api/v1/orders",
        "/api/v1/conversations",
        "/api/v1/tasks",
        "/api/v1/products",
        "/api/v1/ai/agents",
        "/api/v1/tenants/00000000-0000-0000-0000-000000000001/timezone",
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


# ------------------------------------------------- the SSE gateway (N-09) --
#
# The realtime gateway was the ONE surface that never read `lifecycle_state`: the
# request path, the auth path and the workers all did, but `/realtime/events`
# only checked that the user was active and a member. A suspended workspace
# therefore kept a live firehose of its own events while every ordinary request
# was refused. A stream also outlives the request that opened it, so a
# connect-time check alone is not enough — the generator has to re-check.


def test_tenant_may_use_api_agrees_with_the_policy_table() -> None:
    """Pinned against the table itself, so adding a lifecycle state cannot leave
    the gate with an implicit answer."""
    for state, policy in STATE_POLICIES.items():
        assert tenant_may_use_api(state) is policy.allows_api, state


def test_tenant_may_use_api_fails_closed_on_unknown_or_missing() -> None:
    assert tenant_may_use_api("active") is True
    assert tenant_may_use_api("suspended") is False
    assert tenant_may_use_api("not-a-real-state") is False
    assert tenant_may_use_api(None) is False


class _NoEventsRedis:
    """`xread` finds nothing, so the loop falls through to the heartbeat branch."""

    async def xread(self, **_kwargs):
        return None


class _OpenRequest:
    async def is_disconnected(self) -> bool:
        return False


def _stream(rt):
    return rt._event_stream(
        tenant_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        streams=["message.events"],
        cursor=None,
        request=_OpenRequest(),
    )


async def test_the_stream_closes_once_the_workspace_may_no_longer_stream(
    monkeypatch,
) -> None:
    """The connect-time gate alone leaves an already-open inbox streaming.

    Before N-09 the generator never consulted the state at all, so this loop
    emitted a heartbeat forever — hence the cap rather than a bare iteration.
    The close carries exactly one frame: the tenant_suspended envelope. A bare
    close reads as a network drop and the client reconnects into the same
    refusal forever (d1f93a3 reconnect-storm fix), so silence is no longer the
    expected shape — one explanatory frame, then the stream ends.
    """
    from app.modules.realtime import router as rt

    monkeypatch.setattr(rt, "get_redis", lambda: _NoEventsRedis())
    monkeypatch.setattr(rt, "_HEARTBEAT_INTERVAL_S", 0)  # heartbeat due at once

    async def _deny(_tenant_id: str) -> bool:
        return False

    monkeypatch.setattr(rt, "_tenant_may_stream", _deny)

    frames: list[bytes] = []
    async for frame in _stream(rt):
        frames.append(frame)
        if len(frames) > 1:
            pytest.fail("the stream kept emitting after the workspace was blocked")

    assert len(frames) == 1, "a blocked workspace gets exactly the refusal frame"
    assert b"tenant_suspended" in frames[0]
    assert b"heartbeat" not in frames[0]


async def test_the_stream_keeps_heartbeating_while_the_workspace_is_allowed(
    monkeypatch,
) -> None:
    """The gate must be consulted, not simply kill every stream."""
    from app.modules.realtime import router as rt

    monkeypatch.setattr(rt, "get_redis", lambda: _NoEventsRedis())
    monkeypatch.setattr(rt, "_HEARTBEAT_INTERVAL_S", 0)

    async def _allow(_tenant_id: str) -> bool:
        return True

    monkeypatch.setattr(rt, "_tenant_may_stream", _allow)

    frames: list[bytes] = []
    async for frame in _stream(rt):
        frames.append(frame)
        if len(frames) >= 2:
            break

    assert frames == [b": heartbeat\n\n", b": heartbeat\n\n"]


@pytest.fixture
async def sse_sessions(monkeypatch, db):
    """Point the SSE module's own session factory at the test connection.

    Both SSE paths deliberately open their OWN short-lived session — a
    request-scoped one would pin a pooled connection for the entire stream, which
    can be hours. That is right in production, but it means they cannot see the
    `db` fixture's uncommitted rows, so bind them to the same connection rather
    than committing test data into the database.

    Patched through `get_sessionmaker` rather than `SessionLocal`: the latter is
    produced by the module's `__getattr__`, and restoring it by assignment would
    leave a real attribute permanently shadowing the lazy one.
    """
    conn = await db.connection()
    factory = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: factory)
    return factory


async def test_the_sse_gate_refuses_a_suspended_workspace(
    db: AsyncSession, tenant_ctx, sse_sessions
) -> None:
    tenant_id = str(tenant_ctx.tenant_id)
    assert await _tenant_may_stream(tenant_id) is True

    await _set_state(db, tenant_ctx.tenant_id, "suspended")

    assert await _tenant_may_stream(tenant_id) is False


async def test_sse_auth_refuses_to_open_a_stream_for_a_suspended_workspace(
    db: AsyncSession, tenant_ctx, sse_sessions
) -> None:
    """The endpoint's own gate, not just the helper it delegates to."""
    token = create_access_token(
        str(tenant_ctx.user.id), {"tenant_id": str(tenant_ctx.tenant_id)}
    )
    request = _request("/api/v1/realtime/events", authorization=f"Bearer {token}")

    # Active: the stream opens.
    authed = await _sse_auth(request)
    assert authed.tenant_id == tenant_ctx.tenant_id

    await _set_state(db, tenant_ctx.tenant_id, "suspended")

    with pytest.raises(PermissionDeniedError) as exc:
        await _sse_auth(request)
    assert "suspended" in str(exc.value)


async def test_unknown_lifecycle_state_denies_business_routes(
    db: AsyncSession, tenant_ctx
):
    """Fail closed: an uninterpretable state must not grant access."""
    await _set_state(db, tenant_ctx.tenant_id, "who-knows")

    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(_request("/api/v1/orders"), db, _authed(tenant_ctx))


async def test_blocked_tenant_is_denied_before_the_tenant_guc_is_switched(
    db: AsyncSession, tenant_ctx
):
    """Prove the gate runs BEFORE bind_tenant.

    The `tenant_ctx` fixture already bound the caller's own tenant, so asking
    "is app.tenant_id set" proves nothing. Instead use a SECOND tenant the
    caller is a member of: if the gate ran after bind_tenant, the GUC would have
    moved to that suspended tenant before the request was rejected.
    """
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Suspended Co")
    db.add(other)
    await db.flush()
    db.add(
        TenantUser(
            tenant_id=other.id, user_id=tenant_ctx.user.id, role_id=tenant_ctx.role.id
        )
    )
    await db.flush()
    # The sessions UPDATE now runs behind the tenants RLS policy (fd2026100410),
    # which matches `id = app.tenant_id OR app.is_platform_admin = 'true'`. The
    # fixture bound THIS caller's tenant, so writing a second tenant needs the
    # platform-admin GUC for the duration of the setup write — then it is
    # revoked again, because the caller under test is NOT a platform admin and
    # the gate below must reject an ordinary owner.
    await db.execute(sa.text("SELECT set_config('app.is_platform_admin', 'true', true)"))
    await _set_state(db, other.id, "suspended")
    await db.execute(sa.text("SELECT set_config('app.is_platform_admin', 'false', true)"))

    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(
            _request("/api/v1/customers"), db, _authed(tenant_ctx), str(other.id)
        )

    bound = (
        await db.execute(sa.text("SELECT current_setting('app.tenant_id', true)"))
    ).scalar_one()
    assert bound == str(tenant_ctx.tenant_id), (
        "the suspended tenant was bound before the gate rejected it: "
        f"app.tenant_id={bound!r}"
    )


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


# --------------------------------- §48 prefers an ACTIVE tenant at login -----
#
# Login used to pin the DEFAULT membership and refuse outright when its tenant
# was blocked, so a suspension locked the user out of tenants they still hold
# live memberships in. The membership candidates are now tried in preference
# order — default first, then the rest — and the refusal only lands when EVERY
# membership is blocked.


async def _second_membership(db: AsyncSession, tenant_ctx, *, default: bool) -> Tenant:
    """A second tenant + membership for the fixture user (self-GUC allows it)."""
    role = (await db.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Tenant")
    db.add(other)
    await db.flush()
    db.add(
        TenantUser(
            tenant_id=other.id,
            user_id=tenant_ctx.user.id,
            role_id=role.id,
            is_default=False,
        )
    )
    if default:
        # Make the fixture tenant the default, as the real register() does —
        # otherwise the preference order the fallback relies on is undefined.
        membership = (
            await db.execute(
                sa.select(TenantUser).where(
                    TenantUser.user_id == tenant_ctx.user.id,
                    TenantUser.tenant_id == tenant_ctx.tenant_id,
                )
            )
        ).scalar_one()
        membership.is_default = True
    await db.flush()
    return other


async def test_suspended_default_tenant_does_not_lock_out_the_active_ones(
    db: AsyncSession, tenant_ctx
):
    """A suspended default must not block sign-in into a live membership."""
    other = await _second_membership(db, tenant_ctx, default=True)
    await _set_state(db, tenant_ctx.tenant_id, "suspended")

    pair, _user, tenant_id = await AuthService.login(
        db,
        email=tenant_ctx.user.email,
        password="secret-password",
        user_agent="test",
        ip="127.0.0.1",
    )
    assert tenant_id == other.id
    claims = decode_token(pair.access_token)
    assert claims["tenant_id"] == str(other.id), (
        "the minted pair must carry the ACTIVE tenant, not the suspended one"
    )


async def test_login_refuses_only_when_every_membership_is_blocked(
    db: AsyncSession, tenant_ctx
):
    """All memberships blocked → the original default's refusal stands."""
    other = await _second_membership(db, tenant_ctx, default=True)
    await _set_state(db, tenant_ctx.tenant_id, "suspended")
    # The fallback must not be a loophole: the second tenant is blocked too.
    # tenants UPDATE is bound-tenant policy (fd2026100410), so bind it first.
    await bind_tenant(db, other.id)
    await _set_state(db, other.id, "deleted")

    with pytest.raises(PermissionDeniedError, match="suspended"):
        await AuthService.login(
            db,
            email=tenant_ctx.user.email,
            password="secret-password",
            user_agent="test",
            ip="127.0.0.1",
        )

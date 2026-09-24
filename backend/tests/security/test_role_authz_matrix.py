"""§114 "Authorization" + §115 "Broken authorization / Privilege escalation".

A token that is valid for tenant A proves the caller IS a member of A; it does
NOT prove the caller holds the ROLE the UI implied. The frontend hides a button
when the role lacks a permission (docs say "UI visibility is not security",
§12); the API must refuse the same action independently. This suite proves that
refusal for the real, mounted route graph — not a mock.

Method — no database required (mirrors tests/test_api_contracts.py):
  * the REAL FastAPI app is built with `create_app()`;
  * `get_tenant_ctx` is overridden to hand a route a fabricated TenantContext
    whose `permission_codes` are the exact set the seed (`scripts/provision.py`
    `ROLE_MATRIX`) grants to a given role, and whose session is an inert stub;
  * the request is driven through the full dependency chain via ASGITransport,
    so `require_permission(...)` (a dependency) and the in-body
    `_require_platform_admin` guard BOTH execute for real, before any endpoint
    body runs.

Contract asserted per route/role:
  * role lacks the permission  -> 403 (refused at the authorization layer) — every
    route in the matrix;
  * role holds the permission  -> NOT a 401/403 (reached the handler; the stub
    session may then 404/500 — that is irrelevant, the claim is only that the
    authorization gate did not deny a caller entitled to pass) — for the routes in
    ``_ALLOW_SAFE``, the ones whose handler touches nothing but the stubbed session
    and the in-memory secret store. The two directions are each other's
    non-vacuity check: a route with no gate is caught by the first, a route that
    denies everyone by the second.

The permission→role mapping is imported from the seed so this cannot drift from
what is actually provisioned. A route listed here under a permission it does
not enforce is exactly the hole this suite exists to catch — which is how
`POST /platform/secrets/{provider}/rotate` (any tenant member could rotate the
tenant's channel credentials) was found: it was gated only on tenancy while its
sibling `POST /platform/secrets` required `settings:write`.

Venue: runs anywhere (no DB). It complements the DB-backed cross-tenant matrix
in `test_tenant_access_matrix.py`, which proves tenant isolation (data plane);
this file proves role authorization (control plane).
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.identity.deps import (
    AuthedUser,
    TenantContext,
    get_db,
    get_tenant_ctx,
)

# Middlewares that open their OWN database/redis connection (the idempotency
# store is Postgres, the rate limiter is Redis). They are irrelevant to the
# authorization question this file asks — that is decided by the route's
# dependency chain — and leaving them in makes an unauthenticated-DB CI-less
# local run hang trying to reach the provisioned production host.
_TRANSPORT_ONLY_MIDDLEWARE = {IdempotencyMiddleware, RateLimitMiddleware}


def _authz_app():  # noqa: ANN201
    """The real mounted route graph, minus DB/redis-bound middleware.

    Every dependency under test (`require_permission`, the §160
    `_require_platform_admin` in-body guard) lives on the routes, not in the
    middleware — stripping them changes nothing about authorization.
    """
    app = create_app()
    app.user_middleware = [
        m for m in app.user_middleware if m.cls not in _TRANSPORT_ONLY_MIDDLEWARE
    ]
    app.middleware_stack = None  # force Starlette to rebuild the stack
    return app

# --- role -> permission-code sets, read straight from the provisioning seed ---
_provision_path = Path(__file__).resolve().parents[2] / "scripts" / "provision.py"
_spec = importlib.util.spec_from_file_location("_provision_seed", _provision_path)
_provision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_provision)  # type: ignore[union-attr]
ROLE_MATRIX: dict[str, list[str]] = _provision.ROLE_MATRIX  # type: ignore[assignment]

TENANT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _Result:
    def __init__(self, rows: list | None = None, scalar=None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def all(self):  # noqa: ANN201
        return self._rows

    def first(self):  # noqa: ANN201
        return self._rows[0] if self._rows else None

    def scalar_one(self):  # noqa: ANN201
        return self._scalar if self._scalar is not None else 0

    def scalar_one_or_none(self):  # noqa: ANN201
        return self._scalar

    def scalars(self):  # noqa: ANN201
        return self

    def unique(self):  # noqa: ANN201
        return self


class _StubSession:
    """Inert AsyncSession: reads resolve to "nothing there" (404), not 403.

    Deliberately returns no rows so a caller that SHOULD have been refused by
    the authorization gate but was not lands on a data-plane 404 — a status the
    matrix can distinguish cleanly from 403.
    """

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _Result()

    async def get(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None

    def add(self, *args, **kwargs) -> None:  # noqa: ANN002
        return None

    def add_all(self, *args, **kwargs) -> None:  # noqa: ANN002
        return None

    def delete(self, *args, **kwargs) -> None:  # noqa: ANN002
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _ctx_for(role_code: str, *, platform_admin: bool = False) -> TenantContext:
    perms = set(ROLE_MATRIX.get(role_code, []))
    user = AuthedUser(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        role_code=role_code,
        is_platform_admin=platform_admin,
    )
    return TenantContext(
        session=_StubSession(),
        user=user,
        tenant_id=TENANT_ID,
        role_code=role_code,
        permission_codes=perms,
    )


async def _status_for(app, ctx, method: str, path: str, body=None) -> int:  # noqa: ANN001
    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _stub_db(ctx.session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=10) as client:
        response = await client.request(method, path, json=body)
    return response.status_code


def _stub_db(session):  # noqa: ANN001, ANN201
    async def _get_db():
        yield session

    return _get_db


@pytest.fixture(autouse=True)
def _in_memory_secret_store(monkeypatch):
    """Keep allow-path handlers off the real secret store / database.

    A request that correctly PASSES the role gate still runs its endpoint body;
    that body may reach `get_secret_store()`. Pin it to the in-memory store so
    the assertion measures the authorization gate, not incidental I/O.
    """
    from app.core.secrets import InMemorySecretStore, set_secret_store

    set_secret_store(InMemorySecretStore())
    yield


# (route_id, method, path, required_permission_or_None, extra_body)
# A required_permission of None means the route is on the §160 platform-admin
# PLANE (gated by the global is_platform_admin claim, NOT a tenant permission).
_PRIVILEGED_ROUTES: list[tuple[str, str, str, str | None, dict]] = [
    (
        "upsert_flag",
        "PUT",
        "/api/v1/platform/flags/loadtest-feature",
        "settings:write",
        {},
    ),
    (
        "create_secret",
        "POST",
        "/api/v1/platform/secrets",
        "settings:write",
        {"provider": "whatsapp", "vault_key": "k", "value": "v"},
    ),
    (
        # THE DEFECT THIS SUITE WAS WRITTEN TO FIND: rotates the tenant's live
        # channel credential. Its sibling create_secret requires settings:write;
        # this one shipped with no role gate at all.
        "rotate_secret",
        "POST",
        f"/api/v1/platform/secrets/{'whatsapp'}/rotate",
        "settings:write",
        {"new_value": "stolen-value"},
    ),
    (
        "upsert_integration",
        "POST",
        "/api/v1/integrations",
        "settings:write",
        {"provider": "whatsapp"},
    ),
    (
        "delete_ai_memory",
        "DELETE",
        f"/api/v1/ai/memories/{uuid.uuid4()}",
        "settings:write",
        {},
    ),
    (
        "delete_segment",
        "DELETE",
        f"/api/v1/segments/{uuid.uuid4()}",
        "marketing:write",
        {},
    ),
]

# §160 platform-admin plane — NO tenant role, not even owner, may reach these.
_PLATFORM_ADMIN_ROUTES: list[tuple[str, str, str, dict]] = [
    ("admin_list_tenants", "GET", "/api/v1/platform/admin/tenants", {}),
    (
        "admin_break_glass",
        "POST",
        "/api/v1/platform/admin/break-glass",
        {
            "tenant_id": str(TENANT_ID),
            "action": "read_data",
            "resource_type": "customer",
            "resource_id": "1",
            "reason": "incident 1234 investigation window",
        },
    ),
]


# Route ids whose ALLOW side is safe to execute against the inert stub session
# (endpoint body touches only ctx.session / the in-memory store). Every route is
# exercised in full on the DENY side regardless.
_ALLOW_SAFE = {
    "rotate_secret",
    "upsert_flag",
    "delete_ai_memory",
    "delete_segment",
}


@pytest.mark.parametrize("role", ["owner", "manager", "staff"])
@pytest.mark.parametrize(
    ("route_id", "method", "path", "required", "body"),
    _PRIVILEGED_ROUTES,
    ids=[r[0] for r in _PRIVILEGED_ROUTES],
)
async def test_roles_without_permission_are_refused(
    route_id, method, path, required, body, role
) -> None:  # noqa: ANN001
    """DENY: a role that does not hold the route's permission is refused 403.

    This is the security-critical direction and is checked for every route. When
    the gate is missing (the rotate_secret hole) the request falls through to the
    handler — here a stubbed data plane returning 404 — which is NOT a 403, so
    the assertion fails and names the hole.
    """
    holds = required in ROLE_MATRIX.get(role, [])
    if holds:
        pytest.skip("allow-direction is covered by test_permission_gate_allows_its_roles")
    app = _authz_app()
    status = await _status_for(app, _ctx_for(role), method, path, body or None)
    assert status == 403, (
        f"{route_id}: role '{role}' does NOT hold '{required}' yet was not "
        f"refused at the authorization layer (got {status}; a non-403 means the "
        "request reached the handler — the UI hides this button but the API does "
        "not enforce it)"
    )


@pytest.mark.parametrize("role", ["owner", "manager"])
@pytest.mark.parametrize(
    ("route_id", "method", "path", "required", "body"),
    [r for r in _PRIVILEGED_ROUTES if r[0] in _ALLOW_SAFE],
    ids=sorted(_ALLOW_SAFE),
)
async def test_roles_holding_the_permission_reach_the_handler(
    route_id, method, path, required, body, role
) -> None:  # noqa: ANN001
    """ALLOW: the gate is a permission test, not a blanket denial.

    Only routes whose handler touches nothing but ``ctx.session`` (stubbed) or the
    in-memory secret store are exercised here — the rest are covered in full on
    the DENY side, where the assertion is the security-critical one.

    This direction is what makes the DENY suite non-vacuous: a route that denied
    everyone would be green there and red here. ``rotate_secret`` is the case in
    point — it shipped with no gate at all (deny red), and now its holder passes
    and its non-holder is refused (one green each side, neither reachable alone).
    """
    holds = required in ROLE_MATRIX.get(role, [])
    if not holds:
        pytest.skip("deny-direction is covered by test_roles_without_permission_are_refused")
    app = _authz_app()
    status = await _status_for(app, _ctx_for(role), method, path, body or None)
    assert status not in (401, 403), (
        f"{route_id}: role '{role}' holds '{required}' but was refused by the "
        f"authorization layer ({status}) — the gate denies a caller entitled to pass"
    )


@pytest.mark.parametrize("permission", ["settings:write", "billing:write", "marketing:write"])
@pytest.mark.parametrize("role", ["owner", "manager", "staff"])
async def test_permission_gate_allows_its_roles(role, permission) -> None:  # noqa: ANN001
    """Positive control at the gate itself: `require_permission` is not a blanket
    denial. It passes a caller holding the code and raises for one who does not.

    Executed directly (no HTTP, no endpoint body) so it is fast and cannot touch
    real infrastructure — it asserts the RBAC primitive every gated route leans
    on. Together with the DENY suite this shows the primitive is correct AND that
    a route missing the primitive (rotate_secret) is the failure, not the gate.
    """
    from app.core.errors import PermissionDeniedError
    from app.modules.identity.deps import require_permission

    gate = require_permission(permission)
    ctx = _ctx_for(role)
    if permission in ROLE_MATRIX.get(role, []):
        assert await gate(ctx) is ctx
    else:
        with pytest.raises(PermissionDeniedError):
            await gate(ctx)


@pytest.mark.parametrize("role", ["owner", "manager", "staff"])
@pytest.mark.parametrize(
    ("route_id", "method", "path", "body"),
    _PLATFORM_ADMIN_ROUTES,
    ids=[r[0] for r in _PLATFORM_ADMIN_ROUTES],
)
async def test_platform_admin_plane_refused_for_every_tenant_role(
    route_id, method, path, body, role
) -> None:  # noqa: ANN001
    """§160: a tenant role — even owner with settings:write — is not a platform admin.

    The break-glass / cross-tenant admin plane is gated by the GLOBAL
    is_platform_admin JWT claim, never by a tenant permission code. A tenant
    admin must not be able to mint break-glass capabilities for any tenant.
    """
    app = _authz_app()
    status = await _status_for(app, _ctx_for(role, platform_admin=False), method, path, body)
    assert status == 403, (
        f"{route_id}: tenant role '{role}' (not a platform admin) reached the "
        f"platform-admin plane (got {status}); §160 requires 403"
    )


async def test_platform_admin_plane_reachable_for_real_platform_admin() -> None:
    """Positive control: the plane is not a blanket denial — a genuine platform
    admin passes the §160 gate and reaches the handler (stub session -> 200/404,
    never a 401/403)."""
    app = _authz_app()
    ctx = _ctx_for("owner", platform_admin=True)
    status = await _status_for(app, ctx, "GET", "/api/v1/platform/admin/tenants", None)
    assert status not in (401, 403), (
        f"a real platform admin was refused the §160 plane ({status})"
    )


def test_the_seed_itself_matches_the_documented_role_model() -> None:
    """Guard the fixture: owner ⊇ manager ⊇ staff, and the two exclusions that
    define 'manager' (no settings:write / billing:write) actually hold."""
    owner, manager, staff = (
        set(ROLE_MATRIX["owner"]),
        set(ROLE_MATRIX["manager"]),
        set(ROLE_MATRIX["staff"]),
    )
    assert staff <= manager <= owner
    assert "settings:write" in owner and "settings:write" not in manager
    assert "billing:write" in owner and "billing:write" not in manager
    assert "settings:write" not in staff


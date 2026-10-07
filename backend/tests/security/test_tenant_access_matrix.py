"""§115 CROSS-TENANT ACCESS / IDOR / BROKEN AUTHORIZATION — the access matrix.

The spec's one hard security line, applied across the resource surface: a token
minted for tenant A must never read or mutate tenant B's rows — not through a
path id, not through a list filter or a search term, not through a bulk merge or
CSV import, not through the §151 workspace/location hierarchy, and not through
the §147 break-glass plane.

Two layers, because "a test exists" is not "the guarantee holds":

* LAYER 1 — STRUCTURAL (no database, runs everywhere): every route that is not a
  deliberately-public entry point must resolve its tenant through
  `get_tenant_ctx`, which verifies MEMBERSHIP and binds the RLS GUC. A single
  resource route that dropped that dependency would be readable by any bearer
  token across the fleet; this test fails the moment one appears. It enumerates
  routes from the live router graph, so new routes are covered automatically.

* LAYER 2 — BEHAVIOURAL (DB-backed; skips loudly without DATABASE_URL_APP_ADMIN,
  the venue CI provides): seed a real row in a second tenant B and drive the REAL
  service functions the routes delegate to, while the session is bound to tenant
  A. Each must come back not-found / refused / empty for B's data and healthy for
  A's own. The explicit `tenant_id` filter plus RLS is the pair that makes this
  hold; the assertion is what proves neither can be removed unnoticed.

Run locally: Layer 1 only (Layer 2 skips). In CI: both, on real PostgreSQL as the
non-BYPASSRLS `sales_app` role — see tests/conftest.py, the ROLE is the point: a
BYPASSRLS role would make every isolation assertion here vacuous.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.routing import APIRoute, _IncludedRouter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.security import hash_password
from app.modules.catalog.external.csv_import import CSVImportService
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService, IdentityMergeService
from app.modules.identity.deps import AuthedUser, resolve_scope
from app.modules.identity.models import Location, Role, Tenant, TenantUser, User, Workspace
from app.modules.orders.models import Order
from app.modules.orders.service import OrderService
from app.modules.platform.router import _require_platform_admin

# ---------------------------------------------------------------------------
# Deliberately-public surfaces: everything here resolves tenancy by some other
# contract (a bearer login, a signed webhook, a visitor token, an SSE ticket)
# and is covered by dedicated suites. They are enumerated so an ACCIDENTAL
# addition to the resource surface can never hide inside "public".
# ---------------------------------------------------------------------------
_ALLOWED_PUBLIC_ROUTES: frozenset[str] = frozenset(
    {
        "POST /api/v1/auth/register",
        "POST /api/v1/auth/login",
        "POST /api/v1/auth/refresh",
        "POST /api/v1/auth/logout",
        "GET /api/v1/auth/me",
        "POST /api/v1/auth/switch-tenant",
        "POST /api/v1/auth/mfa/verify",
        "POST /api/v1/auth/mfa/enroll",
        "POST /api/v1/auth/mfa/confirm",
        "POST /api/v1/auth/mfa/disable",
        "POST /api/v1/invitations/accept",
        # account-global recovery (docs/ACCOUNT_RECOVERY.md): password reset
        # runs BEFORE any tenant scope exists; the token row is account-scoped
        # and inaccessible to Supabase public roles by migration.
        "POST /api/v1/auth/password-reset/request",
        "POST /api/v1/auth/password-reset/confirm",
        # Email verification rides the same account-global contract as the
        # password-reset pair above: the emailed token IS the credential
        # (fd2026100411 rows are possession-scoped), and the resend endpoint
        # answers a uniform neutral 202 for every address, so neither route
        # reads tenant-scoped data or binds a GUC.
        "POST /api/v1/auth/verify-email",
        "POST /api/v1/auth/resend-verification",
        # Website Platform bridge (modules/catalog/website_platform.py): the
        # caller is the EXTERNAL website builder, not a browser session —
        # tenancy resolves from the X-Website-Platform-Key header contract
        # (_resolve_tenant_key), which binds the tenant and is covered by the
        # website-bridge suite. Declared here so the matrix sees the
        # alternative resolver instead of flagging it as unguarded.
        "GET /api/v1/website-platform/catalog/products",
        # SEC-1: mints a 5-minute stream-scoped credential from the caller's
        # OWN authed identity — reads no tenant-scoped row, binds no GUC.
        "POST /api/v1/realtime/stream-token",
        # public webchat visitor ingress (widget public key + visitor token)
        "POST /api/v1/webchat/{public_key}/messages",
        # provider webhook entrypoints (signature-verified inside the handler)
        "GET /api/v1/webhooks/{channel}",
        "POST /api/v1/webhooks/{channel}",
        # Meta OAuth callback: PUBLIC by design — the 10-minute server-signed
        # oauth_state JWT minted to a settings:write holder is the
        # authorization, and the route only ever redirects back to the
        # frontend with an outcome marker (it reads no tenant data).
        "GET /api/v1/integrations/meta/oauth/callback",
        # SSE streams carry their own ticket auth in-body
        "GET /api/v1/conversations/stream",
        "GET /api/v1/realtime/events",
        # load-balancer probes
        "GET /healthz",
        "GET /readyz",
        # §O10 Prometheus exposition. It carries no tenant context and a scraper
        # has no JWT to present, so it sits at the root beside the probes and
        # admits itself a different way: a constant-time internal service token
        # wherever SECURE_ENVIRONMENT is on, 503 if that token is not configured.
        # What makes this safe to declare is the closed `stream` label set in
        # app/core/metrics.py — an open label there would publish tenant ids.
        "GET /metrics",
    }
)

#: Routes mounted on the app itself rather than under the `/api/v1` router. The
#: prefix below is derived from membership here, NOT from a guess about the path:
#: a heuristic that assumes "everything except the two probes is versioned" turns
#: a new root route into a phantom `/api/v1/...` and reports the wrong URL in a
#: security failure.
_ROOT_MOUNTED: frozenset[str] = frozenset({"/healthz", "/readyz", "/metrics"})


def _walk_routes(app):  # noqa: ANN001, ANN201
    """Flatten FastAPI's lazily-included routers into concrete APIRoutes."""
    collected: list[APIRoute] = []

    def walk(routes) -> None:  # noqa: ANN001
        for r in routes:
            if isinstance(r, _IncludedRouter):
                walk(r.original_router.routes)
            elif isinstance(r, APIRoute):
                collected.append(r)

    walk(app.routes)
    return collected


def _dep_names(route: APIRoute) -> set[str]:
    names: set[str] = set()

    def collect(dependant) -> None:  # noqa: ANN001
        for sub in dependant.dependencies:
            names.add(getattr(sub.call, "__name__", ""))
            collect(sub)

    collect(route.dependant)
    return names


def _resource_routes():  # noqa: ANN201
    from app.main import create_app

    app = create_app()
    out: list[tuple[str, APIRoute]] = []
    for route in _walk_routes(app):
        prefix = "" if route.path in _ROOT_MOUNTED else "/api/v1"
        for method in sorted(m for m in route.methods if m != "HEAD"):
            out.append((f"{method} {prefix}{route.path}", route))
    return out


# ============================================================ LAYER 1: structure


def test_every_resource_route_resolves_tenant_or_is_declared_public() -> None:
    """No tenant data route may be reachable without `get_tenant_ctx`.

    get_tenant_ctx is the only code path that proves the caller is a MEMBER of
    the tenant the token names and binds the RLS GUC. A resource route missing it
    is a fleet-wide read for any authenticated bearer — the IDOR class §115 names.
    """
    offenders: list[str] = []
    for key, route in _resource_routes():
        if key in _ALLOWED_PUBLIC_ROUTES:
            continue
        dep_names = _dep_names(route)
        if "get_tenant_ctx" not in dep_names:
            offenders.append(f"{key}  deps={sorted(dep_names)}")
    assert not offenders, (
        "resource routes reachable without get_tenant_ctx (no membership check, "
        "no RLS binding):\n" + "\n".join(sorted(offenders))
    )


def test_allowed_public_list_is_still_exact() -> None:
    """The public allow-list is a fence, not a wish: every entry must still be a
    real route, so the list cannot silently accrete stale or over-broad entries."""
    live = {key for key, _r in _resource_routes()}
    stale = _ALLOWED_PUBLIC_ROUTES - live
    assert not stale, f"_ALLOWED_PUBLIC_ROUTES names routes that no longer exist: {stale}"


# ============================================================ LAYER 2: behaviour


async def _seed_foreign_tenant(db: AsyncSession, *, tag: str) -> uuid.UUID:
    """Create tenant B (+ owner + membership), bound to B, and return its id.

    Replays the tests/conftest.py::tenant_ctx bootstrap: create the user, set the
    user GUC so the tenant_users self-access policy admits the membership row,
    then bind tenant B so its rows are writable. The caller re-binds to A after
    seeding B's data.
    """
    owner = User(
        email=f"b-owner-{uuid.uuid4().hex[:10]}@test.local",
        password_hash=hash_password("secret-password"),
        full_name="Tenant B Owner",
    )
    tenant_b = Tenant(slug=f"b-{tag}-{uuid.uuid4().hex[:8]}", name="Tenant B")
    db.add_all([tenant_b, owner])
    await db.flush()
    await db.execute(
        text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(owner.id)}
    )
    owner_role_id = (await db.execute(select(Role.id).where(Role.code == "owner"))).scalar_one()
    db.add(TenantUser(tenant_id=tenant_b.id, user_id=owner.id, role_id=owner_role_id))
    await db.flush()
    await bind_tenant(db, tenant_b.id)
    return tenant_b.id


async def _customer_in(db: AsyncSession, tenant_id, name: str) -> Customer:  # noqa: ANN001
    customer = Customer(tenant_id=tenant_id, name=name)
    db.add(customer)
    await db.flush()
    return customer


async def _order_in(db: AsyncSession, tenant_id, customer_id) -> Order:  # noqa: ANN001
    order = Order(
        tenant_id=tenant_id,
        number=f"MAT-{uuid.uuid4().hex[:6]}",
        customer_id=customer_id,
        status="pending",
        currency="EGP",
        grand_total=Decimal("10.00"),
        subtotal=Decimal("10.00"),
        discount_total=Decimal("0"),
        shipping_total=Decimal("0"),
        tax_total=Decimal("0"),
        placed_at=datetime.now(UTC),
    )
    db.add(order)
    await db.flush()
    return order


@pytest.mark.parametrize("resource", ["customer", "order", "conversation"])
async def test_foreign_row_is_not_readable_by_path_id(
    db, tenant_ctx, resource  # noqa: ANN001
) -> None:
    """Tenant A reading B's row by its primary-key id: not-found, never a leak."""
    tenant_b = await _seed_foreign_tenant(db, tag=f"id-{resource}")
    if resource == "customer":
        row = await _customer_in(db, tenant_b, "B Customer")
    elif resource == "order":
        cust = await _customer_in(db, tenant_b, "B Owner Cust")
        row = await _order_in(db, tenant_b, cust.id)
    else:  # conversation
        cust = await _customer_in(db, tenant_b, "B Conv Cust")
        row = await ConversationService.get_or_create(
            db, tenant_b, customer_id=cust.id, channel="webchat"
        )
    row_id = row.id

    await bind_tenant(db, tenant_ctx.tenant_id)
    if resource == "customer":
        with pytest.raises(NotFoundError):
            await CustomerService.get(db, tenant_ctx.tenant_id, row_id)
    elif resource == "order":
        with pytest.raises(NotFoundError):
            await OrderService.get(db, tenant_ctx.tenant_id, row_id)
    else:
        with pytest.raises(NotFoundError):
            await ConversationService.get(db, tenant_ctx.tenant_id, row_id)


async def test_foreign_row_is_not_mutable_by_path_id(db, tenant_ctx) -> None:  # noqa: ANN001
    """Read-only isolation is worthless if the WRITE door is open: block/archive
    must refuse a foreign row exactly as the read does."""
    tenant_b = await _seed_foreign_tenant(db, tag="mut")
    victim = await _customer_in(db, tenant_b, "Victim")
    await bind_tenant(db, tenant_ctx.tenant_id)
    with pytest.raises(NotFoundError):
        await CustomerService.set_blocked(
            db, tenant_ctx.tenant_id, victim.id, blocked=True
        )
    with pytest.raises(NotFoundError):
        await CustomerService.archive(
            db, tenant_ctx.tenant_id, victim.id, deleted_by=tenant_ctx.user.id
        )


async def test_list_and_search_never_leak_foreign_rows(db, tenant_ctx) -> None:  # noqa: ANN001
    """List filters and free-text search are scoped by tenant, not just by page."""
    secret = f"ZZSECRETONLY {uuid.uuid4().hex[:6]}"
    tenant_b = await _seed_foreign_tenant(db, tag="list")
    await _customer_in(db, tenant_b, secret)
    # _seed_foreign_tenant left the GUC bound to B; A's own row can only be
    # minted once the session is bound to A again (RLS WITH CHECK refuses the
    # write otherwise — seen in CI as InsufficientPrivilegeError).
    await bind_tenant(db, tenant_ctx.tenant_id)
    await _customer_in(db, tenant_ctx.tenant_id, "Alpha Ownco")  # one of A's own

    listing = await CustomerService.list_customers(db, tenant_ctx.tenant_id, limit=200)
    assert all(c.name != secret for c in listing), "foreign customer surfaced in list"
    assert any(c.name == "Alpha Ownco" for c in listing)

    hits = await CustomerService.list_customers(
        db, tenant_ctx.tenant_id, search=secret, limit=200
    )
    assert hits == [], f"cross-tenant search leaked {len(hits)} rows"

    # the SAME search does find it when bound to B (proves the row is real)
    await bind_tenant(db, tenant_b)
    b_hits = await CustomerService.list_customers(db, tenant_b, search=secret, limit=200)
    assert len(b_hits) == 1


async def test_identity_merge_cannot_cross_tenants(db, tenant_ctx) -> None:  # noqa: ANN001
    """POST /customers/merge with B's ids while acting as A must refuse — a merge
    rewrites history, so BOTH rows must be visible to the caller first."""
    tenant_b = await _seed_foreign_tenant(db, tag="merge")
    b_source = await _customer_in(db, tenant_b, "B source")
    # _seed_foreign_tenant left the GUC bound to B; A's canonical row can only
    # be minted once the session is bound to A again (RLS WITH CHECK refuses
    # the write otherwise — seen in CI as InsufficientPrivilegeError).
    await bind_tenant(db, tenant_ctx.tenant_id)
    a_only = await _customer_in(db, tenant_ctx.tenant_id, "A canonical")

    with pytest.raises(NotFoundError):
        await IdentityMergeService.merge(
            db,
            tenant_ctx.tenant_id,
            canonical_customer_id=a_only.id,
            merged_away_customer_id=b_source.id,
            performed_by_user_id=tenant_ctx.user.id,
        )


async def test_csv_import_lands_only_in_the_callers_tenant(db, tenant_ctx) -> None:  # noqa: ANN001
    """Bulk import is scoped by the caller's tenant_id, never by a column the CSV
    could smuggle. A row imported as A is invisible to a foreign tenant B."""
    marker = f"IMPORTED {uuid.uuid4().hex[:8]}"
    csv = f"name,phone\n{marker},+201000000001\n"
    await bind_tenant(db, tenant_ctx.tenant_id)
    report = await CSVImportService.import_customers(
        db, tenant_ctx.tenant_id, raw_csv=csv, customer_service=CustomerService
    )
    assert report.imported >= 1
    a_hits = await CustomerService.list_customers(
        db, tenant_ctx.tenant_id, search=marker, limit=10
    )
    assert len(a_hits) == 1

    tenant_b = await _seed_foreign_tenant(db, tag="import")
    await bind_tenant(db, tenant_b)
    b_hits = await CustomerService.list_customers(db, tenant_b, search=marker, limit=10)
    assert b_hits == []


async def test_workspace_scope_rejects_foreign_hierarchy(db, tenant_ctx) -> None:  # noqa: ANN001
    """§151: resolve_scope fails closed on a workspace owned by another tenant —
    a scope header can never widen a request across tenants."""
    tenant_b = await _seed_foreign_tenant(db, tag="ws")
    ws_b = Workspace(tenant_id=tenant_b, name="B Workspace", slug=f"bws-{uuid.uuid4().hex[:6]}")
    db.add(ws_b)
    await db.flush()
    ws_b_id = ws_b.id

    await bind_tenant(db, tenant_ctx.tenant_id)
    with pytest.raises(PermissionDeniedError):
        await resolve_scope(
            db,
            tenant_id=tenant_ctx.tenant_id,
            user_id=tenant_ctx.user.id,
            workspace_id=ws_b_id,
        )


async def test_location_scope_requires_same_tenant_grant(db, tenant_ctx) -> None:  # noqa: ANN001
    """A location id from tenant B is refused for tenant A at the tenancy check,
    before the location-grant lookup even runs (deps.resolve_scope checks twice)."""
    tenant_b = await _seed_foreign_tenant(db, tag="loc")
    ws_b = Workspace(tenant_id=tenant_b, name="B WS", slug=f"bws-{uuid.uuid4().hex[:6]}")
    db.add(ws_b)
    await db.flush()
    loc_b = Location(
        tenant_id=tenant_b,
        workspace_id=ws_b.id,
        name="B Loc",
        code=f"blc{uuid.uuid4().hex[:6]}",
    )
    db.add(loc_b)
    await db.flush()
    loc_b_id = loc_b.id

    await bind_tenant(db, tenant_ctx.tenant_id)
    with pytest.raises(PermissionDeniedError):
        await resolve_scope(
            db,
            tenant_id=tenant_ctx.tenant_id,
            user_id=tenant_ctx.user.id,
            location_id=loc_b_id,
        )


def test_break_glass_plane_rejects_a_tenant_admin() -> None:
    """§147/§160 (structural, no DB): a tenant owner — full RBAC inside their own
    tenant — is NOT a platform admin and cannot enter the cross-tenant plane.

    The plane is the one door that intentionally spans tenants; this proves it
    opens only on the global claim, never on tenant membership.
    """
    class _Ctx:
        def __init__(self, platform_admin: bool) -> None:
            self.user = AuthedUser(
                id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                role_code="owner",
                is_platform_admin=platform_admin,
            )

    with pytest.raises(PermissionDeniedError):
        _require_platform_admin(_Ctx(platform_admin=False))
    # positive control: the gate is the claim, not a blanket denial
    _require_platform_admin(_Ctx(platform_admin=True))

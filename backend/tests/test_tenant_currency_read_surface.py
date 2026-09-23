"""W5 (item C) — a tenant's currency has to be READABLE, not only writable.

§47 added ``PUT /tenants/{tenant_id}/currency`` (audited, refuses a tenant that
already traded in another currency), but no GET ever existed. So the write
surface was reachable and the value it stored was invisible to any client: the
money a screen renders has a currency, and without a read endpoint the frontend
can only hard-code one. This is the smallest honest read to close that gap.

The first two cases are DB-free and check the ROUTE — a permission moved into
the endpoint body (where a caller could bypass it) still shows up here, and they
run on a laptop with no app database. The rest drive the real ASGI stack over a
DB and prove the read is scoped: a permitted caller sees their tenant's code,
another tenant's caller does not.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.identity.router import tenants_router


def _permission_codes(routes, path: str, method: str) -> set[str]:
    """RBAC codes a route declares, found by walking its dependency tree."""
    for route in routes:
        if route.path == path and method in route.methods:
            codes: set[str] = set()
            stack = list(route.dependant.dependencies)
            while stack:
                dependant = stack.pop()
                code = getattr(dependant.call, "code", None)
                if code:
                    codes.add(code)
                stack.extend(dependant.dependencies)
            return codes
    raise AssertionError(f"{method} {path} is not routed")


# --------------------------------------------------- DB-free: the route ------


def test_the_currency_read_route_is_registered() -> None:
    """The endpoint the frontend needs to know which symbol to render."""
    path = "/tenants/{tenant_id}/currency"
    assert any(
        r.path == path and "GET" in r.methods for r in tenants_router.routes
    ), "GET /tenants/{tenant_id}/currency must be routed on tenants_router"


def test_reading_the_currency_is_gated_by_a_permission() -> None:
    """It is not open to every logged-in member: it names money, so it is gated,
    and gated at the ROUTE (the same ``require_permission`` the write uses), not
    in the handler body."""
    codes = _permission_codes(tenants_router.routes, "/tenants/{tenant_id}/currency", "GET")
    assert codes, "the currency read must declare a require_permission gate"


# ----------------------------------------------------- driven over a DB ------


def _client(db: AsyncSession, *, ctx_tenant_id: uuid.UUID, perms: set[str]) -> AsyncClient:
    """Real ASGI stack with ONLY the auth context swapped, so the route, its
    gate and its tenant-match rule are the things under test."""
    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=ctx_tenant_id, role_code="owner"),
            tenant_id=ctx_tenant_id,
            role_code="owner",
            permission_codes=perms,
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_permitted_caller_reads_their_own_tenants_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    stored = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    stored.currency = "SAR"
    await db.flush()

    async with _client(db, ctx_tenant_id=tenant_ctx.tenant_id, perms={"settings:read"}) as client:
        response = await client.get(f"/api/v1/tenants/{tenant_ctx.tenant_id}/currency")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"tenant_id": str(tenant_ctx.tenant_id), "currency": "SAR"}


async def test_a_caller_from_another_tenant_cannot_read_it(
    db: AsyncSession, tenant_ctx
) -> None:
    """Tenancy is the point: the tenant id in the path must match the caller's."""
    async with _client(db, ctx_tenant_id=uuid.uuid4(), perms={"settings:read"}) as client:
        response = await client.get(f"/api/v1/tenants/{tenant_ctx.tenant_id}/currency")

    assert response.status_code == 403, response.text


async def test_a_reader_without_the_permission_is_refused(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _client(db, ctx_tenant_id=tenant_ctx.tenant_id, perms=set()) as client:
        response = await client.get(f"/api/v1/tenants/{tenant_ctx.tenant_id}/currency")

    assert response.status_code == 403, response.text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

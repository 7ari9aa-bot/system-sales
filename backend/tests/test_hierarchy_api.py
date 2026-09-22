"""§151 Q3 — hierarchy management API (workspaces, locations, location grants).

Identity-scoped admin surface under /api/v1/hierarchy, gated by the existing
RBAC codes (settings:read / settings:write — the same pair that guards tenant
settings and invitations). Tenancy is taken from the request context, never
from a path id: every row is filtered by BOTH ctx.tenant_id and the bound RLS
GUC, so a foreign id is a 404, not a leak.

Location grants are the interesting RLS case: user_location_access is keyed on
app.user_id (members see their own rows), so an OWNER managing someone else's
access only works because migration f151ee151ee1 adds a tenant-owner OR-clause
to the location_access policy — tests below exercise exactly that path, as the
real sales_app role under FORCE RLS.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant, TenantUser, User

ALL_PERMS = {"settings:read", "settings:write"}


def _make_ctx(db: AsyncSession, tenant_ctx, perms: set[str]) -> TenantContext:
    return TenantContext(
        session=db,
        user=AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes=perms,
    )


def _app(ctx: TenantContext) -> FastAPI:
    app = create_app()

    async def _ctx() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def _http(app: FastAPI):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _member(db: AsyncSession, tenant_ctx) -> User:
    """A second user with an explicit membership row (grants must target members)."""
    member = User(
        email=f"member-{uuid.uuid4().hex[:10]}@test.local",
        password_hash=hash_password("secret-password"),
        full_name="Staff Member",
    )
    db.add(member)
    await db.flush()
    db.add(
        TenantUser(
            tenant_id=tenant_ctx.tenant_id, user_id=member.id, role_id=tenant_ctx.role.id
        )
    )
    await db.flush()
    return member


async def test_workspace_create_list_update(db: AsyncSession, tenant_ctx) -> None:
    app = _app(_make_ctx(db, tenant_ctx, ALL_PERMS))
    async with await _http(app) as client:
        created = await client.post(
            "/api/v1/hierarchy/workspaces",
            json={"name": "Downtown", "slug": "downtown"},
        )
        assert created.status_code == 201, created.text
        ws = created.json()
        assert ws["name"] == "Downtown" and ws["slug"] == "downtown"
        assert ws["is_active"] is True

        listed = await client.get("/api/v1/hierarchy/workspaces")
        assert listed.status_code == 200
        assert [w["id"] for w in listed.json()["items"]] == [ws["id"]]

        patched = await client.patch(
            f"/api/v1/hierarchy/workspaces/{ws['id']}", json={"is_active": False}
        )
        assert patched.status_code == 200
        assert patched.json()["is_active"] is False


async def test_workspace_slug_conflicts_within_tenant(db: AsyncSession, tenant_ctx) -> None:
    app = _app(_make_ctx(db, tenant_ctx, ALL_PERMS))
    async with await _http(app) as client:
        first = await client.post(
            "/api/v1/hierarchy/workspaces", json={"name": "A", "slug": "dup"}
        )
        assert first.status_code == 201
        second = await client.post(
            "/api/v1/hierarchy/workspaces", json={"name": "B", "slug": "dup"}
        )
        assert second.status_code == 409


async def test_workspace_foreign_tenant_is_404_not_leak(db: AsyncSession, tenant_ctx) -> None:
    # A workspace in ANOTHER tenant, seeded under that tenant's GUC binding.
    other = Tenant(slug=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    db.add(other)
    await db.flush()
    from app.core.db import bind_tenant

    await bind_tenant(db, other.id)
    ws_out = sa.text(
        "INSERT INTO workspaces (id, tenant_id, name, slug, is_active, created_at, updated_at)"
        " VALUES (:id, :t, 'Foreign', 'foreign', true, now(), now())"
    )
    foreign_id = uuid.uuid4()
    await db.execute(ws_out, {"id": foreign_id, "t": other.id})
    await bind_tenant(db, tenant_ctx.tenant_id)

    app = _app(_make_ctx(db, tenant_ctx, ALL_PERMS))
    async with await _http(app) as client:
        got = await client.get(f"/api/v1/hierarchy/workspaces/{foreign_id}")
        assert got.status_code == 404
        listed = await client.get("/api/v1/hierarchy/workspaces")
        assert foreign_id not in [uuid.UUID(w["id"]) for w in listed.json()["items"]]


async def test_location_crud_under_workspace(db: AsyncSession, tenant_ctx) -> None:
    app = _app(_make_ctx(db, tenant_ctx, ALL_PERMS))
    async with await _http(app) as client:
        ws = (
            await client.post(
                "/api/v1/hierarchy/workspaces", json={"name": "HQ", "slug": "hq"}
            )
        ).json()

        loc = await client.post(
            f"/api/v1/hierarchy/workspaces/{ws['id']}/locations",
            json={"name": "Branch 1", "code": "B1"},
        )
        assert loc.status_code == 201, loc.text
        body = loc.json()
        assert body["workspace_id"] == ws["id"] and body["code"] == "B1"

        # Same code in the SAME workspace conflicts; a different workspace is fine.
        dup = await client.post(
            f"/api/v1/hierarchy/workspaces/{ws['id']}/locations",
            json={"name": "Branch 1b", "code": "B1"},
        )
        assert dup.status_code == 409
        ws2 = (
            await client.post(
                "/api/v1/hierarchy/workspaces", json={"name": "North", "slug": "north"}
            )
        ).json()
        again = await client.post(
            f"/api/v1/hierarchy/workspaces/{ws2['id']}/locations",
            json={"name": "Branch N", "code": "B1"},
        )
        assert again.status_code == 201

        listed = await client.get(f"/api/v1/hierarchy/workspaces/{ws['id']}/locations")
        assert [x["id"] for x in listed.json()["items"]] == [body["id"]]

        patched = await client.patch(
            f"/api/v1/hierarchy/locations/{body['id']}", json={"name": "Renamed"}
        )
        assert patched.status_code == 200 and patched.json()["name"] == "Renamed"


async def test_location_grant_revoke_flow(db: AsyncSession, tenant_ctx) -> None:
    member = await _member(db, tenant_ctx)
    app = _app(_make_ctx(db, tenant_ctx, ALL_PERMS))
    async with await _http(app) as client:
        ws = (
            await client.post(
                "/api/v1/hierarchy/workspaces", json={"name": "HQ", "slug": "hq"}
            )
        ).json()
        loc = (
            await client.post(
                f"/api/v1/hierarchy/workspaces/{ws['id']}/locations",
                json={"name": "Branch"},
            )
        ).json()

        granted = await client.put(
            f"/api/v1/hierarchy/locations/{loc['id']}/access/{member.id}",
            json={"role_override": "staff"},
        )
        assert granted.status_code == 200, granted.text
        assert granted.json()["user_id"] == str(member.id)
        assert granted.json()["role_override"] == "staff"

        # Idempotent PUT: granting twice yields one row, not an error.
        again = await client.put(
            f"/api/v1/hierarchy/locations/{loc['id']}/access/{member.id}", json={}
        )
        assert again.status_code == 200

        rows = await client.get(f"/api/v1/hierarchy/locations/{loc['id']}/access")
        assert rows.status_code == 200
        items = rows.json()["items"]
        assert [r["user_id"] for r in items] == [str(member.id)]

        revoked = await client.delete(
            f"/api/v1/hierarchy/locations/{loc['id']}/access/{member.id}"
        )
        assert revoked.status_code == 204
        after = await client.get(f"/api/v1/hierarchy/locations/{loc['id']}/access")
        assert after.json()["items"] == []


async def test_grant_refuses_non_member(db: AsyncSession, tenant_ctx) -> None:
    app = _app(_make_ctx(db, tenant_ctx, ALL_PERMS))
    async with await _http(app) as client:
        ws = (
            await client.post(
                "/api/v1/hierarchy/workspaces", json={"name": "HQ", "slug": "hq"}
            )
        ).json()
        loc = (
            await client.post(
                f"/api/v1/hierarchy/workspaces/{ws['id']}/locations",
                json={"name": "Branch"},
            )
        ).json()
        stranger = await client.put(
            f"/api/v1/hierarchy/locations/{loc['id']}/access/{uuid.uuid4()}", json={}
        )
        assert stranger.status_code == 400


async def test_read_permitted_without_write_and_write_refused_for_readers(
    db: AsyncSession, tenant_ctx
) -> None:
    app = _app(_make_ctx(db, tenant_ctx, {"settings:read"}))
    async with await _http(app) as client:
        ok = await client.get("/api/v1/hierarchy/workspaces")
        assert ok.status_code == 200
        denied = await client.post(
            "/api/v1/hierarchy/workspaces", json={"name": "X", "slug": "x"}
        )
        assert denied.status_code == 403


async def test_malformed_slug_is_rejected_before_the_database() -> None:
    # No DB needed: body validation rejects the bad slug pattern itself. The
    # stub ctx has a session that cannot execute — if the endpoint were ever
    # reached with a valid-looking body this test would blow up loudly.
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=object(),  # type[arg-type]
            user=None,  # type[arg-type]
            tenant_id=uuid.uuid4(),
            role_code="owner",
            permission_codes=ALL_PERMS,
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    async with await _http(app) as client:
        bad = await client.post(
            "/api/v1/hierarchy/workspaces", json={"name": "N", "slug": "Bad Slug!"}
        )
        assert bad.status_code == 422

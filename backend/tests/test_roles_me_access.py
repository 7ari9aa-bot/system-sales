"""`/roles/me` — the caller's own grant, readable by the accounts that have none.

The Settings Center decided what to show from a role code alone, so a cashier was offered
twenty sections and found out at the save button. The fix needs a cheap, authoritative answer
to "what may I do here", and it must work for the account with the least access — otherwise
the navigation has to guess again.

That is why this route is NOT gated by `settings:read` while `/roles/matrix` still is: the
matrix answers "what does everyone hold" and is an administrative read; this answers "what am
I". The last test pins that difference so a future tidy-up does not "fix" it by adding the
same gate.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from app.modules.identity.models import Permission, Role, role_permissions


async def _ctx_for(db, tenant_ctx, role_code: str) -> TenantContext:
    role = (await db.execute(select(Role).where(Role.code == role_code))).scalar_one()
    codes = {
        code
        for (code,) in (
            await db.execute(
                select(Permission.code)
                .join(role_permissions, role_permissions.c.permission_id == Permission.id)
                .where(role_permissions.c.role_id == role.id)
            )
        ).all()
    }
    return TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code=role_code,
            is_platform_admin=False,
            is_active=True,
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code=role_code,
        permission_codes=codes,
    )


def _app(db, ctx: TenantContext | None):
    app = create_app()

    async def _session():
        yield db

    app.dependency_overrides[get_db] = _session
    if ctx is not None:
        app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    return app


# The three roles the platform seeds (scripts/provision.py ROLES). There is no tenant
# "cashier" role: "cashier" is a POS desk, not a membership.
@pytest.mark.parametrize("role_code", ["owner", "manager", "staff"])
async def test_every_role_can_read_its_own_access(
    db, tenant_ctx, app_sessions_on_test_connection, role_code: str
) -> None:
    ctx = await _ctx_for(db, tenant_ctx, role_code)
    app = _app(db, ctx)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/roles/me")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role_code"] == role_code
    # The answer is the role's real grant, not a hardcoded table on the client.
    assert body["permissions"] == sorted(ctx.permission_codes)


async def test_a_staff_member_learns_it_has_no_settings_grant(
    db, tenant_ctx, app_sessions_on_test_connection
) -> None:
    """The account the old navigation lied to: no settings read at all, and it can see that."""
    ctx = await _ctx_for(db, tenant_ctx, "staff")
    assert "settings:read" not in ctx.permission_codes
    app = _app(db, ctx)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        mine = await client.get("/api/v1/roles/me")
        matrix = await client.get("/api/v1/roles/matrix")

    assert mine.status_code == 200
    assert "settings:read" not in mine.json()["permissions"]
    # ...and the administrative read stays closed to it, which is why /roles/me exists.
    assert matrix.status_code == 403, matrix.text


async def test_an_anonymous_caller_gets_nothing(
    db, tenant_ctx, app_sessions_on_test_connection
) -> None:
    app = _app(db, None)  # no identity override: the real auth chain runs and refuses
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/roles/me")

    assert response.status_code in (401, 403), response.text

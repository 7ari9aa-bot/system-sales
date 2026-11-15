"""The person's own name and the shop's own name — two facts, two owners, two routes.

The profile page used to be a reading surface: the API could not rewrite a display name, so the
screen apologised instead of offering a form. ``PATCH /users/me`` closes that, and ``PUT
/tenants/{id}/name`` does the same for the shop, which is a DIFFERENT fact owned by the workspace
(not the person) and therefore lives on the workspace settings page, gated by ``settings:write``.

Both writes are the cleaned value (whitespace collapses, an invisible name is refused) and both
answer with what the server now holds rather than echoing the request back.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant, User
from app.modules.identity.router import tenants_router, users_router
from app.modules.identity.service import TenantSettingsService, UserService

NAME_PATH = "/tenants/{tenant_id}/name"
PROFILE_PATH = "/users/me"


def _permission_codes(routes, path: str, method: str) -> set[str]:
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


def test_the_workspace_name_route_is_gated_like_the_settings_beside_it() -> None:
    assert _permission_codes(tenants_router.routes, NAME_PATH, "PUT") == {"settings:write"}


def test_the_profile_route_exists_and_needs_only_the_token() -> None:
    # No permission code: every signed-in account may rewrite its OWN name, and the id comes from
    # the token, never from the body. The gate is authentication, which the route inherits.
    assert _permission_codes(users_router.routes, PROFILE_PATH, "PATCH") == set()


def _client(
    db: AsyncSession, *, ctx_tenant_id: uuid.UUID, ctx_user_id: uuid.UUID, perms: set[str]
) -> AsyncClient:
    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=ctx_user_id, tenant_id=ctx_tenant_id, role_code="owner"),
            tenant_id=ctx_tenant_id,
            role_code="owner",
            permission_codes=perms,
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _tenant_name(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    await db.flush()
    row = (await db.execute(sa.select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    await db.refresh(row)
    return row.name


async def _user_name(db: AsyncSession, user_id: uuid.UUID) -> str:
    await db.flush()
    row = (await db.execute(sa.select(User).where(User.id == user_id))).scalar_one()
    await db.refresh(row)
    return row.full_name


# --- the shop's name ------------------------------------------------------------------------


async def test_the_owner_can_rename_the_workspace(db: AsyncSession, tenant_ctx) -> None:
    tenant = await TenantSettingsService.set_name(
        db, tenant_ctx.tenant_id, "متجر النور", actor_user_id=tenant_ctx.user.id
    )
    assert tenant.name == "متجر النور"
    assert await _tenant_name(db, tenant_ctx.tenant_id) == "متجر النور"


async def test_a_rename_collapses_whitespace_before_it_is_stored(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant = await TenantSettingsService.set_name(
        db, tenant_ctx.tenant_id, "  متجر   النور  ", actor_user_id=tenant_ctx.user.id
    )
    assert tenant.name == "متجر النور"


async def test_a_name_that_is_only_whitespace_is_refused(db: AsyncSession, tenant_ctx) -> None:
    before = tenant_ctx.tenant.name
    with pytest.raises(ValidationError):
        await TenantSettingsService.set_name(
            db, tenant_ctx.tenant_id, "   ", actor_user_id=tenant_ctx.user.id
        )
    assert await _tenant_name(db, tenant_ctx.tenant_id) == before


async def test_a_name_longer_than_the_column_is_refused(db: AsyncSession, tenant_ctx) -> None:
    with pytest.raises(ValidationError):
        await TenantSettingsService.set_name(
            db, tenant_ctx.tenant_id, "x" * 256, actor_user_id=tenant_ctx.user.id
        )


async def test_the_rename_leaves_an_audit_row_with_before_and_after(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.platform.models import AuditLog

    before = tenant_ctx.tenant.name
    await TenantSettingsService.set_name(
        db, tenant_ctx.tenant_id, "Shop Two", actor_user_id=tenant_ctx.user.id
    )
    await db.flush()
    row = (
        await db.execute(
            sa.select(AuditLog).where(
                AuditLog.tenant_id == tenant_ctx.tenant_id,
                AuditLog.action == "tenant.name_changed",
            )
        )
    ).scalar_one()
    assert row.before == {"name": before}
    assert row.after == {"name": "Shop Two"}
    assert row.actor_user_id == tenant_ctx.user.id


async def test_renaming_to_the_same_name_is_not_a_change(db: AsyncSession, tenant_ctx) -> None:
    from app.modules.platform.models import AuditLog

    # the stored name with stray whitespace is the same name, so it writes nothing
    for _ in range(2):
        await TenantSettingsService.set_name(
            db, tenant_ctx.tenant_id, " Test   Tenant ", actor_user_id=tenant_ctx.user.id
        )
    await db.flush()
    rows = (
        (
            await db.execute(
                sa.select(AuditLog).where(
                    AuditLog.tenant_id == tenant_ctx.tenant_id,
                    AuditLog.action == "tenant.name_changed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


async def test_an_unknown_tenant_cannot_be_renamed(db: AsyncSession, tenant_ctx) -> None:
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await TenantSettingsService.set_name(
            db, uuid.uuid4(), "Ghost", actor_user_id=tenant_ctx.user.id
        )


async def test_the_rename_route_writes_refuses_and_reports_the_stored_name(
    db: AsyncSession, tenant_ctx
) -> None:
    url = f"/api/v1/tenants/{tenant_ctx.tenant_id}/name"
    async with _client(
        db,
        ctx_tenant_id=tenant_ctx.tenant_id,
        ctx_user_id=tenant_ctx.user.id,
        perms={"settings:write"},
    ) as client:
        ok = await client.put(url, json={"name": "  Rana  Store "})
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"tenant_id": str(tenant_ctx.tenant_id), "name": "Rana Store"}

        blank = await client.put(url, json={"name": "   "})
        assert blank.status_code == 400, blank.text

        empty = await client.put(url, json={"name": ""})
        assert empty.status_code == 422, empty.text

        too_long = await client.put(url, json={"name": "x" * 300})
        assert too_long.status_code == 422, too_long.text

    assert await _tenant_name(db, tenant_ctx.tenant_id) == "Rana Store"


async def test_another_workspace_cannot_be_renamed_and_a_staff_role_is_refused(
    db: AsyncSession, tenant_ctx
) -> None:
    url = f"/api/v1/tenants/{tenant_ctx.tenant_id}/name"
    async with _client(
        db,
        ctx_tenant_id=uuid.uuid4(),
        ctx_user_id=tenant_ctx.user.id,
        perms={"settings:write"},
    ) as client:
        assert (await client.put(url, json={"name": "Hijack"})).status_code == 403

    async with _client(
        db,
        ctx_tenant_id=tenant_ctx.tenant_id,
        ctx_user_id=tenant_ctx.user.id,
        perms={"settings:read"},
    ) as client:
        assert (await client.put(url, json={"name": "Hijack"})).status_code == 403

    assert await _tenant_name(db, tenant_ctx.tenant_id) == tenant_ctx.tenant.name


# --- the person's name ----------------------------------------------------------------------


async def test_the_account_can_rewrite_its_own_name(db: AsyncSession, tenant_ctx) -> None:
    updated = await UserService.update_profile(db, tenant_ctx.user.id, full_name="  Rana   Adel  ")
    assert updated.full_name == "Rana Adel"
    assert await _user_name(db, tenant_ctx.user.id) == "Rana Adel"


async def test_an_invisible_person_name_is_refused(db: AsyncSession, tenant_ctx) -> None:
    before = tenant_ctx.user.full_name
    with pytest.raises(ValidationError):
        await UserService.update_profile(db, tenant_ctx.user.id, full_name="    ")
    assert await _user_name(db, tenant_ctx.user.id) == before


async def test_the_profile_route_answers_with_the_whole_account(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _client(
        db,
        ctx_tenant_id=tenant_ctx.tenant_id,
        ctx_user_id=tenant_ctx.user.id,
        perms=set(),
    ) as client:
        response = await client.patch(PROFILE_PATH, json={"full_name": "  Rana Adel "})
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        # the whole account, so the screen renders what the server holds
        assert body["full_name"] == "Rana Adel"
        assert body["email"] == tenant_ctx.user.email
        assert body["id"] == str(tenant_ctx.user.id)
        assert [t["id"] for t in body["tenants"]] == [str(tenant_ctx.tenant_id)]

        read_back = await client.get(PROFILE_PATH)
        assert read_back.status_code == 200, read_back.text
        assert read_back.json()["full_name"] == "Rana Adel"

        blank = await client.patch(PROFILE_PATH, json={"full_name": "  "})
        assert blank.status_code == 400, blank.text

        empty = await client.patch(PROFILE_PATH, json={"full_name": ""})
        assert empty.status_code == 422, empty.text

    assert await _user_name(db, tenant_ctx.user.id) == "Rana Adel"


async def test_the_profile_route_never_touches_another_account(
    db: AsyncSession, tenant_ctx
) -> None:
    """The id comes from the token, so a body cannot aim the write at someone else."""
    other = User(
        email=f"other-{uuid.uuid4().hex[:10]}@test.local",
        password_hash="not-a-real-hash",
        full_name="Untouched",
    )
    db.add(other)
    await db.flush()

    async with _client(
        db,
        ctx_tenant_id=tenant_ctx.tenant_id,
        ctx_user_id=tenant_ctx.user.id,
        perms=set(),
    ) as client:
        response = await client.patch(
            PROFILE_PATH,
            json={"full_name": "Rana", "id": str(other.id), "email": "evil@test.local"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["id"] == str(tenant_ctx.user.id)

    assert await _user_name(db, other.id) == "Untouched"
    assert await _user_name(db, tenant_ctx.user.id) == "Rana"


# --- two-step verification, as the account reports it ---------------------------------------


async def test_the_account_says_two_step_is_off_until_it_is_confirmed(
    db: AsyncSession, tenant_ctx
) -> None:
    """The security screen used to apologise that it could not read this state."""
    from app.modules.identity.models import UserMfaSecret

    async def _me(client: AsyncClient) -> bool:
        response = await client.get("/api/v1/users/me")
        assert response.status_code == 200, response.text
        return response.json()["mfa_enabled"]

    async with _client(
        db,
        ctx_tenant_id=tenant_ctx.tenant_id,
        ctx_user_id=tenant_ctx.user.id,
        perms={"settings:read"},
    ) as client:
        assert await _me(client) is False

        # started but never confirmed: the row exists and still challenges nobody
        db.add(
            UserMfaSecret(
                user_id=tenant_ctx.user.id,
                totp_secret_encrypted="not-a-real-secret",
                enabled_at=None,
                backup_codes_hashes=[],
            )
        )
        await db.flush()
        assert await _me(client) is False

        # confirmed — the only state that turns logins into a two-step challenge
        await db.execute(
            sa.update(UserMfaSecret)
            .where(UserMfaSecret.user_id == tenant_ctx.user.id)
            .values(enabled_at=sa.func.now())
        )
        assert await _me(client) is True

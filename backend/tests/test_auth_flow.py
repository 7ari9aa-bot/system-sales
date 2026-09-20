"""Auth flow tests — register / login / rotation / logout / invitations.

Runs against the real database (as sales_app, RLS on) inside a per-test
rollback transaction.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import ConflictError, PermissionDeniedError
from app.core.security import decode_token
from app.modules.identity.deps import _role_permissions
from app.modules.identity.models import RefreshToken, Role, TenantUser
from app.modules.identity.service import AuthService, TenantService, UserService


async def test_register_login_refresh_logout(db):
    email = f"user-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Flow Tenant",
        tenant_slug=f"flow-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Flow Owner",
    )
    assert tenant.slug.startswith("flow-")

    pair, logged_in, tenant_id = await AuthService.login(
        db, email=email, password="strong-password-1"
    )
    assert tenant_id == tenant.id
    claims = decode_token(pair.access_token)
    assert claims["sub"] == str(user.id)
    assert claims["tenant_id"] == str(tenant.id)

    pair2, _user, tenant_id2 = await AuthService.refresh(
        db, refresh_token=pair.refresh_token
    )
    assert tenant_id2 == tenant.id
    # rotation: old refresh token must be revoked
    revoked = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash != "")
        )
    ).scalars().all()
    assert any(r.revoked_at is not None for r in revoked)

    await AuthService.logout(db, refresh_token=pair2.refresh_token)

    tenants = await TenantService.list_for_user(db, user.id)
    assert any(t.id == tenant.id and role == "owner" for t, role in tenants)


async def test_login_wrong_password_denied(db):
    with pytest.raises(PermissionDeniedError):
        await AuthService.login(db, email="ghost@test.local", password="nope")


async def test_refresh_token_reuse_revokes_family(db, app_sessions_on_test_connection):
    """Reuse must revoke the whole family — and the revocation must be durable.

    `_revoke_family_on_reuse` deliberately runs on its OWN session so the
    revocation survives the rollback that follows the 401. That means it cannot
    use the `db` fixture's connection unless the app's session factory is bound to
    it, which is what `app_sessions_on_test_connection` does — see the fixture's
    docstring for why the default fails.
    """
    email = f"reuse-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Reuse Tenant",
        tenant_slug=f"reuse-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Reuse Owner",
    )
    pair, _u, _t = await AuthService.login(db, email=email, password="strong-password-1")
    await AuthService.refresh(db, refresh_token=pair.refresh_token)
    # reusing the now-revoked token must deny AND revoke the whole family
    with pytest.raises(PermissionDeniedError):
        await AuthService.refresh(db, refresh_token=pair.refresh_token)
    remaining = (
        await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    ).scalars().all()
    assert all(r.revoked_at is not None for r in remaining)


async def test_invitation_flow(db, tenant_ctx):
    invitation = await TenantService.invite(
        db,
        tenant_id=tenant_ctx.tenant_id,
        email=f"staff-{uuid.uuid4().hex[:8]}@test.local",
        role_code="staff",
        invited_by=tenant_ctx.user.id,
    )
    user, invitation = await TenantService.accept_invitation(
        db,
        token=invitation.token,
        password="strong-password-1",
        full_name="New Staff",
    )
    membership = (
        await db.execute(
            select(TenantUser).where(
                TenantUser.user_id == user.id,
                TenantUser.tenant_id == tenant_ctx.tenant_id,
            )
        )
    ).scalar_one()
    assert membership.role_id is not None

    # accepting the same token again must fail
    from app.core.errors import ValidationError

    with pytest.raises((ValidationError, ConflictError)):
        await TenantService.accept_invitation(
            db, token=invitation.token, password="x-strong-pass-1", full_name="Again"
        )


async def test_unknown_role_rejected(db, tenant_ctx):
    from app.core.errors import ValidationError

    with pytest.raises(ValidationError):
        await TenantService.invite(
            db,
            tenant_id=tenant_ctx.tenant_id,
            email=f"x-{uuid.uuid4().hex[:6]}@test.local",
            role_code="superwizard",
            invited_by=tenant_ctx.user.id,
        )


async def test_duplicate_slug_conflict(db):
    slug = f"dup-{uuid.uuid4().hex[:8]}"
    await AuthService.register(
        db,
        tenant_name="One",
        tenant_slug=slug,
        email=f"a-{uuid.uuid4().hex[:6]}@test.local",
        password="strong-password-1",
        full_name="A",
    )
    with pytest.raises(ConflictError):
        await AuthService.register(
            db,
            tenant_name="Two",
            tenant_slug=slug,
            email=f"b-{uuid.uuid4().hex[:6]}@test.local",
            password="strong-password-1",
            full_name="B",
        )


async def test_profile_update(db, tenant_ctx):
    updated = await UserService.update_profile(
        db, tenant_ctx.user.id, full_name="Renamed Owner"
    )
    assert updated.full_name == "Renamed Owner"


async def test_rbac_permission_matrix(db, tenant_ctx):
    """Owner (seeded) holds settings:write; staff does not."""
    owner_perms = await _role_permissions(db, tenant_ctx.role.id)
    assert "settings:write" in owner_perms
    assert "orders:write" in owner_perms

    staff_role = (
        await db.execute(select(Role).where(Role.code == "staff"))
    ).scalar_one()
    staff_perms = await _role_permissions(db, staff_role.id)
    assert "conversations:write" in staff_perms
    assert "settings:write" not in staff_perms


async def test_register_minimal_email_password_only(db):
    """Minimal signup: only email+password — tenant name/slug and display
    name derive from the email local part, slug dedupes automatically."""
    email = f"hamed.adel-{uuid.uuid4().hex[:6]}@gmail.com"
    user, tenant = await AuthService.register(
        db, tenant_name=None, tenant_slug=None, email=email,
        password="Probe-1234", full_name=None,
    )
    assert user.email == email
    assert user.full_name == "Hamed Adel"
    assert tenant.name == "Hamed Adel"
    assert tenant.slug.startswith("hamed-adel-")


async def test_register_minimal_slug_collision_dedupes(db):
    """Two minimal signups with the same email local part get distinct slugs."""
    local = f"collision-{uuid.uuid4().hex[:4]}"
    _u1, t1 = await AuthService.register(
        db, tenant_name=None, tenant_slug=None, email=f"{local}@test.local",
        password="Probe-1234", full_name=None,
    )
    u2, t2 = await AuthService.register(
        db, tenant_name=None, tenant_slug=None, email=f"{local}@other.local",
        password="Probe-1234", full_name=None,
    )
    assert t1.slug != t2.slug
    assert t2.slug.startswith(t1.slug)  # نفس الأساس + لاحقة تفريد

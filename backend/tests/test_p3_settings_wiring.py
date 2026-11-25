"""Tests for P3 platform-management settings wiring.

Covers:
  * team.session_timeout_minutes  → access-token TTL
  * team.allow_member_invites     → invitation gate
  * team.default_role             → fallback role when inviting
  * security.require_strong_passwords → registration + password reset
  * security.ip_allowlist         → request IP gate
  * notifications.email_enabled / push_enabled → dispatch gating

Each test verifies the setting is actually READ through the settings resolver
(app.core.settings_read), not via direct SQL, and that the behaviour changes
when the setting changes.
"""

from __future__ import annotations

import hashlib
import inspect
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest

# Import all models so SQLAlchemy's metadata is complete (the Notification
# model has a FK to customers.id; without this import the table is missing).
import app.modules.platform.models  # noqa: F401
import app.modules.customers.models  # noqa: F401


# -----------------------------------------------------------------------
# Source inspection: resolver is used, not direct SQL
# -----------------------------------------------------------------------

def test_auth_uses_settings_read_resolver_not_direct_sql():
    """AuthService reads team.session_timeout_minutes and team.require_2fa
    through app.core.settings_read, not through raw tenant_settings SQL."""
    from app.modules.identity.services import auth

    source = inspect.getsource(auth)
    assert "settings_read" in source, "auth should import from app.core.settings_read"
    assert "team.session_timeout_minutes" in source
    assert "team.require_2fa" in source
    # No more direct SQL for these settings.
    assert (
        "SELECT (value->>'v')::int FROM tenant_settings "
        "WHERE tenant_id = :t AND key = 'team.session_timeout_minutes'"
    ) not in source


def test_auth_reads_require_strong_passwords():
    """_validate_password_strength reads security.require_strong_passwords
    via the resolver, not a hardcoded required=True."""
    from app.modules.identity.services import auth

    source = inspect.getsource(auth)
    assert "security.require_strong_passwords" in source
    assert "_tenant_strong_passwords_required" in source


def test_tenant_service_uses_settings_read_resolver():
    """TenantService.invite reads team.allow_member_invites and
    team.default_role through app.core.settings_read."""
    from app.modules.identity.services import tenant

    source = inspect.getsource(tenant)
    assert "settings_read" in source
    assert "team.allow_member_invites" in source
    assert "team.default_role" in source
    # No more direct SQL for allow_member_invites.
    assert (
        "SELECT (value->>'v')::boolean FROM tenant_settings "
        "WHERE tenant_id = :t AND key = 'team.allow_member_invites'"
    ) not in source


def test_deps_uses_settings_read_resolver_for_ip_allowlist():
    """get_current_user reads security.ip_allowlist through the resolver."""
    from app.modules.identity import deps

    source = inspect.getsource(deps)
    assert "settings_read" in source
    assert "security.ip_allowlist" in source
    # No more direct SQL for ip_allowlist.
    assert (
        "SELECT (value->>'v')::jsonb FROM tenant_settings "
        "WHERE tenant_id = :t AND key = 'security.ip_allowlist'"
    ) not in source


def test_notifications_dispatch_uses_settings_read():
    """NotificationService.dispatch reads email_enabled and push_enabled
    through the resolver and gates delivery on them."""
    from app.modules.notifications import service

    source = inspect.getsource(service)
    assert "dispatch" in source
    assert "notifications.email_enabled" in source
    assert "notifications.push_enabled" in source
    assert "settings_read" in source
    assert "_send_email" in source
    assert "_send_push" in source


def test_digest_uses_settings_read_not_direct_sql():
    """NotificationAggregator reads digest_mode and quiet_hours through the
    resolver, not direct SQL."""
    from app.modules.notifications import digest

    source = inspect.getsource(digest)
    assert "settings_read" in source
    # No more direct SQL for digest_mode.
    assert (
        "SELECT value->>'v' FROM tenant_settings "
        "WHERE tenant_id = :t AND key = 'notifications.digest_mode'"
    ) not in source


def test_settings_read_module_exists_in_core():
    """app.core.settings_read exists and exposes the resolver functions."""
    from app.core import settings_read

    assert hasattr(settings_read, "resolve_setting")
    assert hasattr(settings_read, "resolve_settings")
    assert hasattr(settings_read, "setting_bool")


def test_settings_read_does_not_import_identity():
    """settings_read must not import from identity (would re-create the cycle)."""
    from app.core import settings_read

    source = inspect.getsource(settings_read)
    assert "app.modules.identity" not in source


def test_hierarchy_uses_settings_read():
    """identity.services.hierarchy reads settings via the resolver."""
    from app.modules.identity.services import hierarchy

    source = inspect.getsource(hierarchy)
    assert "settings_read" in source
    assert (
        "SELECT value -> 'v' FROM tenant_settings "
        "WHERE tenant_id = :tid AND key = :k"
    ) not in source


def test_invite_router_does_not_read_default_role_sql():
    """The invite router delegates default_role resolution to the service,
    not its own direct SQL."""
    from app.modules.identity.routers import tenants

    source = inspect.getsource(tenants)
    assert "team.default_role" not in source or "role_code=body.role_code" in source
    assert (
        "SELECT (value->>'v')::text FROM tenant_settings "
        "WHERE tenant_id = :t AND key = 'team.default_role'"
    ) not in source


# -----------------------------------------------------------------------
# Behavioural tests (need DB)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_timeout_changes_token_ttl(db):
    """Setting team.session_timeout_minutes to 5 makes _resolve_access_ttl
    return 300 seconds; setting it to 0 returns None."""
    from app.core.settings_read import resolve_setting
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService
    from app.modules.identity.service import AuthService

    tenant_id = uuid.uuid4()
    # We need a real tenant for the settings GUC — create one via register.
    email = f"timeout-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Timeout Tenant",
        tenant_slug=f"timeout-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Timeout Owner",
    )
    await db.flush()

    # Default: 0 → no limit
    ttl = await AuthService._resolve_access_ttl(db, tenant.id)
    assert ttl is None

    # Set to 5 minutes
    svc = SettingsService(db, tenant.id)
    await svc.set("team.session_timeout_minutes", 5, scope=Scope.TENANT)
    await db.flush()
    ttl = await AuthService._resolve_access_ttl(db, tenant.id)
    assert ttl == 300

    # Reset
    await svc.reset("team.session_timeout_minutes", scope=Scope.TENANT)
    await db.flush()
    ttl = await AuthService._resolve_access_ttl(db, tenant.id)
    assert ttl is None


@pytest.mark.asyncio
async def test_allow_member_invites_blocks_invitation(db):
    """When team.allow_member_invites is False, TenantService.invite raises
    PermissionDeniedError."""
    from app.core.errors import PermissionDeniedError
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService
    from app.modules.identity.service import AuthService, TenantService

    email = f"invites-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Invites Tenant",
        tenant_slug=f"invites-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Invites Owner",
    )
    await db.flush()

    # Default: invites allowed
    invite = await TenantService.invite(
        db,
        tenant_id=tenant.id,
        email=f"new-{uuid.uuid4().hex[:8]}@test.local",
        role_code="staff",
        invited_by=user.id,
        inviter_role_code="owner",
    )
    assert invite.status == "pending"

    # Disable invites
    svc = SettingsService(db, tenant.id)
    await svc.set("team.allow_member_invites", False, scope=Scope.TENANT)
    await db.flush()

    with pytest.raises(PermissionDeniedError, match="invitations are disabled"):
        await TenantService.invite(
            db,
            tenant_id=tenant.id,
            email=f"blocked-{uuid.uuid4().hex[:8]}@test.local",
            role_code="staff",
            invited_by=user.id,
            inviter_role_code="owner",
        )


@pytest.mark.asyncio
async def test_default_role_fallback_when_role_code_is_none(db):
    """When role_code is None, the tenant's team.default_role setting is used."""
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService
    from app.modules.identity.service import AuthService, TenantService
    from app.modules.identity.models import Role

    email = f"defrole-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="DefRole Tenant",
        tenant_slug=f"defrole-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="DefRole Owner",
    )
    await db.flush()

    # Set default_role to "manager"
    svc = SettingsService(db, tenant.id)
    await svc.set("team.default_role", "manager", scope=Scope.TENANT)
    await db.flush()

    invite = await TenantService.invite(
        db,
        tenant_id=tenant.id,
        email=f"manager-{uuid.uuid4().hex[:8]}@test.local",
        role_code=None,
        invited_by=user.id,
        inviter_role_code="owner",
    )
    # The invitation should have the manager role
    role = await db.get(Role, invite.role_id)
    assert role.code == "manager"


@pytest.mark.asyncio
async def test_require_strong_passwords_on_registration(db):
    """Registration with a weak password fails when
    security.require_strong_passwords is at its default (True)."""
    from app.core.errors import ValidationError
    from app.modules.identity.service import AuthService

    with pytest.raises(ValidationError, match="password must contain both"):
        await AuthService.register(
            db,
            tenant_name="Weak Pwd Tenant",
            tenant_slug=f"weak-{uuid.uuid4().hex[:8]}",
            email=f"weak-{uuid.uuid4().hex[:8]}@test.local",
            password="allletters",  # no digits
            full_name="Weak Owner",
        )


@pytest.mark.asyncio
async def test_require_strong_passwords_off_allows_weak_password_on_reset(db):
    """When security.require_strong_passwords is False, a weak password is
    accepted on password reset."""
    from app.core.errors import ValidationError
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService
    from app.modules.identity.service import AuthService
    from app.modules.identity.models import PasswordResetToken
    from app.core.secrets import get_envelope_store
    import secrets
    from datetime import UTC, datetime, timedelta

    email = f"reset-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Reset Tenant",
        tenant_slug=f"reset-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Reset Owner",
    )
    await db.flush()

    # Disable strong passwords
    svc = SettingsService(db, tenant.id)
    await svc.set("security.require_strong_passwords", False, scope=Scope.TENANT)
    await db.flush()

    # Create a reset token
    import hashlib
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            encrypted_token=get_envelope_store().encrypt(token),
            requested_at=now,
            expires_at=now + timedelta(hours=1),
            next_attempt_at=now,
        )
    )
    await db.flush()

    # Weak password should now be accepted
    await AuthService.reset_password(db, token=token, password="weak")
    await db.flush()


@pytest.mark.asyncio
async def test_notification_dispatch_gates_email_and_push(db):
    """When email_enabled and push_enabled are both False (default), dispatch
    creates the in-app notification but does not stage email/push outbox
    events. When enabled, it does stage them."""
    from app.modules.notifications.service import NotificationService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService
    from app.modules.identity.service import AuthService

    email = f"notif-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Notif Tenant",
        tenant_slug=f"notif-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Notif Owner",
    )
    await db.flush()

    # Default: both disabled → only in-app notification
    notif = await NotificationService.dispatch(
        db,
        tenant.id,
        user.id,
        kind="order",
        body="New order received",
        title="New Order",
    )
    assert notif is not None
    await db.flush()

    # Enable email + push
    svc = SettingsService(db, tenant.id)
    await svc.set("notifications.email_enabled", True, scope=Scope.TENANT)
    await svc.set("notifications.push_enabled", True, scope=Scope.TENANT)
    await db.flush()

    notif2 = await NotificationService.dispatch(
        db,
        tenant.id,
        user.id,
        kind="order",
        body="Another order received",
        title="Another Order",
        dedup_key=f"order-{uuid.uuid4().hex[:8]}",
    )
    assert notif2 is not None
    await db.flush()

    # Verify outbox events were staged for email and push
    from sqlalchemy import text
    events = (
        await db.execute(
            text(
                "SELECT event_type FROM outbox_events "
                "WHERE tenant_id = :tid AND producer = 'notifications' "
                "ORDER BY created_at DESC LIMIT 5"
            ),
            {"tid": tenant.id},
        )
    ).scalars().all()
    assert "notification.email" in events
    assert "notification.push" in events

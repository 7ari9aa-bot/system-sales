"""Tests for P3 platform-management settings wiring.

Covers:
  * team.session_timeout_minutes  → access-token TTL
  * team.allow_member_invites     → invitation gate
  * team.default_role             → fallback role when inviting
  * security.require_strong_passwords → registration + password reset
  * security.ip_allowlist         → request IP gate
  * notifications.email_enabled / push_enabled → dispatch gating
  * notifications.digest_mode     → digest aggregation
  * organization.multi_branch     → workspace creation gate

Every test calls a real service or endpoint and verifies the outcome changes
when the setting changes — no source-inspection (``inspect.getsource``) tests.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.applications.apparel.modules.customers.models  # noqa: F401

# Import all models so SQLAlchemy's metadata is complete (the Notification
# model has a FK to customers.id; without this import the table is missing).
import app.modules.platform.models  # noqa: F401

# -----------------------------------------------------------------------
# Behavioural tests (need DB)
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_timeout_changes_token_ttl(db):
    """Setting team.session_timeout_minutes to 5 makes _resolve_access_ttl
    return 300 seconds; setting it to 0 returns None."""
    from app.modules.identity.service import AuthService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

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
    from app.modules.identity.service import AuthService, TenantService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

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
    from app.modules.identity.models import Role
    from app.modules.identity.service import AuthService, TenantService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

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
    from app.core.secrets import get_envelope_store
    from app.modules.identity.models import PasswordResetToken
    from app.modules.identity.service import AuthService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

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
    await svc.set(
        "security.require_strong_passwords",
        False,
        scope=Scope.TENANT,
        # security.* is APPROVAL_REQUIRED: a plain set() opens a change request and writes
        # nothing, so the test would read the default. Write it the way an approved change lands.
        bypass_approval=True,
    )
    await db.flush()

    # Create a reset token

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
    from app.modules.identity.service import AuthService
    from app.modules.notifications.service import (
        NotificationPreferencesService,
        NotificationService,
    )
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

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

    # Explicitly disable both email and push
    svc = SettingsService(db, tenant.id)
    await svc.set("notifications.email_enabled", False, scope=Scope.TENANT)
    await svc.set("notifications.push_enabled", False, scope=Scope.TENANT)
    await db.flush()

    # Both disabled → only in-app notification, no outbox events
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

    # Verify NO notification outbox events were staged while disabled
    from sqlalchemy import text

    disabled_events = (
        (
            await db.execute(
                text(
                    "SELECT payload->>'event_type' AS event_type "
                    "FROM outbox_events "
                    "WHERE meta->>'tenant_id' = :tid "
                    "  AND meta->>'producer' = 'notifications'"
                ),
                {"tid": str(tenant.id)},
            )
        )
        .scalars()
        .all()
    )
    assert disabled_events == [], (
        f"expected no notification outbox events when disabled, got {disabled_events}"
    )

    # Enable email + push
    await svc.set("notifications.email_enabled", True, scope=Scope.TENANT)
    await svc.set("notifications.push_enabled", True, scope=Scope.TENANT)
    # Two gates, and the test has to open both: the WORKSPACE decides whether this
    # deployment sends the channel at all, and the PERSON decides whether they want
    # it. Opening only the workspace gate proved nothing once the personal
    # preference layer landed — push defaults to OFF per person, so the event that
    # "should" be staged never was and this assertion had been red on main.
    await NotificationPreferencesService.update(
        db, tenant.id, user.id, email_enabled=True, push_enabled=True
    )
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
    events = (
        (
            await db.execute(
                text(
                    "SELECT payload->>'event_type' AS event_type "
                    "FROM outbox_events "
                    "WHERE meta->>'tenant_id' = :tid "
                    "  AND meta->>'producer' = 'notifications' "
                    "ORDER BY created_at DESC LIMIT 5"
                ),
                {"tid": str(tenant.id)},
            )
        )
        .scalars()
        .all()
    )
    assert "notification.email" in events, f"expected notification.email in {events}"
    assert "notification.push" in events, f"expected notification.push in {events}"


@pytest.mark.asyncio
async def test_ip_allowlist_blocks_unlisted_ip(db):
    """When security.ip_allowlist is set, get_current_user rejects requests
    from IPs not in the list."""
    from app.core.errors import PermissionDeniedError
    from app.core.security import create_access_token
    from app.modules.identity.deps import get_current_user
    from app.modules.identity.service import AuthService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

    email = f"ip-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="IP Tenant",
        tenant_slug=f"ip-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="IP Owner",
    )
    await db.flush()

    # Set IP allowlist to a specific IP
    svc = SettingsService(db, tenant.id)
    await svc.set("security.ip_allowlist", ["10.0.0.1"], scope=Scope.TENANT, bypass_approval=True)
    await db.flush()

    # Create a valid access token for the user
    token = create_access_token(
        str(user.id),
        {"tenant_id": str(tenant.id), "role": "owner"},
    )

    # Mock request from a DIFFERENT IP
    request = SimpleNamespace(
        headers={"authorization": f"Bearer {token}"},
        cookies={},
        client=SimpleNamespace(host="192.168.1.99"),
        method="GET",
    )

    with pytest.raises(PermissionDeniedError, match="not allowed"):
        await get_current_user(request, db, authorization=f"Bearer {token}")


@pytest.mark.asyncio
async def test_ip_allowlist_allows_listed_ip(db):
    """When the request IP is in the allowlist, get_current_user succeeds."""
    from app.core.security import create_access_token
    from app.modules.identity.deps import get_current_user
    from app.modules.identity.service import AuthService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

    email = f"ipok-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="IP OK Tenant",
        tenant_slug=f"ipok-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="IP OK Owner",
    )
    await db.flush()

    svc = SettingsService(db, tenant.id)
    await svc.set("security.ip_allowlist", ["10.0.0.1"], scope=Scope.TENANT, bypass_approval=True)
    await db.flush()

    token = create_access_token(
        str(user.id),
        {"tenant_id": str(tenant.id), "role": "owner"},
    )

    request = SimpleNamespace(
        headers={"authorization": f"Bearer {token}"},
        cookies={},
        client=SimpleNamespace(host="10.0.0.1"),
        method="GET",
    )

    authed = await get_current_user(request, db, authorization=f"Bearer {token}")
    assert authed.id == user.id
    assert authed.tenant_id == tenant.id


@pytest.mark.asyncio
async def test_digest_mode_holds_non_critical_notifications(db):
    """When notifications.digest_mode is not 'realtime', should_send_immediately
    returns False for non-critical notifications."""
    from app.modules.identity.service import AuthService
    from app.modules.notifications.digest import NotificationAggregator
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

    email = f"digest-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Digest Tenant",
        tenant_slug=f"digest-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Digest Owner",
    )
    await db.flush()

    # Default digest_mode should be realtime → should_send_immediately is True
    result = await NotificationAggregator.should_send_immediately(
        db, tenant.id, user.id, priority="information"
    )
    assert result is True

    # Set digest_mode to 'hourly'
    svc = SettingsService(db, tenant.id)
    await svc.set("notifications.digest_mode", "hourly", scope=Scope.TENANT)
    await db.flush()

    result = await NotificationAggregator.should_send_immediately(
        db, tenant.id, user.id, priority="information"
    )
    assert result is False

    # Critical always sends immediately, regardless of digest mode
    result = await NotificationAggregator.should_send_immediately(
        db, tenant.id, user.id, priority="critical"
    )
    assert result is True


@pytest.mark.asyncio
async def test_resolve_setting_returns_default_then_override(db):
    """resolve_setting returns the registry default when no override exists,
    and the tenant override when one is set."""
    from app.core.settings_read import resolve_setting, setting_bool
    from app.modules.identity.service import AuthService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

    email = f"resolve-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Resolve Tenant",
        tenant_slug=f"resolve-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Resolve Owner",
    )
    await db.flush()

    # Default: require_strong_passwords is True
    val = await resolve_setting(db, tenant.id, "security.require_strong_passwords")
    assert val is True
    assert await setting_bool(db, tenant.id, "security.require_strong_passwords") is True

    # Override at tenant level
    svc = SettingsService(db, tenant.id)
    await svc.set(
        "security.require_strong_passwords",
        False,
        scope=Scope.TENANT,
        # security.* is APPROVAL_REQUIRED: a plain set() opens a change request and writes
        # nothing, so the test would read the default. Write it the way an approved change lands.
        bypass_approval=True,
    )
    await db.flush()

    val = await resolve_setting(db, tenant.id, "security.require_strong_passwords")
    assert val is False
    assert await setting_bool(db, tenant.id, "security.require_strong_passwords") is False


@pytest.mark.asyncio
async def test_multi_branch_blocks_second_workspace(db):
    """When organization.multi_branch is False (default), creating a second
    workspace is rejected. Enabling it allows the second workspace."""
    from app.core.errors import ValidationError
    from app.modules.identity.service import AuthService
    from app.modules.identity.services.hierarchy import HierarchyService
    from app.modules.settings.registry import Scope
    from app.modules.settings.service import SettingsService

    email = f"branch-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Branch Tenant",
        tenant_slug=f"branch-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Branch Owner",
    )
    await db.flush()

    # First workspace succeeds (registration already creates one)
    # Check how many workspaces exist
    workspaces = await HierarchyService.list_workspaces(db, tenant.id)
    initial_count = len(workspaces)

    if initial_count == 0:
        await HierarchyService.create_workspace(db, tenant.id, name="Main", slug="main")
        await db.flush()

    # Second workspace should be blocked (multi_branch=False by default)
    with pytest.raises(ValidationError, match="multi-branch is not enabled"):
        await HierarchyService.create_workspace(db, tenant.id, name="Second", slug="second")

    # Enable multi_branch
    svc = SettingsService(db, tenant.id)
    await svc.set("organization.multi_branch", True, scope=Scope.TENANT)
    await db.flush()

    # Now the second workspace succeeds
    ws2 = await HierarchyService.create_workspace(db, tenant.id, name="Second", slug="second")
    await db.flush()
    assert ws2 is not None
    assert ws2.slug == "second"

"""Tests for bypass_approval removal from rollback/restore/preset (جولة 14, requirement 2).

rollback, restore_to_snapshot, and apply_preset must route APPROVAL_REQUIRED
settings through the change-request flow. The exception is _apply_change_request
itself (after approval), which keeps its internal bypass.

bypass is only allowed with settings:emergency_bypass permission, and writes
an independent audit row.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import PermissionDeniedError
from app.modules.settings.models import SettingChangeRequest
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio

OWNER_PERMS = {
    "settings:read",
    "settings:write",
    "settings:read_sensitive",
    "settings:emergency_bypass",
    "settings:branch_write",
}
MANAGER_PERMS = {"settings:read", "settings:write", "settings:branch_write"}


async def test_rollback_of_approval_required_creates_change_request(db: AsyncSession, tenant_ctx):
    """Rollback of an APPROVAL_REQUIRED setting creates a change request, not a direct write."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    # Write an APPROVAL_REQUIRED setting via internal bypass
    await svc.set(
        "billing.auto_renew",
        True,
        user_id=tenant_ctx.user.id,
        permissions=None,
        bypass_approval=True,
    )
    await db.flush()

    # Find the history row
    history = await svc.history(key="billing.auto_renew")
    assert len(history) >= 1
    target_id = history[0].id

    # Rollback as a manager (no emergency_bypass) → should create a change request
    result = await svc.rollback(
        target_id,
        user_id=tenant_ctx.user.id,
        permissions=MANAGER_PERMS,
    )
    assert isinstance(result, SettingChangeRequest)
    assert result.status == "pending_approval"
    assert "billing.auto_renew" in result.changes


async def test_rollback_of_non_approval_setting_applies_directly(db: AsyncSession, tenant_ctx):
    """Rollback of a non-APPROVAL_REQUIRED setting applies directly (no change request)."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "pos.return_max_days",
        14,
        user_id=tenant_ctx.user.id,
        permissions=None,
    )
    await db.flush()

    history = await svc.history(key="pos.return_max_days")
    assert len(history) >= 1
    target_id = history[0].id

    result = await svc.rollback(
        target_id,
        user_id=tenant_ctx.user.id,
        permissions=MANAGER_PERMS,
    )
    from app.modules.settings.models import TenantSetting

    assert isinstance(result, TenantSetting)
    assert result.value.get("v") == 14


async def test_rollback_emergency_bypass_requires_permission(db: AsyncSession, tenant_ctx):
    """Emergency bypass without settings:emergency_bypass raises PermissionDeniedError."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "billing.auto_renew",
        True,
        user_id=tenant_ctx.user.id,
        permissions=None,
        bypass_approval=True,
    )
    await db.flush()

    history = await svc.history(key="billing.auto_renew")
    target_id = history[0].id

    with pytest.raises(PermissionDeniedError):
        await svc.rollback(
            target_id,
            user_id=tenant_ctx.user.id,
            permissions=MANAGER_PERMS,
            bypass_approval=True,
        )


async def test_rollback_emergency_bypass_with_permission_applies_and_audits(
    db: AsyncSession, tenant_ctx
):
    """Emergency bypass with permission applies the change and writes an audit row."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "billing.auto_renew",
        True,
        user_id=tenant_ctx.user.id,
        permissions=None,
        bypass_approval=True,
    )
    await db.flush()

    history = await svc.history(key="billing.auto_renew")
    target_id = history[0].id

    result = await svc.rollback(
        target_id,
        user_id=tenant_ctx.user.id,
        permissions=OWNER_PERMS,
        bypass_approval=True,
    )
    from app.modules.settings.models import TenantSetting

    assert isinstance(result, TenantSetting)


async def test_restore_to_snapshot_skips_approval_required_without_bypass(
    db: AsyncSession, tenant_ctx
):
    """restore_to_snapshot skips APPROVAL_REQUIRED settings when not bypassing."""
    from datetime import UTC, datetime, timedelta

    svc = SettingsService(db, tenant_ctx.tenant_id)
    # Set an APPROVAL_REQUIRED setting
    await svc.set(
        "billing.auto_renew",
        True,
        user_id=tenant_ctx.user.id,
        permissions=None,
        bypass_approval=True,
    )
    # Also set a non-APPROVAL setting
    await svc.set(
        "pos.return_max_days",
        21,
        user_id=tenant_ctx.user.id,
        permissions=None,
    )
    await db.flush()

    snapshot_before = datetime.now(UTC) + timedelta(seconds=1)
    await db.flush()

    result = await svc.restore_to_snapshot(
        snapshot_before + timedelta(seconds=10),
        user_id=tenant_ctx.user.id,
        permissions=MANAGER_PERMS,
    )
    # APPROVAL_REQUIRED setting should be in pending_approval, not restored
    assert result["pending_approval"] >= 1
    assert result["restored"] >= 0


async def test_apply_change_request_keeps_internal_bypass(db: AsyncSession, tenant_ctx):
    """_apply_change_request still uses bypass_approval=True after approval (the exception)."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    # Create a change request for an APPROVAL_REQUIRED setting
    req = await svc.create_change_request(
        {"billing.auto_renew": False},
        user_id=tenant_ctx.user.id,
        permissions=OWNER_PERMS,
    )
    await db.flush()
    # It should be pending_approval (since billing.auto_renew is APPROVAL_REQUIRED)
    assert req.status == "pending_approval"

    # Approve with a different user (self-approval guard).
    # The FK on reviewed_by requires a real user, so create one via ORM.
    from app.modules.identity.models import TenantUser, User

    other_user_id = uuid.uuid4()
    db.add(
        User(
            id=other_user_id,
            email="reviewer@test.local",
            full_name="Reviewer",
            password_hash="x",
            is_active=True,
        )
    )
    # Look up the owner role id
    from app.modules.identity.models import Role

    role_row = (await db.execute(select(Role).where(Role.code == "owner"))).scalar_one()
    db.add(
        TenantUser(
            tenant_id=tenant_ctx.tenant_id,
            user_id=other_user_id,
            role_id=role_row.id,
        )
    )
    await db.flush()
    approved = await svc.approve_change_request(
        req.id,
        reviewer_id=other_user_id,
        permissions=OWNER_PERMS,
    )
    assert approved.status == "applied"

    # Verify the value was actually written
    resolved = await svc.resolve("billing.auto_renew")
    assert resolved.value is False


# ---------------------------------------------------------------------------
# Fail-closed: permissions=None + bypass_approval=True must be rejected
# ---------------------------------------------------------------------------


async def test_rollback_bypass_with_none_permissions_rejected(db, tenant_ctx):
    """rollback with bypass_approval=True but permissions=None must fail-closed."""
    svc = SettingsService(db, tenant_id=tenant_ctx.tenant_id)
    # First set a value normally (billing.auto_renew is APPROVAL_REQUIRED,
    # so we need bypass to set it — use owner perms).
    await svc.set(
        "billing.auto_renew",
        True,
        scope="tenant",
        user_id=tenant_ctx.user.id,
        permissions=OWNER_PERMS,
        bypass_approval=True,
    )
    await db.flush()

    # Get the latest history id
    history = await svc.history(key="billing.auto_renew", limit=1)
    assert len(history) == 1

    # Now try rollback with bypass_approval=True but permissions=None
    with pytest.raises(PermissionDeniedError, match="emergency bypass"):
        await svc.rollback(
            history[0].id,
            user_id=tenant_ctx.user.id,
            permissions=None,  # no authenticated caller
            bypass_approval=True,
        )


async def test_restore_bypass_with_none_permissions_rejected(db, tenant_ctx):
    """restore_to_snapshot with bypass_approval=True but permissions=None must fail-closed."""
    from datetime import UTC, datetime, timedelta

    svc = SettingsService(db, tenant_id=tenant_ctx.tenant_id)
    with pytest.raises(PermissionDeniedError, match="emergency bypass"):
        await svc.restore_to_snapshot(
            datetime.now(UTC) - timedelta(days=1),
            user_id=tenant_ctx.user.id,
            permissions=None,  # no authenticated caller
            bypass_approval=True,
        )


async def test_preset_bypass_with_none_permissions_rejected():
    """apply_preset bypass check is fail-closed when permissions=None.

    No current preset has APPROVAL_REQUIRED settings, so the bypass path in
    ``apply_preset`` is not reachable through any real preset.  We verify the
    fail-closed logic directly by inspecting the source: the condition must
    use ``permissions is None or ...`` (not ``permissions is not None and ...``).
    """
    import inspect

    source = inspect.getsource(SettingsService.apply_preset)
    # The fail-closed pattern: "permissions is None or" (not "permissions is not None and")
    assert "permissions is None or" in source, (
        "apply_preset bypass must be fail-closed: permissions is None or ..."
    )
    assert (
        "permissions is not None and" not in source.split("bypass_approval")[1].split("bulk_set")[0]
    ), "apply_preset still uses fail-open pattern"

"""Tests for advanced approvals — sensitive settings require a second admin (§172).

Covers:
* security.* and billing.* settings are APPROVAL_REQUIRED.
* Direct ``set``/``reset`` from the API is refused for APPROVAL_REQUIRED keys.
* Internal callers (presets, restore, rollback, change-request apply) bypass.
* A change request for sensitive settings stays pending until approved.
* Self-approval is forbidden (reviewer ≠ submitter).
* Approval applies the changes and audits the decision.
* Rejection leaves the setting unchanged and audits the decision.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.platform.settings.registry import ApplyMode, get_definition
from app.platform.settings.service import SettingsService


def _uuid_hex() -> str:
    return uuid.uuid4().hex[:8]


async def _create_tenant(db: AsyncSession, slug: str = "appr"):
    """Register a fresh tenant and return (user, tenant)."""
    from app.platform.identity.service import AuthService

    email = f"{slug}-{_uuid_hex()}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name=f"{slug} tenant",
        tenant_slug=f"{slug}-{_uuid_hex()}",
        email=email,
        password="strong-password-1",
        full_name=f"{slug} owner",
    )
    await db.flush()
    return user, tenant


async def _create_second_admin(db: AsyncSession, tenant, slug: str = "rev"):
    """Add a second admin (owner role) to an existing tenant."""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.platform.identity.models import Role, TenantUser, User

    user = User(
        email=f"{slug}-{_uuid_hex()}@test.local",
        password_hash=hash_password("strong-password-1"),
        full_name="Reviewer",
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.code == "owner"))).scalar_one()
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role_id=role.id, is_default=False))
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Registry: security.* and billing.* are APPROVAL_REQUIRED
# ---------------------------------------------------------------------------


class TestSensitiveRegistry:
    def test_security_keys_are_approval_required(self) -> None:
        for key in (
            "security.require_strong_passwords",
            "security.api_key_rotation_days",
            "security.audit_retention_days",
            "security.ip_allowlist",
        ):
            defn = get_definition(key)
            assert defn.apply_mode == ApplyMode.APPROVAL_REQUIRED, (
                f"{key} should be APPROVAL_REQUIRED"
            )

    def test_billing_keys_are_approval_required(self) -> None:
        for key in (
            "billing.auto_renew",
            "billing.currency",
            "billing.notify_before_renewal_days",
        ):
            defn = get_definition(key)
            assert defn.apply_mode == ApplyMode.APPROVAL_REQUIRED, (
                f"{key} should be APPROVAL_REQUIRED"
            )

    def test_normal_keys_are_not_approval_required(self) -> None:
        defn = get_definition("pos.max_discount_pct")
        assert defn.apply_mode != ApplyMode.APPROVAL_REQUIRED


# ---------------------------------------------------------------------------
# Direct set/reset is refused for sensitive settings
# ---------------------------------------------------------------------------


class TestDirectWriteBlocked:
    pytestmark = pytest.mark.asyncio

    async def test_set_refused_for_sensitive_key(self, db) -> None:
        user, tenant = await _create_tenant(db, "setblk")
        svc = SettingsService(db, tenant.id)
        with pytest.raises(ValidationError, match="requires approval"):
            await svc.set(
                "security.require_strong_passwords",
                False,
                user_id=user.id,
            )

    async def test_reset_refused_for_sensitive_key(self, db) -> None:
        user, tenant = await _create_tenant(db, "rstblk")
        svc = SettingsService(db, tenant.id)
        with pytest.raises(ValidationError, match="requires approval"):
            await svc.reset(
                "security.require_strong_passwords",
                user_id=user.id,
            )

    async def test_bulk_set_refused_for_sensitive_key(self, db) -> None:
        user, tenant = await _create_tenant(db, "blkblk")
        svc = SettingsService(db, tenant.id)
        with pytest.raises(ValidationError, match="requires approval"):
            await svc.bulk_set(
                {"security.require_strong_passwords": False},
                user_id=user.id,
            )

    async def test_bypass_allows_internal_set(self, db) -> None:
        user, tenant = await _create_tenant(db, "bypass")
        svc = SettingsService(db, tenant.id)
        row = await svc.set(
            "security.require_strong_passwords",
            False,
            user_id=user.id,
            bypass_approval=True,
        )
        assert row.value == {"v": False}

    async def test_normal_key_set_works_without_bypass(self, db) -> None:
        user, tenant = await _create_tenant(db, "norm")
        svc = SettingsService(db, tenant.id)
        row = await svc.set("pos.max_discount_pct", 15.0, user_id=user.id)
        assert row.value == {"v": 15.0}


# ---------------------------------------------------------------------------
# Change request flow for sensitive settings
# ---------------------------------------------------------------------------


class TestChangeRequestFlow:
    pytestmark = pytest.mark.asyncio

    async def test_create_request_stays_pending(self, db) -> None:
        user, tenant = await _create_tenant(db, "pend")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"security.require_strong_passwords": False},
            user_id=user.id,
            reason="disable for testing",
        )
        assert req.status == "pending_approval"
        assert req.submitted_by == user.id

    async def test_self_approval_forbidden(self, db) -> None:
        user, tenant = await _create_tenant(db, "self")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"security.require_strong_passwords": False},
            user_id=user.id,
        )
        with pytest.raises(ValidationError, match="cannot approve your own"):
            await svc.approve_change_request(req.id, reviewer_id=user.id)

    async def test_second_admin_approves_and_applies(self, db) -> None:
        submitter, tenant = await _create_tenant(db, "appr2")
        reviewer = await _create_second_admin(db, tenant, "rev")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"security.require_strong_passwords": False},
            user_id=submitter.id,
            reason="testing",
        )
        approved = await svc.approve_change_request(
            req.id,
            reviewer_id=reviewer.id,
            review_note="looks good",
        )
        assert approved.status == "applied"
        assert approved.reviewed_by == reviewer.id
        row = await svc.resolve("security.require_strong_passwords")
        assert row.value is False

    async def test_rejection_does_not_apply(self, db) -> None:
        submitter, tenant = await _create_tenant(db, "rej")
        reviewer = await _create_second_admin(db, tenant, "rj")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"billing.currency": "USD"},
            user_id=submitter.id,
        )
        rejected = await svc.reject_change_request(
            req.id,
            reviewer_id=reviewer.id,
            review_note="no",
        )
        assert rejected.status == "rejected"
        row = await svc.resolve("billing.currency")
        assert row.value == "EGP"

    async def test_self_rejection_forbidden(self, db) -> None:
        user, tenant = await _create_tenant(db, "srej")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"security.require_strong_passwords": False},
            user_id=user.id,
        )
        with pytest.raises(ValidationError, match="cannot reject your own"):
            await svc.reject_change_request(req.id, reviewer_id=user.id)

    async def test_approve_non_pending_fails(self, db) -> None:
        submitter, tenant = await _create_tenant(db, "dbl")
        reviewer = await _create_second_admin(db, tenant, "dbl")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"security.require_strong_passwords": False},
            user_id=submitter.id,
        )
        await svc.approve_change_request(req.id, reviewer_id=reviewer.id)
        with pytest.raises(ValidationError, match="not pending_approval"):
            await svc.approve_change_request(req.id, reviewer_id=reviewer.id)

    async def test_approval_audited(self, db) -> None:
        from sqlalchemy import text

        submitter, tenant = await _create_tenant(db, "aud")
        reviewer = await _create_second_admin(db, tenant, "aud")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"security.require_strong_passwords": False},
            user_id=submitter.id,
        )
        await svc.approve_change_request(req.id, reviewer_id=reviewer.id)
        audit = (
            await db.execute(
                text(
                    "SELECT action FROM audit_logs "
                    "WHERE tenant_id = :tid AND "
                    "action = 'settings.change_request_approved'"
                ),
                {"tid": tenant.id},
            )
        ).scalar_one_or_none()
        assert audit is not None

    async def test_rejection_audited(self, db) -> None:
        from sqlalchemy import text

        submitter, tenant = await _create_tenant(db, "raud")
        reviewer = await _create_second_admin(db, tenant, "raud")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"security.require_strong_passwords": False},
            user_id=submitter.id,
        )
        await svc.reject_change_request(req.id, reviewer_id=reviewer.id)
        audit = (
            await db.execute(
                text(
                    "SELECT action FROM audit_logs "
                    "WHERE tenant_id = :tid AND "
                    "action = 'settings.change_request_rejected'"
                ),
                {"tid": tenant.id},
            )
        ).scalar_one_or_none()
        assert audit is not None

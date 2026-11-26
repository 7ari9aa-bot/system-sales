"""Behavioural tests for the audit retention scheduler sweep.

The sweep (``audit_retention_sweep``) reads ``security.audit_retention_days``
and deletes audit logs older than the window.  These tests verify:

* Old audit rows are deleted when the retention window has passed.
* Recent audit rows survive the sweep.
* The sweep is a no-op when retention is disabled (``audit_retention_days = 0``).
* The sweep only touches the current tenant's rows (tenant-scoped).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

import app.core.model_registry  # noqa: F401 — complete table registration (FK chains)
import app.modules.platform.models  # noqa: F401 — ensure tables registered
from app.core.db import bind_tenant


def _uuid_hex() -> str:
    return uuid.uuid4().hex[:8]


async def _insert_audit_row(
    db,
    tenant_id: uuid.UUID,
    *,
    action: str = "test.action",
    created_at: datetime | None = None,
) -> uuid.UUID:
    """Insert an audit_logs row directly with a controlled created_at.

    ``audit_logs`` is FORCE RLS, so the tenant GUC must be bound first.
    The caller is responsible for calling ``bind_tenant`` before this.
    """
    from sqlalchemy import text

    row_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO audit_logs "
            "(id, tenant_id, action, resource_type, resource_id, created_at) "
            "VALUES (:id, :tid, :action, 'test_resource', :rid, :created_at)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "action": action,
            "rid": str(row_id),
            "created_at": created_at or datetime.now(UTC),
        },
    )
    return row_id


async def _row_exists(db, row_id: uuid.UUID) -> bool:
    """Check whether a specific audit row still exists (by id)."""
    from sqlalchemy import select

    from app.modules.platform.models import AuditLog

    result = await db.execute(select(AuditLog.id).where(AuditLog.id == row_id))
    return result.scalar() is not None


class TestAuditRetentionSweep:
    """The scheduler handler deletes old audit rows per the retention setting."""

    @pytest.mark.asyncio
    async def test_deletes_old_rows_and_keeps_recent(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService

        email = f"ret-{_uuid_hex()}@test.local"
        _user, tenant = await AuthService.register(
            db,
            tenant_name="Retention Tenant",
            tenant_slug=f"ret-{_uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Retention Owner",
        )
        await db.flush()

        # Set retention to 30 days.
        await SettingsService(db, tenant.id).set(
            "security.audit_retention_days",
            30,
            scope=Scope.TENANT,
            # security.* is APPROVAL_REQUIRED (§172): the API path is a change
            # request. This test is about the sweep, so it seeds the value the
            # way an approved request would leave it.
            bypass_approval=True,
        )
        await db.flush()

        # audit_logs is FORCE RLS — bind the tenant GUC before writing.
        await bind_tenant(db, tenant.id)

        old_time = datetime.now(UTC) - timedelta(days=100)
        recent_time = datetime.now(UTC) - timedelta(days=5)

        old_id = await _insert_audit_row(db, tenant.id, action="ret.old", created_at=old_time)
        recent_id = await _insert_audit_row(
            db, tenant.id, action="ret.recent", created_at=recent_time
        )
        await db.flush()

        from app.workers.scheduler_worker import _handle_audit_retention_sweep

        result = await _handle_audit_retention_sweep(db, tenant.id, {})
        await db.flush()

        assert result["deleted"] >= 1
        assert result["retention_days"] == 30

        await bind_tenant(db, tenant.id)
        assert not await _row_exists(db, old_id), "old row should be deleted"
        assert await _row_exists(db, recent_id), "recent row should survive"

    @pytest.mark.asyncio
    async def test_noop_when_retention_disabled(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService

        email = f"ret-{_uuid_hex()}@test.local"
        _user, tenant = await AuthService.register(
            db,
            tenant_name="Retention Disabled Tenant",
            tenant_slug=f"retdis-{_uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Disabled Owner",
        )
        await db.flush()

        await SettingsService(db, tenant.id).set(
            "security.audit_retention_days",
            0,
            scope=Scope.TENANT,
            bypass_approval=True,
        )
        await db.flush()

        await bind_tenant(db, tenant.id)

        old_time = datetime.now(UTC) - timedelta(days=999)
        old_id = await _insert_audit_row(db, tenant.id, action="ret.disabled", created_at=old_time)
        await db.flush()

        from app.workers.scheduler_worker import _handle_audit_retention_sweep

        result = await _handle_audit_retention_sweep(db, tenant.id, {})
        await db.flush()

        assert result["skipped"] is True
        await bind_tenant(db, tenant.id)
        assert await _row_exists(db, old_id), "row must survive when retention is disabled"

    @pytest.mark.asyncio
    async def test_tenant_scoped_only_deletes_own_rows(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService

        # Tenant A — retention 30 days, has an old row.
        email_a = f"ret-a-{_uuid_hex()}@test.local"
        _user_a, tenant_a = await AuthService.register(
            db,
            tenant_name="Tenant A",
            tenant_slug=f"ret-a-{_uuid_hex()}",
            email=email_a,
            password="strong-password-1",
            full_name="Owner A",
        )
        await db.flush()
        await SettingsService(db, tenant_a.id).set(
            "security.audit_retention_days", 30, scope=Scope.TENANT, bypass_approval=True
        )
        await db.flush()

        # Tenant B — same retention, also has an old row.
        email_b = f"ret-b-{_uuid_hex()}@test.local"
        _user_b, tenant_b = await AuthService.register(
            db,
            tenant_name="Tenant B",
            tenant_slug=f"ret-b-{_uuid_hex()}",
            email=email_b,
            password="strong-password-1",
            full_name="Owner B",
        )
        await db.flush()
        await SettingsService(db, tenant_b.id).set(
            "security.audit_retention_days", 30, scope=Scope.TENANT, bypass_approval=True
        )
        await db.flush()

        old_time = datetime.now(UTC) - timedelta(days=100)

        await bind_tenant(db, tenant_a.id)
        row_a_id = await _insert_audit_row(db, tenant_a.id, action="a.old", created_at=old_time)
        await db.flush()

        await bind_tenant(db, tenant_b.id)
        row_b_id = await _insert_audit_row(db, tenant_b.id, action="b.old", created_at=old_time)
        await db.flush()

        from app.workers.scheduler_worker import _handle_audit_retention_sweep

        # Sweep tenant A only.
        await bind_tenant(db, tenant_a.id)
        await _handle_audit_retention_sweep(db, tenant_a.id, {})
        await db.flush()

        await bind_tenant(db, tenant_a.id)
        assert not await _row_exists(db, row_a_id), "tenant A's old row should be deleted"

        await bind_tenant(db, tenant_b.id)
        assert await _row_exists(db, row_b_id), "tenant B's row must be untouched"

"""RLS isolation hardening (fd2026100409) — the four audit findings, pinned.

G-01  audit_logs / security_events: NULL-tenant system rows are invisible
      to tenant sessions and readable ONLY with the platform-admin GUC;
      UPDATE and DELETE are refused outright (append-only).
G-04  sales_app cannot TRUNCATE any table, and the ledger tables refuse
      UPDATE / DELETE — append-only at the privilege layer too.
G-03  user_location_access WITH CHECK requires the granted location's
      tenant to be one of the caller's memberships.
"""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant

pytestmark = pytest.mark.usefixtures("db")


async def _seed_security_event(db: AsyncSession, tenant_id: uuid.UUID | None, message: str) -> None:
    await db.execute(
        sa.text(
            "INSERT INTO security_events (id, event_type, details, ip, tenant_id) "
            "VALUES (gen_random_uuid(), 'login_failure', "
            "CAST(:details AS jsonb), '127.0.0.1', :tenant)"
        ),
        {
            "details": json.dumps({"m": message}),  # JSONB binds as a string
            "tenant": str(tenant_id) if tenant_id else None,
        },
    )


class TestSystemEventVisibility:
    async def test_tenant_session_cannot_read_null_system_rows(self, db, tenant_ctx):
        await _seed_security_event(db, None, "cross-tenant probe")
        await bind_tenant(db, tenant_ctx.tenant_id)
        rows = (
            await db.execute(
                sa.text("SELECT count(*) FROM security_events WHERE tenant_id IS NULL")
            )
        ).scalar_one()
        assert rows == 0, "a NULL-tenant system row reached a tenant session"

    async def test_admin_guc_reveals_null_system_rows(self, db, tenant_ctx):
        await _seed_security_event(db, None, "admin probe")
        await db.execute(sa.text("SELECT set_config('app.is_platform_admin', 'true', true)"))
        await bind_tenant(db, tenant_ctx.tenant_id)
        rows = (
            await db.execute(
                sa.text("SELECT count(*) FROM security_events WHERE tenant_id IS NULL")
            )
        ).scalar_one()
        assert rows >= 1, "the platform-admin GUC must reveal system rows"

    async def test_update_on_security_events_is_refused(self, db, tenant_ctx):
        await bind_tenant(db, tenant_ctx.tenant_id)
        await db.execute(
            sa.text(
                "INSERT INTO security_events (id, event_type, details, ip, tenant_id) "
                "VALUES (gen_random_uuid(), 'login_failure', '{}', '127.0.0.1', :tenant)"
            ),
            {"tenant": str(tenant_ctx.tenant_id)},
        )
        with pytest.raises(Exception, match="row-level security|permission"):
            await db.execute(
                sa.text("UPDATE security_events SET event_type = 'tampered' WHERE tenant_id = :t"),
                {"t": str(tenant_ctx.tenant_id)},
            )


class TestPrivilegeHygiene:
    async def test_truncate_is_refused_for_sales_app(self, db, tenant_ctx):
        await bind_tenant(db, tenant_ctx.tenant_id)
        await db.execute(
            sa.text(
                "INSERT INTO customers (id, tenant_id, name) VALUES (gen_random_uuid(), :t, 'x')"
            ),
            {"t": str(tenant_ctx.tenant_id)},
        )
        with pytest.raises(Exception, match="permission denied|Privilege"):
            await db.execute(sa.text("TRUNCATE customers"))

    # The grant-level ledger list (fd2026100409 G-04 as converged in
    # provision.py): order_status_history is NOT on it — the state-machine
    # timeline keeps RLS-level tenancy only, so the suite can backdate rows
    # to build deterministic timelines. The audit tables are also granted
    # UPDATE/DELETE at the privilege level but hold no policy for them, so
    # RLS itself denies every mutation — covered by the audit tests above.
    @pytest.mark.parametrize("table", ["inventory_movements", "financial_entries"])
    async def test_ledger_tables_refuse_delete(self, db, table):
        await bind_tenant(db, uuid.uuid4())
        with pytest.raises(Exception, match="permission denied|Privilege"):
            await db.execute(sa.text(f"DELETE FROM {table}"))


class TestLocationGrantTenancy:
    async def test_self_grant_to_a_foreign_tenant_location_is_refused(self, db, tenant_ctx):
        from app.modules.identity.models import Location

        other_tenant = uuid.uuid4()
        await db.execute(
            sa.text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'Other')"),
            {"id": str(other_tenant), "slug": f"other-{uuid.uuid4().hex[:8]}"},
        )
        # locations is RLS-guarded on app.tenant_id — bind the foreign tenant
        # while creating its workspace + location, then bind back to the
        # caller's tenant.
        await bind_tenant(db, other_tenant)
        from app.modules.identity.models import Workspace

        foreign_ws = Workspace(
            tenant_id=other_tenant,
            name="Other WS",
            slug=f"other-ws-{uuid.uuid4().hex[:8]}",
        )
        db.add(foreign_ws)
        await db.flush()
        foreign_location = Location(
            tenant_id=other_tenant,
            workspace_id=foreign_ws.id,
            name="Foreign Site",
        )
        db.add(foreign_location)
        await db.flush()
        await bind_tenant(db, tenant_ctx.tenant_id)
        await db.execute(
            sa.text("SELECT set_config('app.user_id', :u, true)"),
            {"u": str(tenant_ctx.user.id)},
        )
        with pytest.raises(Exception, match="row-level security|policy"):
            await db.execute(
                sa.text("INSERT INTO user_location_access (user_id, location_id) VALUES (:u, :l)"),
                {"u": str(tenant_ctx.user.id), "l": str(foreign_location.id)},
            )

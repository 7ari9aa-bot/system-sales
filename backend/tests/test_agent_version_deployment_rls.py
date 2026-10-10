"""agent_versions / agent_deployments tenant isolation (fe2026100810).

Both tables were created after the RLS sweep and shipped without a policy —
any tenant session could read and write every other tenant's version
snapshots and canary state. The migration gives them the standard tenant
plane treatment; these tests pin it.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.modules.ai.models import Agent, AgentVersion, Deployment

pytestmark = pytest.mark.usefixtures("db")

_TABLES = ("agent_versions", "agent_deployments")


async def _seed_agent_stack(db: AsyncSession, tenant_id: uuid.UUID) -> Agent:
    agent = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Isolation Agent",
        model="fast",
        system_prompt="p",
    )
    db.add_all(
        [
            agent,
            AgentVersion(
                tenant_id=tenant_id,
                agent_id=agent.id,
                version=1,
                status="published",
                system_prompt="p",
                model="fast",
            ),
            Deployment(tenant_id=tenant_id, agent_id=agent.id),
        ]
    )
    await db.flush()
    return agent


class TestPolicyPresence:
    async def test_enabled_and_forced_with_tenant_isolation(self, db):
        for table in _TABLES:
            row = (
                await db.execute(
                    sa.text(
                        "SELECT relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE relname = :t"
                    ),
                    {"t": table},
                )
            ).one()
            assert row.relrowsecurity is True, f"{table} has no RLS"
            assert row.relforcerowsecurity is True, f"{table} RLS is not forced"

            policy = (
                await db.execute(
                    sa.text(
                        "SELECT qual, with_check FROM pg_policies "
                        "WHERE schemaname='public' AND tablename=:t "
                        "AND policyname='tenant_isolation'"
                    ),
                    {"t": table},
                )
            ).scalar_one_or_none()
            assert policy is not None, f"{table} has no tenant_isolation policy"
            assert "app.tenant_id" in policy.qual
            assert "app.tenant_id" in policy.with_check


class TestTenantIsolation:
    async def test_other_tenant_rows_are_invisible(self, db, tenant_ctx):
        tenant_id = tenant_ctx.tenant_id
        agent = await _seed_agent_stack(db, tenant_id)

        other_tenant = uuid.uuid4()
        await db.execute(
            sa.text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'Other')"),
            {"id": str(other_tenant), "slug": f"other-{uuid.uuid4().hex[:8]}"},
        )
        await bind_tenant(db, other_tenant)

        for table, agent_col in (
            ("agent_versions", agent.id),
            ("agent_deployments", agent.id),
        ):
            rows = (
                await db.execute(
                    sa.text(f"SELECT count(*) FROM {table} WHERE agent_id = :a"),
                    {"a": str(agent_col)},
                )
            ).scalar_one()
            assert rows == 0, f"a foreign tenant can read {table} rows"

    async def test_own_tenant_rows_stay_visible_under_force(self, db, tenant_ctx):
        agent = await _seed_agent_stack(db, tenant_ctx.tenant_id)
        versions = (
            await db.execute(
                sa.text("SELECT count(*) FROM agent_versions WHERE agent_id = :a"),
                {"a": str(agent.id)},
            )
        ).scalar_one()
        deployments = (
            await db.execute(
                sa.text("SELECT count(*) FROM agent_deployments WHERE agent_id = :a"),
                {"a": str(agent.id)},
            )
        ).scalar_one()
        assert versions == 1 and deployments == 1

    async def test_cross_tenant_write_is_refused(self, db, tenant_ctx):
        tenant_id = tenant_ctx.tenant_id
        agent = await _seed_agent_stack(db, tenant_id)

        other_tenant = uuid.uuid4()
        await db.execute(
            sa.text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'Other')"),
            {"id": str(other_tenant), "slug": f"other-{uuid.uuid4().hex[:8]}"},
        )
        await bind_tenant(db, other_tenant)

        with pytest.raises(Exception, match="row-level security|policy|permission"):
            await db.execute(
                sa.text(
                    "INSERT INTO agent_versions "
                    "(tenant_id, agent_id, version, status) "
                    "VALUES (:t, :a, 1, 'draft')"
                ),
                {"t": str(tenant_id), "a": str(agent.id)},
            )

"""Published agent versions (P1-5): publish service, DB-level immutability,
tool-policy filtering, and the runtime's explicit fallback policy."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import Agent, AgentVersion, Deployment
from app.modules.ai.runtime import AgentRunner
from app.modules.ai.versions import AIAgentVersionService, filter_agent_tools_by_policy

pytestmark = pytest.mark.usefixtures("db")


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


class TestToolPolicyFilter:
    def test_no_policy_keeps_everything(self) -> None:
        tools = [_tool("search_products"), _tool("create_order")]
        assert filter_agent_tools_by_policy(tools, {}) == tools
        assert filter_agent_tools_by_policy(tools, None) == tools
        assert filter_agent_tools_by_policy(tools, "not-a-dict") == tools

    def test_deny_subtracts(self) -> None:
        tools = [_tool("search_products"), _tool("create_order")]
        kept = filter_agent_tools_by_policy(tools, {"deny": ["create_order"]})
        assert [t.name for t in kept] == ["search_products"]

    def test_allow_narrows(self) -> None:
        tools = [_tool("search_products"), _tool("create_order")]
        kept = filter_agent_tools_by_policy(tools, {"allow": ["search_products"]})
        assert [t.name for t in kept] == ["search_products"]

    def test_deny_wins_over_allow(self) -> None:
        tools = [_tool("a"), _tool("b")]
        kept = filter_agent_tools_by_policy(tools, {"allow": ["a", "b"], "deny": ["b"]})
        assert [t.name for t in kept] == ["a"]

    def test_malformed_entries_fail_open(self) -> None:
        tools = [_tool("a"), _tool("b")]
        assert filter_agent_tools_by_policy(tools, {"deny": [1, None]}) == tools
        assert filter_agent_tools_by_policy(tools, {"allow": "a"}) == tools


def _agent(tenant_id: uuid.UUID, **overrides) -> Agent:
    fields = dict(
        tenant_id=tenant_id,
        kind="customer",
        name="Versioned Agent",
        model="fast",
        system_prompt="row prompt",
        temperature=0.7,
        run_limits={},
    )
    fields.update(overrides)
    return Agent(**fields)


class TestPublish:
    async def test_first_publish_snapshots_the_agent_row(self, db, tenant_ctx) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()

        version = await AIAgentVersionService.publish(
            db, tenant_ctx.tenant_id, agent.id, published_by=tenant_ctx.user.id
        )
        assert version.version == 1
        assert version.status == "published"
        assert version.system_prompt == "row prompt"
        assert version.published_by == tenant_ctx.user.id
        assert version.published_at is not None

    async def test_republishing_identical_config_returns_the_same_row(
        self, db, tenant_ctx
    ) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()

        first = await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        again = await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        assert again.id == first.id
        assert again.version == 1

    async def test_changed_config_mints_version_2(self, db, tenant_ctx) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()

        await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        agent.system_prompt = "edited prompt"
        await db.flush()

        second = await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        assert second.version == 2
        assert second.system_prompt == "edited prompt"

    async def test_unknown_agent_is_404(self, db, tenant_ctx) -> None:
        from app.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, uuid.uuid4())


class TestPublishedImmutability:
    async def _published(self, db: AsyncSession, tenant_id: uuid.UUID) -> AgentVersion:
        agent = _agent(tenant_id)
        db.add(agent)
        await db.flush()
        return await AIAgentVersionService.publish(db, tenant_id, agent.id)

    async def test_update_of_snapshot_columns_is_refused(self, db, tenant_ctx) -> None:
        version = await self._published(db, tenant_ctx.tenant_id)
        with pytest.raises(Exception, match="immutable"):
            await db.execute(
                sa.update(AgentVersion)
                .where(AgentVersion.id == version.id)
                .values(system_prompt="tampered")
            )

    async def test_delete_of_published_is_refused(self, db, tenant_ctx) -> None:
        version = await self._published(db, tenant_ctx.tenant_id)
        with pytest.raises(Exception, match="immutable"):
            await db.execute(sa.delete(AgentVersion).where(AgentVersion.id == version.id))

    async def test_archive_flip_is_the_one_allowed_transition(self, db, tenant_ctx) -> None:
        version = await self._published(db, tenant_ctx.tenant_id)
        await db.execute(
            sa.update(AgentVersion)
            .where(AgentVersion.id == version.id)
            .values(status="archived")
        )

    async def test_draft_rows_stay_editable(self, db, tenant_ctx) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()
        draft = AgentVersion(
            tenant_id=tenant_ctx.tenant_id, agent_id=agent.id, status="draft"
        )
        db.add(draft)
        await db.flush()
        draft.system_prompt = "still drafting"
        await db.flush()
        assert draft.system_prompt == "still drafting"


class TestRuntimeResolution:
    async def test_deployment_serves_the_published_snapshot(self, db, tenant_ctx) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()
        version = await AIAgentVersionService.publish(
            db, tenant_ctx.tenant_id, agent.id, tool_policy={"deny": ["create_order"]}
        )
        db.add(
            Deployment(
                tenant_id=tenant_ctx.tenant_id,
                agent_id=agent.id,
                stable_version_id=version.id,
                canary_percent=0,
                status="active",
            )
        )
        await db.flush()

        version_id, source, policy = await AgentRunner._resolve_agent_version(
            db, tenant_ctx.tenant_id, agent, canary_chosen=False
        )
        assert version_id == version.id
        assert source == "deployment"
        assert policy == {"deny": ["create_order"]}
        assert agent.system_prompt == "row prompt"  # patched from the snapshot

    async def test_no_deployment_falls_back_and_says_so(self, db, tenant_ctx) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()

        version_id, source, policy = await AgentRunner._resolve_agent_version(
            db, tenant_ctx.tenant_id, agent, canary_chosen=False
        )
        assert version_id is None
        assert source == "fallback:no_deployment"
        assert policy is None

    async def test_unpublished_version_id_falls_back(self, db, tenant_ctx) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()
        # "Points at nothing published", FK-honestly: a real version row that
        # never left draft. The resolver must refuse it exactly like a missing
        # row — the stable_version_id column has a real FK, so a random uuid
        # cannot even be inserted.
        draft = AgentVersion(
            tenant_id=tenant_ctx.tenant_id,
            agent_id=agent.id,
            version=1,
            status="draft",
            system_prompt="p",
            model="fast",
        )
        db.add(draft)
        await db.flush()
        db.add(
            Deployment(
                tenant_id=tenant_ctx.tenant_id,
                agent_id=agent.id,
                stable_version_id=draft.id,
                status="active",
            )
        )
        await db.flush()

        version_id, source, policy = await AgentRunner._resolve_agent_version(
            db, tenant_ctx.tenant_id, agent, canary_chosen=False
        )
        assert version_id is None
        assert source == "fallback:version_not_published"
        assert policy is None

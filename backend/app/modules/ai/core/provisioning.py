"""Canonical Agent Provisioning — ensures tenants have all canonical agents.

This module is the **single provisioning entry-point** for canonical agents.
It is called:

1. During **tenant creation** — ``provision_canonical_agents(session, tenant_id)``
   creates agents + default tools for the new tenant.
2. As a **backfill** — ``backfill_all_tenants(session)`` iterates all tenants
   and fills gaps (missing agents, missing tools on existing agents).
3. At **startup** (optional) — ``sync_existing_tenant_tools(session, tenant_id)``
   ensures an already-existing agent has all the tools its definition requires.

Architecture invariants
-----------------------
* Only definitions with ``provisioning_policy.is_canonical == True`` and
  ``provisioning_policy.auto_provision == True`` are provisioned automatically.
* This module NEVER deletes tools or agents — it only ADDS missing ones.
* All tool insertions are validated against ``AgentRegistry.is_tool_authorized``.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.core.registry import AgentRegistry
from app.modules.ai.models import Agent, AgentTool

logger = logging.getLogger(__name__)


async def provision_canonical_agents(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[Agent]:
    """Create all canonical agents (+ default tools) for a tenant.

    Idempotent: skips agents that already exist for this tenant.
    Returns list of newly created agents.
    """
    created: list[Agent] = []

    for defn in AgentRegistry.get_all():
        policy = defn.provisioning_policy or {}
        if not policy.get("is_canonical") or not policy.get("auto_provision"):
            continue

        # Check if agent already exists
        existing = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.kind == defn.kind,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            # Agent exists — ensure it has all default tools
            await _sync_agent_tools(session, tenant_id, existing.id, defn.kind)
            continue

        # Create the canonical agent
        agent = Agent(
            tenant_id=tenant_id,
            kind=defn.kind,
            name=defn.name,
            model=defn.default_model,
            system_prompt=defn.system_prompt_template,
            description=defn.description,
        )
        session.add(agent)
        await session.flush()

        # Provision default tools
        for tool_name in defn.default_tools:
            if not AgentRegistry.is_tool_authorized(defn.kind, tool_name):
                logger.error(
                    "provisioning.tool_not_authorized kind=%s tool=%s — skipping",
                    defn.kind,
                    tool_name,
                )
                continue
            session.add(
                AgentTool(
                    tenant_id=tenant_id,
                    agent_id=agent.id,
                    name=tool_name,
                    policy={},
                )
            )

        await session.flush()
        created.append(agent)
        logger.info(
            "provisioning.created_agent tenant=%s kind=%s tools=%d",
            tenant_id,
            defn.kind,
            len(defn.default_tools),
        )

    return created


async def _sync_agent_tools(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    kind: str,
) -> int:
    """Ensure an existing agent has all default tools for its kind.

    Adds missing tools without removing existing ones. Returns count of newly added tools.
    """
    defn = AgentRegistry.get(kind)

    # Get existing tool names
    existing_tools = set(
        (
            await session.execute(
                select(AgentTool.name).where(
                    AgentTool.tenant_id == tenant_id,
                    AgentTool.agent_id == agent_id,
                )
            )
        )
        .scalars()
        .all()
    )

    added = 0
    for tool_name in defn.default_tools:
        if tool_name in existing_tools:
            continue
        if not AgentRegistry.is_tool_authorized(kind, tool_name):
            logger.error(
                "provisioning.sync_tool_not_authorized kind=%s tool=%s",
                kind,
                tool_name,
            )
            continue
        session.add(
            AgentTool(
                tenant_id=tenant_id,
                agent_id=agent_id,
                name=tool_name,
                policy={},
            )
        )
        added += 1

    if added:
        await session.flush()
        logger.info(
            "provisioning.synced_tools tenant=%s agent=%s kind=%s added=%d",
            tenant_id,
            agent_id,
            kind,
            added,
        )

    return added


async def sync_existing_tenant_tools(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[str, int]:
    """Sync all agents for one tenant — ensure each has all default tools.

    Returns dict of {kind: tools_added}.
    """
    result: dict[str, int] = {}
    agents = (
        (await session.execute(select(Agent).where(Agent.tenant_id == tenant_id))).scalars().all()
    )

    for agent in agents:
        if not AgentRegistry.has(agent.kind):
            logger.warning(
                "provisioning.unknown_kind tenant=%s agent=%s kind=%s — skipping",
                tenant_id,
                agent.id,
                agent.kind,
            )
            continue
        added = await _sync_agent_tools(session, tenant_id, agent.id, agent.kind)
        if added:
            result[agent.kind] = added

    return result


async def backfill_all_tenants(session: AsyncSession) -> dict[str, int]:
    """Iterate ALL tenants and provision/sync canonical agents.

    Returns dict of {tenant_id: agents_created_or_synced}.
    Safe to run repeatedly (idempotent).
    """
    from sqlalchemy import text as sa_text

    rows = await session.execute(sa_text("SELECT id FROM tenants"))
    tenants = [row[0] for row in rows.all()]

    result: dict[str, int] = {}
    for tid in tenants:
        created = await provision_canonical_agents(session, tid)
        if created:
            result[str(tid)] = len(created)

    logger.info("provisioning.backfill_complete tenants=%d created=%s", len(tenants), result)
    return result

"""Configure the Sales Intelligence agent with the approved GLM provider (D16).

    .venv/bin/python scripts/configure_si.py <tenant_id>

D16 resolution recorded in docs/adrs/D16-si-provider-novita-glm.md: the approved
provider is NOVITA serving GLM-5.3 (user decision 2026-10-03). This script
upserts the tenant's model_configs rows for the aliases the SI agent rides
(strong = GLM-5.3, fast = GLM-5.3-flash) — data, not code: swapping provider
later is a row update. Idempotent. The provider key comes from the
environment (NOVITA_API_KEY) or backend/.env — never argv, never committed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from _bootstrap import session_factory
from sqlalchemy import select

from app.core.model_registry import Base  # noqa: F401 — full metadata for FKs
from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
from app.modules.ai.models import Agent, AgentTool, ModelConfig

NOVITA_BASE = "https://api.novita.ai/v3/openai"
STRONG_MODEL = "zai-org/glm-5.3"
FAST_MODEL = "zai-org/glm-5.3-flash"


async def configure_agent(session, tenant_id: uuid.UUID, *, api_key: str) -> uuid.UUID:
    """Upsert model_configs (strong/fast) + the SI agent with all SI tools.

    Reusable by the eval harness and the demo script — the same rows
    production would carry for this tenant.
    """
    for alias, model in (("strong", STRONG_MODEL), ("fast", FAST_MODEL)):
        row = (
            await session.execute(
                select(ModelConfig).where(
                    ModelConfig.tenant_id == tenant_id,
                    ModelConfig.alias == alias,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = ModelConfig(tenant_id=tenant_id, alias=alias)
            session.add(row)
        row.provider = "novita"
        row.model = model
        row.config = {"base_url": NOVITA_BASE, "api_key": api_key}
        row.is_active = True
    await session.flush()

    agent = (
        await session.execute(
            select(Agent).where(
                Agent.tenant_id == tenant_id,
                Agent.is_active.is_(True),
            )
        )
    ).scalars().first()
    if agent is None:
        agent = Agent(
            tenant_id=tenant_id,
            name="Sales Intelligence Agent",
            model="strong",
            system_prompt="أنت محلل مبيعات المتجر.",
        )
        session.add(agent)
        await session.flush()
    else:
        agent.model = "strong"

    existing = {
        r.name
        for r in (
            await session.execute(
                select(AgentTool).where(
                    AgentTool.tenant_id == tenant_id,
                    AgentTool.agent_id == agent.id,
                )
            )
        ).scalars()
    }
    for name in SI_TOOLS:
        if name not in existing:
            session.add(
                AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=name, policy={})
            )
    await session.flush()
    return agent.id


async def main(tenant_id: uuid.UUID, api_key: str) -> int:
    factory = session_factory()
    async with factory() as session:
        from app.core.db import bind_tenant

        await bind_tenant(session, tenant_id)
        agent_id = await configure_agent(session, tenant_id, api_key=api_key)
        await session.commit()
    print(f"configured: tenant={tenant_id} agent={agent_id} "
          f"strong={STRONG_MODEL} fast={FAST_MODEL}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/configure_si.py <tenant_id>")
        sys.exit(2)
    key = os.environ.get("NOVITA_API_KEY") or ""
    if not key:
        print("set NOVITA_API_KEY in the environment (or backend/.env)")
        sys.exit(2)
    sys.exit(asyncio.run(main(uuid.UUID(sys.argv[1]), key)))

"""Published agent versions: snapshot on publish, immutable after, and the
tool-policy filter the runtime applies to whatever version (or fallback row)
won the canary decision.

The policy semantics are deliberately tiny and auditable — a JSONB dict of
optional ``allow`` and ``deny`` name lists:

- no policy / ``{}``  → every registry-authorized tool stays authorized;
- ``allow`` present   → an intersection with the authorized set;
- ``deny`` present    → subtracted, and deny WINS over allow.

The filter never ADDS authorization: it can only narrow what the registry
already authorized (§: tool isolation is the registry's decision, the policy
is the publisher's veto on top).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.ai.models import Agent, AgentVersion


def filter_agent_tools_by_policy(
    tools: list, policy: dict | None
) -> list:
    """Narrow ``tools`` (AgentTool rows) by a version/agent tool policy.

    Malformed policies fail OPEN (treated as empty) — a typo in a publish
    payload must not silently strip every tool from a live agent.
    """
    if not isinstance(policy, dict):
        return tools
    allow = policy.get("allow")
    deny = policy.get("deny")
    if not isinstance(allow, (list, tuple)):
        allow = None
    if not isinstance(deny, (list, tuple)):
        deny = ()
    deny_set = {d for d in deny if isinstance(d, str)}
    allow_set = {a for a in allow if isinstance(a, str)} if allow is not None else None
    if not deny_set and allow_set is None:
        return tools
    return [
        t
        for t in tools
        if t.name not in deny_set and (allow_set is None or t.name in allow_set)
    ]


class AIAgentVersionService:
    """Publish the agent's current configuration as an immutable version."""

    @staticmethod
    async def publish(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        *,
        published_by: uuid.UUID | None = None,
        tool_policy: dict | None = None,
    ) -> AgentVersion:
        """Snapshot the agent row into a new published version.

        Republishing an UNCHANGED configuration returns the existing published
        snapshot instead of minting a no-op version — the version number means
        "a configuration the runtime should distinguish", and identical
        content is not that.
        """
        agent = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.id == agent_id,
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise NotFoundError(f"agent {agent_id} not found")

        published = (
            await session.execute(
                select(AgentVersion)
                .where(
                    AgentVersion.tenant_id == tenant_id,
                    AgentVersion.agent_id == agent_id,
                    AgentVersion.status == "published",
                )
                .order_by(AgentVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        # JSONB columns normalize before comparing: an agent row whose
        # run_limits server default has not been flushed back into memory
        # (None in-process, {} in the database) must not read as "changed".
        identical = published is not None and all(
            getattr(published, field) == getattr(agent, field)
            for field in ("system_prompt", "model", "temperature", "max_output_tokens")
        ) and dict(published.run_limits or {}) == dict(agent.run_limits or {}) and dict(
            published.tool_policy or {}
        ) == dict(tool_policy or {})
        if identical:
            return published

        version = AgentVersion(
            tenant_id=tenant_id,
            agent_id=agent_id,
            version=(published.version + 1) if published is not None else 1,
            system_prompt=agent.system_prompt,
            model=agent.model,
            temperature=agent.temperature,
            max_output_tokens=agent.max_output_tokens,
            run_limits=dict(agent.run_limits or {}),
            tool_policy=dict(tool_policy or {}),
            status="published",
            published_at=datetime.now(UTC),
            published_by=published_by,
        )
        session.add(version)
        await session.flush()
        return version

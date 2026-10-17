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

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.ai.models import Agent, AgentVersion

logger = logging.getLogger(__name__)


def filter_agent_tools_by_policy(tools: list, policy: dict | None) -> list:
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
        t for t in tools if t.name not in deny_set and (allow_set is None or t.name in allow_set)
    ]


async def _ensure_stable_deployment(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    version: AgentVersion,
) -> None:
    """Activate the published version as stable when NO deployment exists.

    This is the publish path's half of the pinning contract: a store whose
    agent has never been deployed (the pre-fe2026100818 production state —
    22 published versions, zero ``agent_deployments`` rows) kept running the
    agent's MUTABLE settings on every run, because the runtime's resolver
    falls back exactly when the deployment row is missing. Publishing must
    therefore leave the store in the state the runtime pins to, in the SAME
    transaction as the version itself — a published version with no
    deployment is a snapshot nobody serves.

    Deliberately creation-ONLY: an existing deployment row — active canary,
    full rollout, or a human rollback — is never touched here. Canary and
    rollback belong to the evaluation service and the deployment API; a
    republish must not silently rewrite what traffic is being served. An
    existing row with a NULL stable slot (degenerate, test-seeded) is also
    left alone for the same reason.

    The SELECT-then-INSERT has a concurrency window; the savepoint turns a
    loser of the ``uq_agent_deployments_tenant_agent`` insert race into a
    no-op instead of a poisoned transaction — same containment the runtime
    uses for its idempotency-keyed ToolCall inserts.
    """
    from app.modules.ai.models import Deployment

    existing = (
        await session.execute(
            select(Deployment).where(
                Deployment.tenant_id == tenant_id,
                Deployment.agent_id == agent_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    try:
        async with session.begin_nested():
            session.add(
                Deployment(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    stable_version_id=version.id,
                    canary_percent=0,
                    status="active",
                )
            )
            await session.flush()
    except IntegrityError:
        logger.info(
            "ai.deployment_activate_lost_race agent=%s version=%s",
            agent_id,
            version.version,
        )
        return
    logger.info(
        "ai.deployment_activated agent=%s version=%s source=publish",
        agent_id,
        version.version,
    )


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
        identical = (
            published is not None
            and all(
                getattr(published, field) == getattr(agent, field)
                for field in (
                    "system_prompt",
                    "persona_prompt",
                    "model",
                    "temperature",
                    "max_output_tokens",
                )
            )
            and dict(published.run_limits or {}) == dict(agent.run_limits or {})
            and dict(published.tool_policy or {}) == dict(tool_policy or {})
        )
        if identical:
            await _ensure_stable_deployment(session, tenant_id, agent_id, published)
            return published

        version = AgentVersion(
            tenant_id=tenant_id,
            agent_id=agent_id,
            version=(published.version + 1) if published is not None else 1,
            system_prompt=agent.system_prompt,
            persona_prompt=agent.persona_prompt,
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
        await _ensure_stable_deployment(session, tenant_id, agent_id, version)
        return version

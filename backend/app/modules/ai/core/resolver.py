"""Agent resolution utilities — find agents by kind, not by hardcoded ID.

These helpers replace every place in the codebase that does:
    SELECT agents WHERE is_active AND tenant_id = :tid ORDER BY created_at LIMIT 1

with kind-aware resolution:
    SELECT agents WHERE kind = :kind AND is_active AND tenant_id = :tid
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.ai.models import Agent


async def resolve_agent_by_kind(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    kind: str,
) -> Agent:
    """Find the tenant's active agent of a given kind.

    Raises ``NotFoundError`` if no active agent of that kind exists.
    """
    agent = (
        await session.execute(
            select(Agent)
            .where(
                Agent.tenant_id == tenant_id,
                Agent.kind == kind,
                Agent.is_active.is_(True),
            )
            .order_by(Agent.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"no active '{kind}' agent for this tenant")
    return agent


async def resolve_agent_by_kind_optional(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    kind: str,
) -> Agent | None:
    """Same as ``resolve_agent_by_kind`` but returns None instead of raising."""
    return (
        await session.execute(
            select(Agent)
            .where(
                Agent.tenant_id == tenant_id,
                Agent.kind == kind,
                Agent.is_active.is_(True),
            )
            .order_by(Agent.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_agents_by_kind(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    kind: str,
) -> list[Agent]:
    """All active agents of a given kind for a tenant."""
    rows = (
        await session.execute(
            select(Agent)
            .where(
                Agent.tenant_id == tenant_id,
                Agent.kind == kind,
                Agent.is_active.is_(True),
            )
            .order_by(Agent.created_at.asc())
        )
    ).scalars()
    return list(rows.all())

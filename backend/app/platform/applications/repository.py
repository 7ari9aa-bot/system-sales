"""Reads the commercial tables into the facts the gate decides on.

SQL here, judgement in access.py: two queries, no policy.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.applications.access import AccessFacts
from app.platform.applications.manifests import normalize_key
from app.platform.applications.models import (
    PlanApplicationInclusion,
    SubscriptionItem,
    WorkspaceAppInstallation,
)
from app.platform.billing.models import Subscription

#: States that still grant what was sold.
LIVE = ("trialing", "active", "past_due")


async def entitled(
    session: AsyncSession, *, tenant_id: uuid.UUID, workspace_id: uuid.UUID | None
) -> frozenset[str]:
    """What the live subscription entitles: plan inclusions plus bought items.

    An item with no workspace covers the account; one with a workspace covers
    only that business, which is how two shops end up with different products.
    """
    subs = (
        await session.execute(
            select(Subscription.id, Subscription.plan_id).where(
                Subscription.tenant_id == tenant_id, Subscription.status.in_(LIVE)
            )
        )
    ).all()
    if not subs:
        return frozenset()
    ids = [row[0] for row in subs]
    plans = [row[1] for row in subs if row[1]]
    keys: set[str] = set()
    if plans:
        keys |= set(
            (
                await session.execute(
                    select(PlanApplicationInclusion.application_key).where(
                        PlanApplicationInclusion.plan_id.in_(plans)
                    )
                )
            )
            .scalars()
            .all()
        )
    scope = SubscriptionItem.workspace_id.is_(None)
    if workspace_id is not None:
        scope = or_(scope, SubscriptionItem.workspace_id == workspace_id)
    keys |= set(
        (
            await session.execute(
                select(SubscriptionItem.application_key).where(
                    SubscriptionItem.subscription_id.in_(ids), scope
                )
            )
        )
        .scalars()
        .all()
    )
    return frozenset(normalize_key(key) for key in keys)


async def installed(session: AsyncSession, *, workspace_id: uuid.UUID) -> dict[str, str]:
    """Every application this workspace has a row for, with its state."""
    rows = (
        await session.execute(
            select(WorkspaceAppInstallation.application_key, WorkspaceAppInstallation.state).where(
                WorkspaceAppInstallation.workspace_id == workspace_id
            )
        )
    ).all()
    return {normalize_key(key): state for key, state in rows}


async def gather_facts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
    application_key: str,
) -> AccessFacts:
    """The facts one gate needs."""
    states = await installed(session, workspace_id=workspace_id) if workspace_id else {}
    return AccessFacts(
        application_key=application_key,
        entitled_applications=await entitled(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        ),
        installation_states=states,
    )

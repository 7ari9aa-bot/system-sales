"""CI-only RLS proof for the SI chat tables (spec §SI-chat).

These run against a real Postgres in CI (DATABASE_URL_APP_ADMIN) and skip
locally — the honest-RED convention. What they pin:

1. tenant_isolation on ai_chat_threads/ai_chat_messages hides another
   tenant's rows from an app-role session, in BOTH directions.
2. The sales_app grants exist: the app role can INSERT and SELECT its own
   thread and message (the provision.py prints-owner-counts lesson — a
   policy without a grant is a silent lockout).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.core.db import bind_tenant
from app.modules.ai.models import Agent, AIChatMessage, AIChatThread

pytestmark = [pytest.mark.usefixtures("db")]


async def _si_agent(db, tenant_id) -> Agent:
    """The FK lesson: thread.agent_id RESTRICTs to a REAL agent row."""
    agent = Agent(
        tenant_id=tenant_id,
        kind="sales_intelligence",
        name="Sales Intelligence",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    return agent


async def test_thread_policy_hides_other_tenant_rows_as_app_role(db, tenant_ctx):
    agent = await _si_agent(db, tenant_ctx.tenant_id)
    thread = AIChatThread(
        tenant_id=tenant_ctx.tenant_id,
        agent_id=agent.id,
        created_by_user_id=tenant_ctx.user.id,
        title="mine",
    )
    db.add(thread)
    await db.flush()

    # A second REAL tenant (the FK lesson again — no synthetic uuid tenants).
    from app.modules.identity.models import Tenant  # noqa: PLC0415 — test-local import

    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Tenant")
    db.add(other)
    await db.flush()

    # Rebind the GUC to the OTHER tenant: RLS must hide tenant A's thread.
    await bind_tenant(db, other.id)
    visible_from_other = (
        await db.execute(sa.select(AIChatThread).where(AIChatThread.id == thread.id))
    ).scalar_one_or_none()
    assert visible_from_other is None, "cross-tenant thread must be invisible"

    # ... and back: the owner's own row is visible again.
    await bind_tenant(db, tenant_ctx.tenant_id)
    visible_from_owner = (
        await db.execute(sa.select(AIChatThread).where(AIChatThread.id == thread.id))
    ).scalar_one()
    assert visible_from_owner.id == thread.id


async def test_app_role_can_insert_and_select_own_thread_and_message(db, tenant_ctx):
    agent = await _si_agent(db, tenant_ctx.tenant_id)
    thread = AIChatThread(
        tenant_id=tenant_ctx.tenant_id,
        agent_id=agent.id,
        created_by_user_id=tenant_ctx.user.id,
        title="grants probe",
    )
    db.add(thread)
    await db.flush()

    message = AIChatMessage(
        tenant_id=tenant_ctx.tenant_id,
        thread_id=thread.id,
        sequence_no=1,
        role="user",
        status="completed",
        content="قارن مبيعات الشهر ده باللي فات.",
    )
    db.add(message)
    await db.flush()

    fetched_thread = (
        await db.execute(sa.select(AIChatThread).where(AIChatThread.id == thread.id))
    ).scalar_one()
    fetched_message = (
        await db.execute(sa.select(AIChatMessage).where(AIChatMessage.id == message.id))
    ).scalar_one()
    assert fetched_thread.title == "grants probe"
    assert fetched_message.sequence_no == 1
    assert fetched_message.role == "user"

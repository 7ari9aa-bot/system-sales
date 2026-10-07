"""§176 gate scenario 15 — stale-run cancellation (§126).

§126: "at most ONE state-mutating processor (AI run / agent reply / automation)
may act on a conversation at a time." A stale response is what an unguarded run
produces — an older run finishing after a newer message arrived and answering
the wrong question, or two runs interleaving their tool calls. The mechanism is
the conversation lease, acquired INSIDE ``AgentRunner.run`` (runtime.py:175) so
EVERY caller is serialized, not just the message-worker hook.

The gate that claimed this scenario (`test_gate.py::test_gate_ai_stale_run_can-
cellation`) asserted two things: that ``AgentRunner.run`` is callable, and that
a second raw ``pg_try_advisory_lock`` fails — which is a duplicate of scenario 5
and never enters the run path. Deleting the ``conversation_lease`` call from
``AgentRunner.run`` leaves that test green, because it never runs ``run()``.

This test drives the REAL ``AgentRunner.run``:

* with one committed transaction already holding the conversation lease (a run
  mid-flight), a second ``AgentRunner.run`` on the SAME conversation from a
  DIFFERENT backend is refused with ``ConversationBusy`` — it cannot slip its
  mutating work in underneath the first;
* once the first transaction commits (lease released), a fresh run boundary is
  admitted — the refusal is transient (the event requeues), not a deadlock.

DB-backed with real committed rows on independent connections (row-lock
serialization cannot exist on one rolled-back connection); skips via ``db_url``
without an application database — CI-only evidence.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import bind_tenant
from app.core.lease import ConversationBusy, conversation_lease
from app.modules.ai.models import Agent
from app.modules.ai.runtime import AgentRunner
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.identity.models import Tenant

pytestmark = [pytest.mark.gate]


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        db_url,
        pool_size=4,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    try:
        yield eng
    finally:
        await eng.dispose()


@asynccontextmanager
async def _tx(engine: AsyncEngine, tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """One independent backend, one committed transaction bound to `tenant_id`."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await bind_tenant(session, tenant_id)
            yield session


async def _seed(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Commit a tenant with an active agent and a conversation. Returns
    (tenant_id, agent_id, conversation_id) as plain UUIDs."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        tenant = Tenant(slug=f"stale-{uuid.uuid4().hex[:10]}", name="Stale Run Gate")
        session.add(tenant)
        await session.flush()
        tid = tenant.id
        await bind_tenant(session, tid)
        agent = Agent(tenant_id=tid, name="Gate Agent", model="fast", is_active=True)
        session.add(agent)
        await session.flush()
        agent_id = agent.id
        customer = Customer(tenant_id=tid, name="Gate")
        session.add(customer)
        await session.flush()
        convo = await ConversationService.get_or_create(
            session, tid, customer_id=customer.id, channel="webchat"
        )
        conv_id = convo.id
    return tid, agent_id, conv_id


async def _cleanup(engine: AsyncEngine, tid: uuid.UUID) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            await bind_tenant(session, tid)
            for table in ("agent_runs", "tool_calls", "conversations", "customers", "agents"):
                await session.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tid})
        async with factory() as session, session.begin():
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
    except Exception:  # noqa: BLE001 — cleanup must never mask an assertion
        pass


async def test_gate_a_second_run_cannot_enter_a_conversation_being_processed(
    engine,
) -> None:
    tid, agent_id, conv_id = await _seed(engine)
    try:
        # Backend A holds the lease the way AgentRunner.run does, for the whole
        # duration of its mutating critical section (advisory xact lock lives to
        # COMMIT, not to the context-manager exit).
        async with _tx(engine, tid) as session_a:
            async with conversation_lease(session_a, conv_id):
                # Backend B tries to start a NEW run on the same conversation
                # while A is still in flight: the run must be refused at the
                # lease boundary, before it can post a stale/interleaved reply.
                with pytest.raises(ConversationBusy):
                    async with _tx(engine, tid) as session_b:
                        await AgentRunner().run(
                            session_b,
                            tid,
                            agent_id=agent_id,
                            conversation_id=conv_id,
                            user_message="answer the newer question",
                        )

        # A committed -> the xact lock is gone -> the deferred run is admitted.
        async with _tx(engine, tid) as session_c:
            async with conversation_lease(session_c, conv_id):
                passed = (await session_c.execute(text("SELECT 1"))).scalar_one()
        assert passed == 1, "the lease was never released after the first run committed"
    finally:
        await _cleanup(engine, tid)

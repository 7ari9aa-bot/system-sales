"""§135 gate — N simultaneous gate entries PARK exactly ONE pending approval.

The double-grant class of bug, CREATION side. ``test_gate_approval_double_
grant.py`` proves that one grant is decided once and consumed once — both
reads there are ``SELECT ... FOR UPDATE``. But the whole chain starts from
``ApprovalService.request``, which until migration ``e6f7a8b9c0d1`` deduped
PENDING rows with an UNLOCKED check-then-act: SELECT, then INSERT if none.
Two concurrent racers for one (tenant, conversation, action, payload_hash)
each saw no PENDING row and each INSERTed — two approvals for one HIGH-risk
action, and since ``decide`` locks a row (not a key), BOTH could be approved
and BOTH consumed. The DB-free twin of this file
(``tests/test_approval_pending_dedupe_index.py``) pins the index and the
service's handling of the violation; this file is the race itself.

Harness borrowed verbatim from ``test_gate_approval_double_grant.py``:
RACERS INDEPENDENT connections, real committed rows, released behind a
barrier, because the shared ``db`` fixture runs one connection in a
rolled-back transaction and cannot exercise index-level locking at all.

If ``uq_approvals_pending_dedupe`` is dropped, the first test fails with
tally["distinct-approval-ids"] > 1 — that mutation is the reason it exists.
The second test races the NULL-conversation case, which is exactly where a
naive unique index (NULLs DISTINCT) would let duplicates through while every
other test stayed green.

DB-backed as the ``sales_app`` role — skips via ``db_url`` when no
application database is configured, so CI is the venue that publishes the
verdict. Locally these are OBSERVED-AS-SKIPPED, nothing more.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.modules.ai.approvals import ApprovalService
from app.modules.ai.models import ApprovalRequest
from app.modules.conversations.models import Conversation
from app.modules.customers.models import Customer
from app.modules.identity.models import Tenant

pytestmark = [pytest.mark.gate]

RACERS = 4

ACTION = "gate.purge_customer_data"
ARGUMENTS = {"arguments": {"customer_id": "c-1", "note": "gate"}}


@pytest.fixture
async def committed_engine(db_url: str):
    engine = create_async_engine(
        db_url,
        pool_size=RACERS + 2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed_with_conversation(engine: AsyncEngine) -> dict:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    slug = uuid.uuid4().hex[:10]
    async with factory() as session, session.begin():
        tenant = Tenant(slug=f"pendup-{slug}", name="Pending Dedupe Gate")
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id
        await bind_tenant(session, tenant_id)
        customer = Customer(tenant_id=tenant_id, name="Gate Customer")
        session.add(customer)
        await session.flush()
        conversation = Conversation(
            tenant_id=tenant_id, customer_id=customer.id, channel="webchat", status="open"
        )
        session.add(conversation)
        await session.flush()
        if conversation.id is None:
            raise AssertionError("seed flush did not assign the conversation PK")
        return {"tenant_id": tenant_id, "conversation_id": conversation.id}


async def _cleanup(engine: AsyncEngine, ids: dict) -> None:
    """Best-effort removal so a shared dev database is not littered."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            await bind_tenant(session, ids["tenant_id"])
            for table in ("approval_requests", "messages", "conversations", "customers"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": ids["tenant_id"]}
                )
        async with factory() as session, session.begin():
            await session.execute(
                text("DELETE FROM tenants WHERE id = :t"), {"t": ids["tenant_id"]}
            )
    except Exception:  # noqa: BLE001 — cleanup must never mask the real assertion
        pass


async def _race_request(committed_engine: AsyncEngine, ids: dict) -> Counter:
    """Release RACERS independent connections into ApprovalService.request at
    one instant; each commits its outcome; return the tally of approval ids
    the racers were handed."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    barrier = asyncio.Barrier(RACERS)

    async def gate_entry() -> str:
        async with factory() as session:
            async with session.begin():
                await bind_tenant(session, ids["tenant_id"])
                await barrier.wait()
                approval = await ApprovalService.request(
                    session,
                    ids["tenant_id"],
                    run_id=None,
                    conversation_id=ids.get("conversation_id"),
                    entity_type="tool",
                    entity_id=ACTION,
                    action=ACTION,
                    risk_level="HIGH",
                    payload=ARGUMENTS,
                )
                return str(approval.id)

    approval_ids = await asyncio.gather(*(gate_entry() for _ in range(RACERS)))
    return Counter(approval_ids)


async def _committed_pending(committed_engine: AsyncEngine, ids: dict) -> int:
    """How many PENDING rows the race actually left behind, counted fresh."""
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await bind_tenant(session, ids["tenant_id"])
        return (
            await session.execute(
                select(func.count())
                .select_from(ApprovalRequest)
                .where(
                    ApprovalRequest.tenant_id == ids["tenant_id"],
                    ApprovalRequest.action == ACTION,
                    ApprovalRequest.status == "PENDING",
                )
            )
        ).scalar_one()


async def test_gate_concurrent_gate_entries_park_one_pending_approval(committed_engine):
    """N simultaneous parks of the SAME action: exactly one PENDING row.

    Before the index: every racer passed the unlocked pre-check, every racer
    INSERTed, and the reviewer queue got N copies of one decision — each of
    which ``decide`` would approve independently (it locks a row, not a key),
    so N executions of a HIGH-risk action were authorised by N appearances of
    one approval. After it: the loser's INSERT raises 23505 against
    uq_approvals_pending_dedupe, ``request`` rolls back to its savepoint,
    re-reads, and hands back the WINNER's row — the idempotent answer the
    pre-check always intended. So the racers return one distinct approval id
    AND the table holds one PENDING row; checking both is what distinguishes
    "handled the violation" from "the race never happened".
    """
    ids = await _seed_with_conversation(committed_engine)
    try:
        tally = await _race_request(committed_engine, ids)
        assert len(tally) == 1, (
            f"{len(tally)} concurrent gate entries produced {len(tally)} "
            f"distinct approvals for one action — duplicate-pending race is OPEN: {dict(tally)}"
        )
        assert sum(tally.values()) == RACERS
        rows = await _committed_pending(committed_engine, ids)
        assert rows == 1, f"{rows} committed PENDING rows for one dedupe key, expected 1"
    finally:
        await _cleanup(committed_engine, ids)


async def test_gate_null_conversation_race_parks_one_pending_approval(committed_engine):
    """The coalesce-bucket case: no conversation, same key, same race.

    A unique index over a bare ``conversation_id`` is silently useless here —
    NULLs are DISTINCT to Postgres, so every racer would land its own row and
    the test above (which uses a real conversation) would stay green. This is
    the negative control for the bucket expression in the index.
    """
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    slug = uuid.uuid4().hex[:10]
    async with factory() as session, session.begin():
        tenant = Tenant(slug=f"pendupn-{slug}", name="Pending Dedupe Gate (no conv)")
        session.add(tenant)
        await session.flush()
        ids = {"tenant_id": tenant.id}
    try:
        tally = await _race_request(committed_engine, ids)
        assert len(tally) == 1, (
            f"NULL-conversation racers produced {len(tally)} distinct approvals — "
            f"the coalesce bucket is not doing its job: {dict(tally)}"
        )
        rows = await _committed_pending(committed_engine, ids)
        assert rows == 1, f"{rows} committed PENDING rows for one NULL-conversation key"
    finally:
        await _cleanup(committed_engine, ids)


async def test_gate_racers_use_separate_connections(committed_engine):
    """Guard the guard: the races above are meaningless on a shared backend."""
    ids = await _seed_with_conversation(committed_engine)
    try:
        factory = async_sessionmaker(committed_engine, expire_on_commit=False)
        barrier = asyncio.Barrier(RACERS)

        async def backend_pid() -> int:
            async with factory() as session:
                async with session.begin():
                    pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                    await barrier.wait()
                    return pid

        pids = await asyncio.gather(*(backend_pid() for _ in range(RACERS)))
        assert len(set(pids)) == RACERS, f"racers shared connections: {pids}"
    finally:
        await _cleanup(committed_engine, ids)

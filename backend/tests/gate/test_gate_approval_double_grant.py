"""§135 + §15-16 gate — one parked action is decided ONCE and honoured ONCE.

The column that owns this promise documents it in the model itself
(`ai/models.py:337`): "an approval authorizes exactly ONE execution of the
action." Nothing enforced that under concurrency. Both reads on the path were
plain SELECTs followed by a separate write, i.e. check-then-act:

* ``ApprovalService.decide`` selected the row, checked ``status == PENDING`` and
  then wrote the decision (``approvals.py:107-129``). Two reviewers — or one
  reviewer with two tabs — both saw PENDING and BOTH returned 200, and
  ``decide_approval`` enqueues a ``message.received`` resume for every
  successful APPROVE (``router.py:340-352``), so the parked run was released
  twice.
* ``find_granted`` selected the unconsumed APPROVED row and ``consume`` wrote
  ``consumed_at`` afterwards (``approvals.py:165-188``), exactly as the runtime
  calls them (``runtime.py:687-711``). Two concurrent resumed runs both saw the
  same unconsumed grant and BOTH called ``spec.handler`` — which is the
  HIGH-risk action (create order, refund, purge) executed twice on one
  human decision.

``/api/v1/ai/approvals`` is deliberately not on the idempotency allow-list
(``core/idempotency.py:115-123``), so no client key deduplicated either step;
the status/consumed columns were the whole guard.

These tests open ``RACERS`` INDEPENDENT connections, commit real rows and
release the racers at the same instant behind a barrier, because the shared
``db`` fixture runs one connection in a rolled-back transaction and cannot
exercise row locking at all. If ``with_for_update()`` is removed from
``decide``'s and ``find_granted``'s SELECT, the first two tests fail (more than
one racer wins). That mutation is the reason they exist; the last test guards
the harness itself, since the race is vacuous on a shared connection.

DB-backed as the ``sales_app`` role — skips via ``db_url`` when no application
database is configured, so CI is the venue that publishes the verdict.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.errors import ValidationError
from app.core.security import hash_password
from app.modules.ai.approvals import ApprovalService, payload_fingerprint
from app.modules.ai.models import ApprovalRequest
from app.modules.conversations.models import Conversation
from app.modules.customers.models import Customer
from app.modules.identity.models import Tenant, User

pytestmark = [pytest.mark.gate]

RACERS = 4  # above one pool's default of 5 minus headroom, so all race at once

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


async def _seed(engine: AsyncEngine, *, status: str) -> dict:
    """Commit a tenant, a reviewer, a conversation and one approval row.

    Returns plain UUIDs — never ORM objects — so nothing lazy-loads on another
    connection later.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    slug = uuid.uuid4().hex[:10]
    async with factory() as session, session.begin():
        tenant = Tenant(slug=f"appr-{slug}", name="Approval Gate")
        reviewer = User(
            email=f"appr-{slug}@test.local",
            password_hash=hash_password("secret-password"),
            full_name="Reviewer",
        )
        session.add_all([tenant, reviewer])
        await session.flush()
        tenant_id, reviewer_id = tenant.id, reviewer.id
        await bind_tenant(session, tenant_id)

        customer = Customer(tenant_id=tenant_id, name="Gate Customer")
        session.add(customer)
        await session.flush()
        conversation = Conversation(
            tenant_id=tenant_id, customer_id=customer.id, channel="webchat", status="open"
        )
        approval = ApprovalRequest(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            requested_by="ai",
            entity_type="customer",
            entity_id=str(customer.id),
            action=ACTION,
            risk_level="HIGH",
            payload=ARGUMENTS,
            payload_hash=payload_fingerprint(ARGUMENTS),
            status=status,
        )
        session.add_all([conversation, approval])
        await session.flush()
        return {
            "tenant_id": tenant_id,
            "reviewer_id": reviewer_id,
            "conversation_id": conversation.id,
            "approval_id": approval.id,
        }


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
                text("DELETE FROM users WHERE id = :u"), {"u": ids["reviewer_id"]}
            )
            await session.execute(
                text("DELETE FROM tenants WHERE id = :t"), {"t": ids["tenant_id"]}
            )
    except Exception:  # noqa: BLE001 — cleanup must never mask the real assertion
        pass


async def _row(engine: AsyncEngine, ids: dict) -> tuple[str, int]:
    """The committed (status, how many rows) for the approval under test."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await bind_tenant(session, ids["tenant_id"])
        row = (
            await session.execute(
                select(func.count(), func.max(ApprovalRequest.status)).where(
                    ApprovalRequest.id == ids["approval_id"]
                )
            )
        ).one()
    return (row[1], row[0])


async def test_gate_one_pending_approval_is_decided_exactly_once(committed_engine):
    """N reviewers approve the same parked action: exactly one decision lands."""
    ids = await _seed(committed_engine, status="PENDING")
    try:
        factory = async_sessionmaker(committed_engine, expire_on_commit=False)
        barrier = asyncio.Barrier(RACERS)

        async def reviewer() -> str:
            async with factory() as session:
                async with session.begin():
                    await bind_tenant(session, ids["tenant_id"])
                    await barrier.wait()
                    try:
                        await ApprovalService.decide(
                            session,
                            ids["tenant_id"],
                            ids["approval_id"],
                            decision="APPROVED",
                            decided_by_user_id=ids["reviewer_id"],
                        )
                    except ValidationError:
                        return "refused"
                    return "granted"

        outcomes = await asyncio.gather(*(reviewer() for _ in range(RACERS)))
        tally = Counter(outcomes)

        assert tally["granted"] == 1, f"double grant: {dict(tally)}"
        assert tally["refused"] == RACERS - 1, f"unexpected outcomes: {dict(tally)}"
        status, rows = await _row(committed_engine, ids)
        assert (status, rows) == ("APPROVED", 1)
    finally:
        await _cleanup(committed_engine, ids)


async def test_gate_one_grant_authorizes_exactly_one_execution(committed_engine):
    """The resume path itself: N concurrent runs claiming one APPROVED grant.

    This is ``runtime.py:687-711`` verbatim — ``find_granted`` then ``consume``
    then the handler — driven from ``RACERS`` connections at the same instant.
    The handler stands in for a refund or a purge, so the count that matters is
    how many racers reached it.
    """
    ids = await _seed(committed_engine, status="APPROVED")
    try:
        factory = async_sessionmaker(committed_engine, expire_on_commit=False)
        barrier = asyncio.Barrier(RACERS)

        async def resumed_run() -> str:
            async with factory() as session:
                async with session.begin():
                    await bind_tenant(session, ids["tenant_id"])
                    await barrier.wait()
                    granted = await ApprovalService.find_granted(
                        session,
                        ids["tenant_id"],
                        conversation_id=ids["conversation_id"],
                        action=ACTION,
                        payload=ARGUMENTS,
                    )
                    if granted is None:
                        return "parks-again"
                    await ApprovalService.consume(session, granted)
                    return "executes-handler"

        outcomes = await asyncio.gather(*(resumed_run() for _ in range(RACERS)))
        tally = Counter(outcomes)

        assert tally["executes-handler"] == 1, f"the HIGH-risk action ran {tally} times"
        assert tally["parks-again"] == RACERS - 1, f"unexpected outcomes: {dict(tally)}"
    finally:
        await _cleanup(committed_engine, ids)


async def test_gate_racers_use_separate_connections(committed_engine):
    """Guard the guard: the two races above are meaningless on one backend."""
    ids = await _seed(committed_engine, status="PENDING")
    try:
        factory = async_sessionmaker(committed_engine, expire_on_commit=False)
        barrier = asyncio.Barrier(RACERS)

        async def backend_pid() -> int:
            async with factory() as session:
                async with session.begin():
                    pid = (
                        await session.execute(text("SELECT pg_backend_pid()"))
                    ).scalar_one()
                    await barrier.wait()
                    return pid

        pids = await asyncio.gather(*(backend_pid() for _ in range(RACERS)))
        assert len(set(pids)) == RACERS, f"racers shared connections: {pids}"
    finally:
        await _cleanup(committed_engine, ids)

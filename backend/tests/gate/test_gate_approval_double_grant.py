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

        # PRIMARY KEYs are assigned at flush time, so the conversation MUST be
        # flushed before its id is read. Run 35959902953 constructed the
        # approval with ``conversation_id=conversation.id`` while the
        # conversation was still un-flushed — the seeded grant carried
        # conversation_id NULL, `find_granted` matched nothing, and the race
        # collapsed to four "parks-again" without ever touching the lock.
        customer = Customer(tenant_id=tenant_id, name="Gate Customer")
        session.add(customer)
        await session.flush()
        conversation = Conversation(
            tenant_id=tenant_id, customer_id=customer.id, channel="webchat", status="open"
        )
        session.add(conversation)
        await session.flush()
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
        session.add(approval)
        await session.flush()
        if conversation.id is None or approval.id is None:
            raise AssertionError("seed flush did not assign primary keys")
        # A grant the resume path cannot even find makes every race below
        # vacuously "green" in the wrong direction — pin it at the source.
        if status == "APPROVED" and approval.conversation_id != conversation.id:
            raise AssertionError("APPROVED grant was not bound to the conversation")
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

        # Claimability probe: if a future seed regression hides the grant from
        # the resume path, fail HERE as a harness bug. Without it the race
        # "passes the invariant" by nobody ever finding the row (run
        # 35959902953: 4 x parks-again, 0 executions — a mis-seed, not a
        # double grant), or fails with a message that reads like one.
        async with factory() as session, session.begin():
            await bind_tenant(session, ids["tenant_id"])
            probe = await ApprovalService.find_granted(
                session,
                ids["tenant_id"],
                conversation_id=ids["conversation_id"],
                action=ACTION,
                payload=ARGUMENTS,
            )
        assert probe is not None, (
            "seeded APPROVED grant is not claimable by find_granted — harness "
            "seeding bug; the race below would prove nothing"
        )

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

        assert tally["executes-handler"] == 1, (
            f"one APPROVED grant authorized {tally['executes-handler']} "
            f"executions (expected exactly 1); outcomes: {dict(tally)}"
            + (
                " — DOUBLE GRANT"
                if tally["executes-handler"] > 1
                else " — grant never claimed by any racer (probe above should have caught this)"
            )
        )
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


# --------------------------------------------------------------------------
# DB-free shape pins. The real concurrency proof is CI-only (these gate tests
# skip without a database), but the double-grant class of bug is dead if and
# only if the claim SELECT holds a row lock and its predicates re-check the
# grant state. That SHAPE is assertable without a DB — pin it here so
# removing `.with_for_update()` or a predicate is caught on any runner, not
# just the gate CI job. Idiom borrowed from tests/test_ai_usage_totals.py:
# a stub session that records the statement instead of running it.
# --------------------------------------------------------------------------


class _ShapeResult:
    def __init__(self, row=None):  # noqa: ANN001
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _RecordingSession:
    def __init__(self, row=None):  # noqa: ANN001
        self.statements = []
        self._row = row

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.statements.append(statement)
        return _ShapeResult(self._row)

    def add(self, obj):  # noqa: ANN001
        pass

    async def flush(self):
        pass


def _pg_sql(statement) -> str:  # noqa: ANN001
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect())).upper()


async def test_find_granted_claim_select_locks_and_rechecks_grant_state():
    """The consumption decision must be made UNDER a row lock on the grant state."""
    session = _RecordingSession()
    granted = await ApprovalService.find_granted(
        session,
        uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        action=ACTION,
        payload=ARGUMENTS,
    )
    assert granted is None
    assert session.statements, "find_granted never consulted the database"
    sql = _pg_sql(session.statements[-1])
    # FOR UPDATE is what serialises two racers for one grant: the loser blocks
    # and Postgres re-evaluates these predicates against the winner's new row
    # version, so the SAME predicates that found the grant are what refuse it.
    assert "FOR UPDATE" in sql, sql
    assert "CONSUMED_AT IS NULL" in sql, sql
    assert "STATUS" in sql, sql
    assert "PAYLOAD_HASH" in sql, sql


async def test_decide_select_locks_and_rechecks_pending_state():
    """Same shape on the decision side: lock first, then read the status."""
    from app.core.errors import NotFoundError

    session = _RecordingSession()
    with pytest.raises(NotFoundError):
        await ApprovalService.decide(
            session,
            uuid.uuid4(),
            uuid.uuid4(),
            decision="APPROVED",
            decided_by_user_id=uuid.uuid4(),
        )
    sql = _pg_sql(session.statements[-1])
    assert "FOR UPDATE" in sql, sql

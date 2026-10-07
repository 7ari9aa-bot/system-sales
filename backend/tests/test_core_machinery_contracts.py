"""Package 10.3 — the machinery contracts that had no direct coverage yet.

Each contract here was verified against the code first; this file only pins
what no existing test exercised:

* ``lease`` — two contenders on ONE conversation: the winner holds, the loser
  is refused 409 (fast and bounded-wait), and the error path releases the
  lock, because the lease is transaction-scoped. Nothing anywhere tested the
  advisory-lock contract.
* ``saga`` — a compensation handler that ITSELF fails is logged and recorded
  (``compensation_error``) without being swallowed, the saga still ends
  FAILED, and the original step failure still propagates. The reverse order
  of compensation over more than two completed steps is pinned here too
  (test_return_saga.py pins the two-step case through the real process).
* ``field_auth`` — fail-closed redaction: an empty permission set redacts,
  secret fields redact even with every permission, and custom sets redact
  unconditionally.
* ``transitions`` — hostile input (None, wrong types, unknown states, empty
  table) can never smuggle a transition through the guard.
* ``pagination`` — the cursor resumes with no duplicate and no skipped row,
  and a cursor behind every row is an empty page, not a 500.
* ``search`` — the Postgres adapter never crosses the tenant boundary: same
  names in two tenants return only the caller's rows, and asking for another
  tenant's id fails closed.

The fingerprint/TTL half of idempotency is already pinned DB-backed in
test_request_integrity.py (same-key replay, different-body conflict,
expired-key reclaim, purge_expired) and is not duplicated here.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.errors import ConflictError
from app.core.field_auth import redact_fields
from app.core.lease import ConversationBusy, conversation_lease
from app.core.pagination import decode_cursor, encode_cursor, paginate
from app.core.saga import Saga, SagaManager, SagaStatus, SagaStepHandler
from app.core.search import PostgresSearch
from app.core.transitions import allowed, require_transition


# ---------------------------------------------------------------------------
# lease — the advisory lock is actually read, contended and released
# ---------------------------------------------------------------------------


def _engine(url: str):
    return create_async_engine(url, connect_args={"statement_cache_size": 0})


def _factory(conn) -> async_sessionmaker:
    return async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


async def test_a_second_contender_on_the_same_conversation_is_refused_409(db_url) -> None:
    """Two processors race for one conversation: exactly one holds the lease.

    The loser's fail-fast attempt reads the try-lock's False and gets the 409
    (ConversationBusy), and its blocking attempt is bounded — it gives up in
    bounded time instead of hanging behind the holder forever.
    """
    conversation_id = uuid.uuid4()
    holder_engine = _engine(db_url)
    loser_engine = _engine(db_url)
    try:
        async with holder_engine.connect() as holder_conn:
            holder_tx = await holder_conn.begin()
            async with _factory(holder_conn)() as holder:
                async with conversation_lease(holder, conversation_id):
                    async with loser_engine.connect() as loser_conn:
                        loser_tx = await loser_conn.begin()
                        async with _factory(loser_conn)() as loser:
                            # FAIL FAST: the try-lock result is actually read.
                            with pytest.raises(ConversationBusy) as busy:
                                async with conversation_lease(loser, conversation_id):
                                    pass  # pragma: no cover — never entered
                            assert busy.value.http_status == 409
                            # BOUNDED WAIT: expires instead of hanging forever.
                            started = time.monotonic()
                            with pytest.raises(ConversationBusy):
                                async with conversation_lease(
                                    loser, conversation_id, wait=True, wait_seconds=0.15
                                ):
                                    pass  # pragma: no cover — never entered
                            assert time.monotonic() - started < 5.0
                        await loser_tx.rollback()
            # The holder exits the block; the xact lock is still held until
            # its transaction ends — the release happens at the boundary.
            await holder_tx.rollback()

        # The lease is free again: a fresh contender acquires immediately.
        async with loser_engine.connect() as conn:
            tx = await conn.begin()
            async with _factory(conn)() as session:
                async with conversation_lease(session, conversation_id):
                    pass
            await tx.rollback()
    finally:
        await holder_engine.dispose()
        await loser_engine.dispose()


async def test_an_error_inside_the_lease_releases_the_lock_on_rollback(db_url) -> None:
    """The error path IS the release path.

    The lease is transaction-scoped, so a crash inside the leased block cannot
    orphan the lock: the holder's rollback frees it and the next contender
    acquires immediately. (Before this was fixed to read the try-lock result,
    a refused contender looked successful — the regression test for the 409
    is the contention test above; this one proves no lock is left behind.)
    """
    conversation_id = uuid.uuid4()
    holder_engine = _engine(db_url)
    contender_engine = _engine(db_url)
    try:
        async with holder_engine.connect() as holder_conn:
            holder_tx = await holder_conn.begin()
            with pytest.raises(RuntimeError, match="mutating work blew up"):
                async with _factory(holder_conn)() as session:
                    async with conversation_lease(session, conversation_id):
                        raise RuntimeError("mutating work blew up")
            await holder_tx.rollback()

        async with contender_engine.connect() as conn:
            tx = await conn.begin()
            async with _factory(conn)() as session:
                async with conversation_lease(session, conversation_id):
                    pass  # acquired: nothing was left behind by the failure
            await tx.rollback()
    finally:
        await holder_engine.dispose()
        await contender_engine.dispose()


# ---------------------------------------------------------------------------
# saga — failing compensation is logged and recorded, never swallowed
# ---------------------------------------------------------------------------


class _CountingStep(SagaStepHandler):
    """Appends to a shared log so tests can read the order the engine acted in."""

    def __init__(self, label: str, log: list[str], *, fail: bool = False) -> None:
        self.label = label
        self.log = log
        self.fail = fail

    async def execute(self, session, tenant_id, saga, context) -> dict:
        self.log.append(f"run:{self.label}")
        if self.fail:
            raise RuntimeError(f"{self.label} refused")
        return {self.label: "done"}

    async def compensate(self, session, tenant_id, saga, context) -> dict:
        self.log.append(f"undo:{self.label}")
        return {self.label: "undone"}


class _UncompensatableStep(SagaStepHandler):
    """A forward action that succeeds but whose undo itself breaks."""

    async def execute(self, session, tenant_id, saga, context) -> dict:
        return {"primed": "done"}

    async def compensate(self, session, tenant_id, saga, context) -> dict:
        raise RuntimeError("undo itself broke")


async def _reload(db: AsyncSession, saga_id: uuid.UUID) -> Saga:
    """Re-read the saga row from the DB, past the identity map."""
    db.expire_all()
    return (await db.execute(select(Saga).where(Saga.id == saga_id))).scalar_one()


async def test_a_failing_compensation_is_logged_and_recorded_not_swallowed(
    db: AsyncSession, tenant_ctx, caplog
) -> None:
    """The undo of an undo breaking must not silently lose the fact.

    The engine records the failed compensation on the step result (with the
    error text), logs it at ERROR, still marks the saga FAILED, and the
    original step failure still propagates to the caller — nothing is eaten.
    """
    tenant_id = tenant_ctx.tenant_id
    saga_type = "test_bad_compensation"
    log: list[str] = []
    SagaManager._handlers[(saga_type, 0)] = _UncompensatableStep()
    SagaManager._handlers[(saga_type, 1)] = _CountingStep("close", log, fail=True)
    try:
        saga = await SagaManager.create_saga(
            db,
            tenant_id,
            saga_type=saga_type,
            aggregate_type="order",
            aggregate_id=uuid.uuid4(),
        )
        await SagaManager.execute_next(db, tenant_id, saga.id)
        with caplog.at_level(logging.ERROR, logger="app.core.saga"):
            with pytest.raises(RuntimeError, match="close refused"):
                await SagaManager.execute_next(db, tenant_id, saga.id)
    finally:
        SagaManager._handlers.pop((saga_type, 0), None)
        SagaManager._handlers.pop((saga_type, 1), None)

    fresh = await _reload(db, saga.id)
    assert fresh.status == SagaStatus.FAILED.value, (
        "a broken compensation must not let the saga look recoverable-clean"
    )
    assert [r["status"] for r in fresh.step_results] == ["failed", "failed"]
    assert "undo itself broke" in fresh.step_results[0]["compensation_error"]
    assert fresh.last_error == "close refused"
    assert any("compensation failed" in record.getMessage() for record in caplog.records), (
        "the compensation failure must reach the logs"
    )


async def test_compensation_over_several_steps_runs_in_reverse_order(
    db: AsyncSession, tenant_ctx, saga_registry
) -> None:
    """Undo order is the reverse of execution order, for any number of steps.

    test_return_saga.py pins the two-step case through the real process; this
    pins the engine's own loop over three completed steps.
    """
    tenant_id = tenant_ctx.tenant_id
    log: list[str] = []
    saga_registry(
        "test_reverse",
        [
            _CountingStep("restock", log),
            _CountingStep("close", log),
            _CountingStep("ship", log, fail=True),
        ],
    )
    saga = await SagaManager.create_saga(
        db,
        tenant_id,
        saga_type="test_reverse",
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
    )
    await SagaManager.execute_next(db, tenant_id, saga.id)
    await SagaManager.execute_next(db, tenant_id, saga.id)
    with pytest.raises(RuntimeError, match="ship refused"):
        await SagaManager.execute_next(db, tenant_id, saga.id)

    assert log == [
        "run:restock",
        "run:close",
        "run:ship",
        "undo:close",
        "undo:restock",
    ]
    fresh = await _reload(db, saga.id)
    assert fresh.status == SagaStatus.FAILED.value
    assert [r["status"] for r in fresh.step_results] == [
        "compensated",
        "compensated",
        "failed",
    ]


@pytest.fixture
def saga_registry():
    """Register handlers on a throw-away saga type, and unregister afterwards.

    `SagaManager._handlers` is process-global: entries left behind would leak
    their steps into every later run of the engine.
    """
    registered: list[tuple[str, int]] = []

    def _register(saga_type: str, steps: list[SagaStepHandler]) -> str:
        for index, step in enumerate(steps):
            SagaManager._handlers[(saga_type, index)] = step
            registered.append((saga_type, index))
        return saga_type

    yield _register
    for key in registered:
        SagaManager._handlers.pop(key, None)


# ---------------------------------------------------------------------------
# field_auth — redaction fails closed
# ---------------------------------------------------------------------------


def test_an_empty_permission_set_redacts_everything_sensitive() -> None:
    data = {"phone": "010", "email": "a@b", "supplier_cost": "9", "profit": "1"}
    out = redact_fields(data, permission_codes=set())
    assert out == {"phone": None, "email": None, "supplier_cost": None, "profit": None}


def test_secret_fields_redact_even_with_every_permission() -> None:
    """Secrets are ALWAYS redacted — no permission code buys them back."""
    data = {"password_hash": "h", "api_key": "sk-x", "access_token": "t", "name": "ok"}
    out = redact_fields(
        data, permission_codes={"pii:read", "internal:read", "admin:all"}
    )
    assert out["password_hash"] is None
    assert out["api_key"] is None
    assert out["access_token"] is None
    assert out["name"] == "ok"


def test_the_right_permissions_keep_pii_and_internal_fields() -> None:
    data = {"phone": "010", "supplier_cost": "9"}
    out = redact_fields(data, permission_codes={"pii:read", "internal:read"})
    assert out["phone"] == "010"
    assert out["supplier_cost"] == "9"


def test_a_custom_redaction_set_redacts_unconditionally() -> None:
    data = {"note": "internal only", "phone": "010"}
    out = redact_fields(
        data,
        permission_codes={"pii:read", "internal:read"},
        fields_to_redact=frozenset({"note"}),
    )
    assert out["note"] is None, "an explicit set is a blocklist, not a permission gate"


def test_redaction_returns_a_copy_and_never_mutates_the_input() -> None:
    data = {"phone": "010"}
    out = redact_fields(data, permission_codes=set())
    assert out is not data
    assert data["phone"] == "010"


# ---------------------------------------------------------------------------
# transitions — hostile input cannot smuggle a move through the guard
# ---------------------------------------------------------------------------

_TABLE: dict[str, set[str]] = {"draft": {"active"}, "active": {"suspended"}}


def test_none_as_current_or_target_is_rejected() -> None:
    with pytest.raises(ConflictError):
        require_transition(_TABLE, None, "active")
    with pytest.raises(ConflictError):
        require_transition(_TABLE, "draft", None)


def test_wrong_types_as_current_or_target_are_rejected() -> None:
    with pytest.raises(ConflictError):
        require_transition(_TABLE, "draft", 123)
    with pytest.raises(ConflictError):
        require_transition(_TABLE, "draft", ["active"])
    with pytest.raises(ConflictError):
        require_transition(_TABLE, {"draft": "active"}, "active")
    with pytest.raises(ConflictError):
        require_transition(_TABLE, object(), "active")  # type: ignore[arg-type]


def test_an_unknown_current_state_and_an_empty_table_fail_closed() -> None:
    with pytest.raises(ConflictError):
        require_transition(_TABLE, "void", "active")
    with pytest.raises(ConflictError):
        require_transition({}, "draft", "active")


def test_a_legal_move_returns_the_target_and_allowed_lists_the_reach() -> None:
    assert require_transition(_TABLE, "draft", "active") == "active"
    assert allowed(_TABLE, "draft") == {"active"}
    assert allowed({}, "draft") == set()


# ---------------------------------------------------------------------------
# pagination — exact resume, and a dead cursor is an empty page
# ---------------------------------------------------------------------------


async def test_keyset_pagination_resumes_without_duplicates_or_skips(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.customers.models import Customer

    suffix = uuid.uuid4().hex[:8]
    db.add_all(
        [
            Customer(tenant_id=tenant_ctx.tenant_id, name=f"page-{suffix}-{i}")
            for i in range(5)
        ]
    )
    await db.flush()

    stmt = select(Customer).where(Customer.tenant_id == tenant_ctx.tenant_id)
    page1, cursor1 = await paginate(db, stmt, limit=2)
    page2, cursor2 = await paginate(db, stmt, cursor=cursor1, limit=2)
    page3, cursor3 = await paginate(db, stmt, cursor=cursor2, limit=2)

    assert len(page1) == len(page2) == 2 and len(page3) == 1
    assert cursor3 is None, "the list is exhausted exactly when the cursor stops"
    ids = [row.id for row in (*page1, *page2, *page3)]
    assert len(set(ids)) == 5, "a resumed keyset must never duplicate or skip a row"


async def test_a_cursor_behind_every_row_is_an_empty_page_not_an_error(
    db: AsyncSession, tenant_ctx
) -> None:
    """A cursor that points before the whole list (or outlives its rows) ends
    the list cleanly — the client gets a page and no next cursor, never a 500
    from a dangling position."""
    from app.modules.customers.models import Customer

    db.add(Customer(tenant_id=tenant_ctx.tenant_id, name=f"tail-{uuid.uuid4().hex[:8]}"))
    await db.flush()

    stmt = select(Customer).where(Customer.tenant_id == tenant_ctx.tenant_id)
    dead_cursor = encode_cursor(datetime(2000, 1, 1, tzinfo=UTC), uuid.uuid4())
    rows, next_cursor = await paginate(db, stmt, cursor=dead_cursor, limit=2)

    assert rows == []
    assert next_cursor is None


def test_a_malformed_cursor_is_a_client_error_with_a_code() -> None:
    from app.core.errors import InvalidCursorError

    with pytest.raises(InvalidCursorError) as exc_info:
        decode_cursor("%%%not-base64%%%")
    assert exc_info.value.code == "invalid_cursor"


# ---------------------------------------------------------------------------
# search — the tenant boundary holds from both sides
# ---------------------------------------------------------------------------


async def test_search_never_crosses_the_tenant_boundary(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.catalog.models import Product
    from app.modules.customers.models import Customer
    from app.modules.identity.models import Tenant

    suffix = uuid.uuid4().hex[:8]
    mine = Customer(
        tenant_id=tenant_ctx.tenant_id,
        name=f"Shared {suffix}",
        email=f"shared-{suffix}@mine.test",
    )
    my_product = Product(
        tenant_id=tenant_ctx.tenant_id,
        title=f"Shared Widget {suffix}",
        slug=f"shared-{suffix}",
        status="active",
    )
    db.add_all([mine, my_product])

    # A second real tenant (customers.tenant_id is FK'd to tenants) holding
    # rows with the SAME names — a boundary test needs a genuine lookalike.
    other_tenant = Tenant(slug=f"t-{suffix}", name="Other Tenant")
    db.add(other_tenant)
    await db.flush()
    await bind_tenant(db, other_tenant.id)
    theirs = Customer(
        tenant_id=other_tenant.id,
        name=f"Shared {suffix}",
        email=f"shared-{suffix}@theirs.test",
    )
    their_product = Product(
        tenant_id=other_tenant.id,
        title=f"Shared Widget {suffix}",
        slug=f"shared-{suffix}-b",
        status="active",
    )
    db.add_all([theirs, their_product])
    await db.flush()
    await bind_tenant(db, tenant_ctx.tenant_id)

    search = PostgresSearch()

    own = await search.search(db, tenant_ctx.tenant_id, f"Shared {suffix}")
    assert {hit.entity_id for hit in own} == {mine.id, my_product.id}, (
        "identical names in another tenant must not leak into our hits"
    )

    own_customers = await search.search(
        db, tenant_ctx.tenant_id, f"Shared {suffix}", entity_types=["customer"]
    )
    assert [hit.entity_id for hit in own_customers] == [mine.id]

    # Asking for the OTHER tenant's id while bound to ours: the explicit
    # tenant filter and the RLS GUC disagree, and the result is zero rows —
    # a caller can never read across by passing a foreign tenant id.
    cross = await search.search(db, other_tenant.id, f"Shared {suffix}")
    assert cross == []

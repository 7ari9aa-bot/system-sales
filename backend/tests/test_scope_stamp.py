"""§151 Q4 — ownership scope at the mutation sites.

Q1–Q3 built the machinery: FORCE RLS on the hierarchy tables, the
app.workspace_id/app.location_id GUCs, fail-closed scope resolution in
get_tenant_ctx, and the admin API. Q4 is the step that makes the hierarchy
REAL for data: every mutation that resolves a scope must stamp it — onto the
row (WorkspaceScopeMixin columns) and onto the event envelope
(add_outbox_event meta) — without each service call site having to thread
two more ids by hand.

The mechanism under test:
* app.core.tenancy.current_scope()/set_current_scope() — the request-scoped
  sibling of current_tenant()/set_current_tenant(); get_tenant_ctx populates
  it after resolve_scope() has validated the scope fail-closed.
* WorkspaceScopeMixin column defaults read that context, so an INSERT inside
  a scoped request carries the scope automatically; with no scope bound the
  columns stay NULL (= tenant-wide, the pre-§151 semantics).
* add_outbox_event fills workspace_id/location_id from the same context when
  the caller does not pass them — exactly like the correlation_id auto-fill.

DB-free cases pin the helpers and the writer; the DB cases prove the real
INSERT lands the scope (CI only).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.core.events.writer import add_outbox_event
from app.core.tenancy import (
    current_scope,
    reset_current_scope,
    set_current_scope,
)


def _magic_session() -> MagicMock:
    session = MagicMock()
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# 1. The scope context (sibling of the tenant context)
# ---------------------------------------------------------------------------


def test_scope_context_defaults_to_unscoped() -> None:
    assert current_scope() == (None, None)


def test_set_and_reset_scope_round_trip() -> None:
    ws, loc = uuid.uuid4(), uuid.uuid4()
    token = set_current_scope(ws, loc)
    try:
        assert current_scope() == (ws, loc)
    finally:
        reset_current_scope(token)
    assert current_scope() == (None, None)


def test_scope_accepts_workspace_only() -> None:
    ws = uuid.uuid4()
    token = set_current_scope(ws, None)
    try:
        assert current_scope() == (ws, None)
    finally:
        reset_current_scope(token)


# ---------------------------------------------------------------------------
# 2. WorkspaceScopeMixin columns default from the scope context
# ---------------------------------------------------------------------------


def test_scope_columns_default_from_context() -> None:
    """The mapped columns must pull their INSERT default from current_scope."""
    from app.modules.orders.models import Order

    ws, loc = uuid.uuid4(), uuid.uuid4()
    token = set_current_scope(ws, loc)
    try:
        # SQLAlchemy wraps a 0-arg callable default into arg(ctx) — same as the
        # id column's uuid default.
        assert Order.__table__.c.workspace_id.default.arg(None) == ws
        assert Order.__table__.c.location_id.default.arg(None) == loc
    finally:
        reset_current_scope(token)
    assert Order.__table__.c.workspace_id.default.arg(None) is None


# ---------------------------------------------------------------------------
# 3. The envelope writer auto-fills scope like correlation_id
# ---------------------------------------------------------------------------


async def test_writer_autofills_scope_from_context() -> None:
    ws, loc = uuid.uuid4(), uuid.uuid4()
    token = set_current_scope(ws, loc)
    try:
        row = await add_outbox_event(
            _magic_session(),
            aggregate_type="order",
            aggregate_id=uuid.uuid4(),
            event_type="order.created",
            tenant_id=uuid.uuid4(),
        )
    finally:
        reset_current_scope(token)
    assert row.meta["workspace_id"] == str(ws)
    assert row.meta["location_id"] == str(loc)


async def test_explicit_scope_args_beat_the_context() -> None:
    ctx_ws = uuid.uuid4()
    explicit = uuid.uuid4()
    token = set_current_scope(ctx_ws, None)
    try:
        row = await add_outbox_event(
            _magic_session(),
            aggregate_type="order",
            aggregate_id=uuid.uuid4(),
            event_type="order.created",
            tenant_id=uuid.uuid4(),
            workspace_id=explicit,
        )
    finally:
        reset_current_scope(token)
    assert row.meta["workspace_id"] == str(explicit)
    assert row.meta["location_id"] is None


async def test_unscoped_writer_leaves_scope_keys_none() -> None:
    """A worker outside any request must not inherit a stale scope."""
    row = await add_outbox_event(
        _magic_session(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=uuid.uuid4(),
    )
    assert row.meta["workspace_id"] is None
    assert row.meta["location_id"] is None


# ---------------------------------------------------------------------------
# 4. DB (CI): the INSERT lands the scope, and unscoped stays NULL
# ---------------------------------------------------------------------------


async def _make_hierarchy(db, tenant_id):
    from app.modules.identity.models import Location, Workspace

    ws = Workspace(
        tenant_id=tenant_id,
        name=f"Q4 WS {uuid.uuid4().hex[:6]}",
        slug=f"q4-ws-{uuid.uuid4().hex[:8]}",
    )
    db.add(ws)
    await db.flush()
    loc = Location(tenant_id=tenant_id, workspace_id=ws.id, name="Q4 Loc")
    db.add(loc)
    await db.flush()
    return ws, loc


async def test_scoped_insert_stamps_the_row(db, tenant_ctx) -> None:
    from app.modules.conversations.models import Conversation
    from app.modules.customers.models import Customer

    ws, loc = await _make_hierarchy(db, tenant_ctx.tenant_id)
    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Q4")
    db.add(customer)
    await db.flush()

    token = set_current_scope(ws.id, loc.id)
    try:
        convo = Conversation(
            tenant_id=tenant_ctx.tenant_id,
            customer_id=customer.id,
            channel="webchat",
        )
        db.add(convo)
        await db.flush()
    finally:
        reset_current_scope(token)

    assert convo.workspace_id == ws.id
    assert convo.location_id == loc.id
    # Outside the scope, the same INSERT stays tenant-wide (NULL) — the
    # pre-§151 semantics must not break for unscoped writers.
    plain = Conversation(
        tenant_id=tenant_ctx.tenant_id,
        customer_id=customer.id,
        channel="whatsapp",
    )
    db.add(plain)
    await db.flush()
    assert plain.workspace_id is None
    assert plain.location_id is None


async def test_operations_task_carries_the_scope_columns(db, tenant_ctx) -> None:
    """Q4 concretization: operations entities join the hierarchy — the
    columns must exist and stamp like every other WorkspaceScopeMixin row."""
    from app.modules.operations.models import Task

    ws, loc = await _make_hierarchy(db, tenant_ctx.tenant_id)
    token = set_current_scope(ws.id, loc.id)
    try:
        task = Task(
            tenant_id=tenant_ctx.tenant_id,
            title="Q4 task",
        )
        db.add(task)
        await db.flush()
    finally:
        reset_current_scope(token)
    assert task.workspace_id == ws.id
    assert task.location_id == loc.id

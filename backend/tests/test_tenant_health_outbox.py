"""§160 tenant health must count THIS tenant's outbox depth — and reach the DB.

``outbox_events`` is a system table: it has no ``tenant_id`` column, because
the §19 envelope carries tenancy inside ``meta`` instead (``writer.py`` always
writes ``meta["tenant_id"]``; the relay refuses a row without it). A filter
that names ``OutboxEvent.tenant_id`` therefore never becomes SQL at all — the
attribute does not exist, so building the statement raises ``AttributeError``
inside the request, and the one route that reports per-tenant backlog answers
500 for every tenant.

These tests drive the route function itself, in-process, with a session that
compiles each statement and refuses any column the model does not have. That
refusal is the same judgement Postgres makes; without it the test would pass
on a statement that could never execute.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.platform.models import OutboxEvent

HEALTH_TENANT = uuid.UUID("5550e40c-1111-2222-3333-444444444444")
OTHER_TENANT = uuid.UUID("5550e40c-9999-2222-3333-444444444444")
PENDING_DEPTH = 7


class _UnknownColumn(Exception):
    """The 42703 a real session would raise."""


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value


class _RecordingSession:
    """Compiles every statement, rejects columns `outbox_events` does not have."""

    def __init__(self, tenant: Any) -> None:
        self._tenant = tenant
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _Result:
        compiled = statement.compile()
        sql = str(compiled)
        self.statements.append((sql, dict(compiled.params)))
        if "outbox_events" in sql:
            unknown = [
                name
                for name in _outbox_column_refs(sql)
                if name not in OutboxEvent.__table__.columns.keys()
            ]
            if unknown:
                raise _UnknownColumn(
                    f'column "{unknown[0]}" does not exist (42703) — '
                    f"`outbox_events` has {sorted(OutboxEvent.__table__.columns.keys())}. "
                    f"SQL: {sql}"
                )
            return _Result(PENDING_DEPTH)
        return _Result(self._tenant)


def _outbox_column_refs(sql: str) -> list[str]:
    """Every `outbox_events.<name>` the compiled statement names."""
    prefix = "outbox_events."
    refs = []
    for chunk in sql.split(prefix)[1:]:
        name = ""
        for char in chunk:
            if char.isalnum() or char == "_":
                name += char
            else:
                break
        if name:
            refs.append(name)
    return refs


def _tenant_row() -> Any:
    from app.modules.identity.models import Tenant

    return Tenant(
        id=HEALTH_TENANT,
        name="Northwind Trading",
        lifecycle_state="active",
        is_active=True,
        status_reason=None,
        created_at=None,
    )


def _admin_ctx(session: Any) -> Any:
    from app.modules.identity.deps import AuthedUser, TenantContext

    user = AuthedUser(
        id=uuid.uuid4(),
        tenant_id=HEALTH_TENANT,
        role_code="owner",
        is_platform_admin=True,
    )
    return TenantContext(
        session=session,
        user=user,
        tenant_id=HEALTH_TENANT,
        role_code="owner",
        permission_codes=set(),
    )


async def _health() -> tuple[dict, _RecordingSession]:
    from app.modules.platform.router import admin_get_tenant

    session = _RecordingSession(_tenant_row())
    payload = await admin_get_tenant(_admin_ctx(session), HEALTH_TENANT)
    return payload, session


def test_the_outbox_has_no_tenant_column_to_filter_on() -> None:
    """Tripwire: if a migration ever adds `outbox_events.tenant_id`, the meta
    predicate below stops being the only option and this file must be re-read."""
    assert "tenant_id" not in OutboxEvent.__table__.columns.keys()


async def test_tenant_health_reaches_the_database_instead_of_raising() -> None:
    """The route's own body is the thing that broke — no HTTP layer hides it."""
    payload, session = await _health()

    assert payload["id"] == str(HEALTH_TENANT)
    assert payload["health"]["outbox_pending"] == PENDING_DEPTH
    assert any("outbox_events" in sql for sql, _ in session.statements), (
        "the health block answered without ever asking the outbox"
    )


async def test_tenant_health_scopes_the_backlog_through_the_event_envelope() -> None:
    """Per-tenant depth, from the key the table actually has.

    A count with no tenant predicate is the wrong number for every tenant in a
    shared table, and it is the tempting 'fix' for the AttributeError — so the
    assertion is that this tenant's id is bound, not merely that the query ran.
    """
    _payload, session = await _health()

    outbox_sql, outbox_params = next(
        (sql, params) for sql, params in session.statements if "outbox_events" in sql
    )
    assert str(HEALTH_TENANT) in outbox_params.values(), (
        f"the backlog count is not bound to the tenant: {outbox_sql}"
    )
    assert "pending" in str(outbox_params.values()), (
        f"the backlog count does not filter on status: {outbox_sql}"
    )
    assert str(OTHER_TENANT) not in outbox_params.values()


async def test_the_tenant_read_and_the_health_read_are_different_statements() -> None:
    """Guards the shape a reviewer guesses at: one statement cannot serve both."""
    _payload, session = await _health()

    assert len(session.statements) == 2, [sql for sql, _ in session.statements]
    assert "tenants" in session.statements[0][0]

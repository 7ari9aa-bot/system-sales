"""tenant_scope nesting: the outer tenant binding must survive the inner block.

Audit finding: ``tenant_scope`` used to end with ``reset_current_tenant()`` —
flattening the ContextVar to None instead of restoring whatever the OUTER block
had bound. An inner scope (a nested service call, a sub-routine that binds its
own tenant) therefore punched a hole through the request's binding: after the
inner block exited, RLS-bound queries of the outer block failed closed (loud,
at least), but any outer code that only READS the tenant — event envelopes,
audit rows, outbound attribution — silently lost it.

The fix (app/core/tenancy.tenant_scope) saves the previous value with a
ContextVar ``set`` token and restores it in ``finally``. These tests pin that
behaviour without a database: ``bind_tenant`` only needs a session object with
an ``execute`` awaitable, so a stub records the RLS binding while the context
transitions are exercised for real.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.tenancy import (
    current_tenant,
    reset_current_tenant,
    set_current_tenant,
    tenant_scope,
    try_current_tenant,
)


class _StubSession:
    """The sliver of AsyncSession bind_tenant touches: async execute()."""

    def __init__(self) -> None:
        self.bound: list[str] = []

    async def execute(self, _stmt: Any, params: dict[str, Any] | None = None) -> None:
        if params and "tenant_id" in params:
            self.bound.append(str(params["tenant_id"]))


@pytest.fixture(autouse=True)
def _clean_context():
    yield
    reset_current_tenant()


async def test_an_inner_scope_restores_the_outer_tenant_on_exit() -> None:
    outer, inner = uuid.uuid4(), uuid.uuid4()
    session = _StubSession()
    set_current_tenant(outer)

    async with tenant_scope(session, inner):
        assert current_tenant() == inner

    # The old behaviour flattened to None here — the outer block's remaining
    # code ran tenant-less.
    assert try_current_tenant() == outer


async def test_two_nested_scopes_each_restore_their_parent() -> None:
    t1, t2, t3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    session = _StubSession()

    async with tenant_scope(session, t1):
        assert current_tenant() == t1
        async with tenant_scope(session, t2):
            assert current_tenant() == t2
            async with tenant_scope(session, t3):
                assert current_tenant() == t3
            assert current_tenant() == t2
        assert current_tenant() == t1

    # Entering unbound and exiting unwinds to unbound — the fail-closed
    # default is unchanged by the save/restore.
    assert try_current_tenant() is None


async def test_an_unbound_entry_still_restores_unbound() -> None:
    tid = uuid.uuid4()
    session = _StubSession()
    assert try_current_tenant() is None

    async with tenant_scope(session, tid):
        assert current_tenant() == tid

    assert try_current_tenant() is None


async def test_a_raising_inner_scope_still_restores_the_outer() -> None:
    outer, inner = uuid.uuid4(), uuid.uuid4()
    set_current_tenant(outer)

    with pytest.raises(RuntimeError, match="boom"):
        async with tenant_scope(_StubSession(), inner):
            raise RuntimeError("boom")

    assert try_current_tenant() == outer


async def test_the_rls_binding_still_happens_on_the_session() -> None:
    """Save/restore must not weaken the RLS half: bind_tenant runs per scope."""
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    session = _StubSession()

    async with tenant_scope(session, t1):
        async with tenant_scope(session, t2):
            pass

    assert session.bound == [str(t1), str(t2)]

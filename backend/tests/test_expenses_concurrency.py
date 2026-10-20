"""Real concurrency: separate committed connections racing for the same numbers and the same void.

The per-test `db` fixture runs everything on ONE rolled-back connection, so it cannot
show a race. This module commits a throw-away tenant, races real connections against it,
then deletes everything it created.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.security import hash_password
from app.modules.errors import ConflictError
from app.modules.expenses.service import ExpenseService, NumberingService
from app.modules.identity.models import Role, Tenant, TenantUser, User
from app.modules.pos.service import PosService

RACERS = 20


@pytest.fixture
async def committed_tenant(db_url):
    engine = create_async_engine(
        db_url, pool_size=RACERS + 2, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    async with factory() as s:
        role = (await s.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()
        user = User(
            email=f"c-{uuid.uuid4().hex[:8]}@test.local",
            password_hash=hash_password("x-secret-pw"),
            full_name="C",
        )
        tenant = Tenant(id=tenant_id, slug=f"c-{uuid.uuid4().hex[:8]}", name="Concurrency")
        s.add_all([tenant, user])
        await s.flush()
        await s.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.id)})
        s.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role_id=role.id))
        await s.commit()
        user_id = user.id
    try:
        yield factory, tenant_id
    finally:
        # Delete EVERYTHING the test created, children first, and prove it: a leftover
        # tenant silently pollutes the shared database for every later run.
        async with factory() as s:
            await s.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            for table in (
                "pos_cash_movements",
                "pos_session_floats",
                "pos_session_reconciliations",
                "expenses",
                "expense_categories",
                "document_counters",
                "pos_sessions",
                "pos_registers",
                "inventory_balances",
                "warehouses",
            ):
                await s.execute(
                    sa.text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            await s.commit()
        async with factory() as s:
            # set_config(..., true) lasts one transaction: bind BOTH ids again for this one.
            await s.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            await s.execute(
                sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)}
            )
            await s.execute(
                sa.text("DELETE FROM tenant_users WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await s.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
            deleted = await s.execute(
                sa.text("DELETE FROM tenants WHERE id = :t RETURNING id"), {"t": tenant_id}
            )
            assert deleted.first() is not None, (
                "cleanup failed: the throw-away tenant is still there"
            )
            await s.commit()
        await engine.dispose()


async def _in_tx(factory, tenant_id, fn):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        try:
            result = await fn(s)
            await s.commit()
            return result
        except Exception as exc:  # the caller inspects it
            await s.rollback()
            return exc


async def test_parallel_numbering_has_no_duplicates_and_no_gaps(committed_tenant) -> None:
    factory, tenant_id = committed_tenant
    results = await asyncio.gather(
        *[
            _in_tx(factory, tenant_id, lambda s: NumberingService.next_number(s, tenant_id, "EXP"))
            for _ in range(RACERS)
        ]
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors[:2]
    seqs = sorted(int(n.rsplit("-", 1)[1]) for n in results)
    assert seqs == list(range(1, RACERS + 1))  # unique AND gap-free


async def test_parallel_void_reverses_the_drawer_exactly_once(committed_tenant) -> None:
    factory, tenant_id = committed_tenant

    async def setup(s):
        from app.modules.inventory.service import InventoryService

        wh = await InventoryService.get_default_warehouse(s, tenant_id)
        reg = await PosService.create_register(
            s, tenant_id, name="ك", code=f"R-{uuid.uuid4().hex[:6]}", warehouse_id=wh.id
        )
        shift = await PosService.open_session(s, tenant_id, reg.id, opening_float="100.00")
        cat = (await ExpenseService.ensure_default_categories(s, tenant_id))[0]
        exp = await ExpenseService.create(
            s,
            tenant_id,
            category_id=cat.id,
            description="x",
            amount="40.00",
            payment_method="cash",
            session_id=shift.id,
        )
        return shift.id, exp.id

    shift_id, expense_id = await _in_tx(factory, tenant_id, setup)

    results = await asyncio.gather(
        *[
            _in_tx(
                factory,
                tenant_id,
                lambda s: ExpenseService.void(s, tenant_id, expense_id, reason="سباق"),
            )
            for _ in range(RACERS)
        ]
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    conflicts = [r for r in results if isinstance(r, ConflictError)]
    assert len(winners) == 1, f"{len(winners)} voids succeeded"
    assert len(conflicts) == RACERS - 1, [
        type(r).__name__ for r in results if isinstance(r, Exception)
    ]

    async def drawer(s):
        return await PosService._cash_totals(s, tenant_id, shift_id)

    inflow, outflow = await _in_tx(factory, tenant_id, drawer)
    assert outflow == Decimal("40.00") and inflow == Decimal("40.00")  # one pay_out, ONE pay_in

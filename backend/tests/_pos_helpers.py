"""Shared fixtures for POS tests: a till to sell on, and a caller with a role's real rights."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.security import hash_password
from app.modules.identity.models import Role, Tenant, TenantUser, User
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from tests._pos_sell import sell  # noqa: F401  (re-exported)
from tests.test_pos_returns import _customer, _register, _sellable_variant, _warehouse


async def till(db, tenant_ctx):
    """An open shift on a cash-only till, a sellable variant (100.00, 50 in stock), a customer."""
    register = await _register(db, tenant_ctx)
    wh = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"P{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        allowed_payment_methods=["cash"],
    )
    shift = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, profile_id=profile.id
    )
    variant = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    customer = await _customer(db, tenant_ctx)
    return shift, variant, customer


async def start_day(db, tenant_ctx, register_id, opening="0.00"):
    """Start the trading day the way a cashier does: enter the drawer's opening balance.

    A sale is refused until this has happened, so every test that sells on a till without an
    open shift calls it first.
    """
    return await PosService.open_day(db, tenant_ctx.tenant_id, register_id, opening_float=opening)


async def ctx_for(db, tenant_ctx, role_code):
    """A TenantContext carrying the permissions the DB really grants that role."""
    import sqlalchemy as sa

    from app.modules.identity.deps import TenantContext

    codes = set(
        (
            await db.execute(
                sa.text(
                    "SELECT p.code FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
                    "JOIN permissions p ON p.id = rp.permission_id WHERE r.code = :c"
                ),
                {"c": role_code},
            )
        ).scalars()
    )
    return TenantContext(
        session=db,
        user=tenant_ctx.user,
        tenant_id=tenant_ctx.tenant_id,
        role_code=role_code,
        permission_codes=codes,
    )


# ---- committed-tenant helpers (separate connections, real commits; shared by the cross-tenant and
# ---- return-value tests). The tenant is named so the purge can only ever delete a test tenant.
_TENANT_TABLES = (
    "pos_return_lines",
    "pos_receipts",
    "pos_cash_movements",
    "pos_session_floats",
    "pos_session_reconciliations",
    "pos_session_handovers",
    "order_payments",
    "order_status_history",
    "inventory_reservations",
    "order_items",
    "orders",
    "inventory_movements",
    "inventory_balances",
    "variant_cost_history",
    "variant_costs",
    "product_prices",
    "product_identifiers",
    "product_variants",
    "products",
    "document_counters",
    "pos_sessions",
    "pos_registers",
    "warehouses",
)
_TENANT_NAME = "IsoRace"


async def purge_test_tenant(admin_url: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    engine = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.begin() as conn:
            name = (
                await conn.execute(
                    sa.text("SELECT name FROM tenants WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar()
            if name != _TENANT_NAME:
                raise AssertionError(
                    f"refusing to purge tenant {tenant_id}: its name is {name!r}, not "
                    f"{_TENANT_NAME!r}"
                )
            await conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
            for table in _TENANT_TABLES:
                await conn.execute(
                    sa.text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                    {"t": tenant_id},
                )
            await conn.execute(
                sa.text("DELETE FROM tenant_users WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await conn.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
            await conn.execute(
                sa.text("DELETE FROM tenants WHERE id = :t AND name = :n"),
                {"t": tenant_id, "n": _TENANT_NAME},
            )
            gone = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM tenants WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
            assert gone == 0, "cleanup failed: the throw-away tenant is still there"
    finally:
        await engine.dispose()


async def make_tenant(db_url, label):
    engine = create_async_engine(db_url, pool_size=4, connect_args={"statement_cache_size": 0})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    async with factory() as s:
        role = (await s.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()
        user = User(
            email=f"{label}-{uuid.uuid4().hex[:8]}@test.local",
            password_hash=hash_password("x-secret-pw"),
            full_name=label,
        )
        tenant = Tenant(id=tenant_id, slug=f"{label}-{uuid.uuid4().hex[:8]}", name=_TENANT_NAME)
        s.add_all([tenant, user])
        await s.flush()
        await s.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.id)})
        s.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role_id=role.id))
        await s.commit()
        user_id = user.id
    return engine, factory, tenant_id, user_id


async def in_tx(factory, tenant_id, fn):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        try:
            result = await fn(s)
            await s.commit()
            return result
        except Exception as exc:
            await s.rollback()
            return exc

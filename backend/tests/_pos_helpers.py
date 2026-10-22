"""Shared fixtures for POS tests: a till to sell on, and a caller with a role's real rights."""

from __future__ import annotations

import uuid

from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
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

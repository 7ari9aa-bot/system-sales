"""A register and its profile must agree on the warehouse the till sells from.

The sale reads ``register.warehouse_id``; the profile also stores one. Nothing tied them together,
so a register could sit on a profile for warehouse A while selling from warehouse B, and editing the
profile later moved nothing. The register's warehouse is the one that matters (it is what stock is
drawn from), so the profile is made to agree with it, in both directions.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.errors import ConflictError, ValidationError
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from tests.test_pos_returns import _warehouse as _default_warehouse

pytestmark = pytest.mark.asyncio


async def _warehouse(db, tenant_ctx):
    """A NEW warehouse each call (the shared helper always returns the one default)."""
    from app.modules.inventory.models import Warehouse

    await _default_warehouse(db, tenant_ctx)  # make sure the tenant has its default first
    wh = Warehouse(
        tenant_id=tenant_ctx.tenant_id, name="wh", code=f"W{uuid.uuid4().hex[:6].upper()}"
    )
    db.add(wh)
    await db.flush()
    return wh


async def _profile(db, tenant_ctx, warehouse):
    return await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="p",
        code=f"P{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )


async def _register_on(db, tenant_ctx, warehouse, profile=None):
    return await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="r",
        code=f"R{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
        profile_id=None if profile is None else profile.id,
    )


async def test_a_register_on_a_profile_must_use_the_profiles_warehouse(db, tenant_ctx):
    a = await _warehouse(db, tenant_ctx)
    b = await _warehouse(db, tenant_ctx)
    profile = await _profile(db, tenant_ctx, a)
    with pytest.raises(ValidationError, match="warehouse of its POS profile"):
        await _register_on(db, tenant_ctx, b, profile)


async def test_a_register_on_the_same_warehouse_is_fine(db, tenant_ctx):
    a = await _warehouse(db, tenant_ctx)
    profile = await _profile(db, tenant_ctx, a)
    register = await _register_on(db, tenant_ctx, a, profile)
    assert register.warehouse_id == profile.warehouse_id == a.id


async def test_a_register_with_no_profile_may_use_any_warehouse(db, tenant_ctx):
    b = await _warehouse(db, tenant_ctx)
    assert (await _register_on(db, tenant_ctx, b)).warehouse_id == b.id


async def test_moving_a_profile_is_refused_while_a_register_still_sells_from_the_old_one(
    db, tenant_ctx
):
    a = await _warehouse(db, tenant_ctx)
    b = await _warehouse(db, tenant_ctx)
    profile = await _profile(db, tenant_ctx, a)
    register = await _register_on(db, tenant_ctx, a, profile)
    with pytest.raises(ConflictError, match="1 register"):
        await PosProfileService.update(db, tenant_ctx.tenant_id, profile.id, warehouse_id=b.id)
    assert profile.warehouse_id == a.id  # nothing moved
    assert register.warehouse_id == a.id


async def test_a_profile_with_no_registers_can_change_warehouse(db, tenant_ctx):
    a = await _warehouse(db, tenant_ctx)
    b = await _warehouse(db, tenant_ctx)
    profile = await _profile(db, tenant_ctx, a)
    await PosProfileService.update(db, tenant_ctx.tenant_id, profile.id, warehouse_id=b.id)
    assert profile.warehouse_id == b.id


async def test_setting_the_same_warehouse_again_is_not_a_conflict(db, tenant_ctx):
    a = await _warehouse(db, tenant_ctx)
    profile = await _profile(db, tenant_ctx, a)
    await _register_on(db, tenant_ctx, a, profile)
    await PosProfileService.update(db, tenant_ctx.tenant_id, profile.id, warehouse_id=a.id)

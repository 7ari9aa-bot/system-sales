"""Every till operation honours the profile's operator list, not only sell / return / close.

``scan``, ``quote`` and the held-cart operations are part of using the till. A user the restricted
profile does not name must not browse the till's prices or park / read / drop carts on a day
somebody else opened; a granted user, an ungranted profile and a manager (``pos:override``) pass.
"""

from __future__ import annotations

import pytest

from app.modules.errors import PermissionDeniedError
from app.modules.pos.service import PosService
from tests.test_pos_open_day_profile_access import _register_on_profile
from tests.test_pos_returns import _sellable_variant
from tests.test_pos_shift_ownership import _user

pytestmark = pytest.mark.asyncio


async def _restricted_day(db, tenant_ctx):
    """A profile that names only the context user, a started day, one sellable variant."""
    register = await _register_on_profile(db, tenant_ctx, grant_to=tenant_ctx.user.id)
    day = await PosService.open_day(
        db,
        tenant_ctx.tenant_id,
        register.id,
        opening_float="100.00",
        actor_user_id=tenant_ctx.user.id,
    )
    variant = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    return day, variant


def _items(variant):
    return [{"variant_id": str(variant.id), "quantity": 1}]


async def test_an_ungranted_user_cannot_scan_or_quote(db, tenant_ctx) -> None:
    day, variant = await _restricted_day(db, tenant_ctx)
    stranger = await _user(db, "stranger")
    tid = tenant_ctx.tenant_id
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.scan(
            db,
            tid,
            day.id,
            identifier_type="sku",
            value="whatever",
            actor_user_id=stranger.id,
        )
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.quote(db, tid, day.id, items=_items(variant), actor_user_id=stranger.id)


async def test_an_ungranted_user_cannot_touch_held_carts(db, tenant_ctx) -> None:
    day, variant = await _restricted_day(db, tenant_ctx)
    stranger = await _user(db, "stranger")
    tid = tenant_ctx.tenant_id
    held = await PosService.hold_cart(
        db,
        tid,
        day.id,
        items=_items(variant),
        held_by=tenant_ctx.user.id,
        actor_user_id=tenant_ctx.user.id,
    )
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.hold_cart(
            db,
            tid,
            day.id,
            items=_items(variant),
            held_by=stranger.id,
            actor_user_id=stranger.id,
        )
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.list_held_carts(db, tid, day.id, actor_user_id=stranger.id)
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.get_held_cart(db, tid, held.id, actor_user_id=stranger.id)
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.release_held_cart(db, tid, held.id, actor_user_id=stranger.id)
    # The refused attempts changed nothing: the owner's cart is still there.
    still = await PosService.list_held_carts(db, tid, day.id, actor_user_id=tenant_ctx.user.id)
    assert [h.id for h in still] == [held.id]


async def test_a_granted_user_and_a_manager_can_use_the_till(db, tenant_ctx) -> None:
    day, variant = await _restricted_day(db, tenant_ctx)
    manager = await _user(db, "manager")
    tid = tenant_ctx.tenant_id
    me = tenant_ctx.user.id
    quoted = await PosService.quote(db, tid, day.id, items=_items(variant), actor_user_id=me)
    assert quoted["grand_total"] == "100.00"
    held = await PosService.hold_cart(
        db, tid, day.id, items=_items(variant), held_by=me, actor_user_id=me
    )
    # A manager covering the till passes the profile check (``pos:override``).
    assert await PosService.get_held_cart(db, tid, held.id, actor_user_id=manager.id, override=True)
    await PosService.release_held_cart(db, tid, held.id, actor_user_id=me)
    assert await PosService.list_held_carts(db, tid, day.id, actor_user_id=me) == []


async def test_an_ungranted_profile_stays_open_to_every_orders_write_holder(db, tenant_ctx) -> None:
    register = await _register_on_profile(db, tenant_ctx, grant_to=None)
    day = await PosService.open_day(
        db, tenant_ctx.tenant_id, register.id, opening_float="0", actor_user_id=tenant_ctx.user.id
    )
    variant = await _sellable_variant(db, tenant_ctx, price="100.00", stock=5)
    anyone = await _user(db, "anyone")
    quoted = await PosService.quote(
        db, tenant_ctx.tenant_id, day.id, items=_items(variant), actor_user_id=anyone.id
    )
    assert quoted["grand_total"] == "100.00"

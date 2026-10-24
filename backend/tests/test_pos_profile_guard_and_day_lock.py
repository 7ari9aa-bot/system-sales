"""A restricted profile stays restricted for the WHOLE day, and the day's operations queue.

Starting a day is not the only till operation: a user the profile does not name must not sell,
return, exchange or close on a day somebody else opened. A manager (``pos:override``) covers.
Quantities are whole pieces, and the same variant may not appear twice in one sale.
"""

from __future__ import annotations

import pytest

from app.modules.errors import ConflictError, PermissionDeniedError, ValidationError
from app.modules.pos.service import PosService
from tests.test_pos_open_day_profile_access import _register_on_profile
from tests.test_pos_returns import _sellable_variant
from tests.test_pos_shift_ownership import _user

pytestmark = pytest.mark.asyncio


async def _open_restricted_day(db, tenant_ctx):
    """A restricted profile naming only the context user, a started day and one recorded sale."""
    register = await _register_on_profile(db, tenant_ctx, grant_to=tenant_ctx.user.id)
    day = await PosService.open_day(
        db,
        tenant_ctx.tenant_id,
        register.id,
        opening_float="100.00",
        actor_user_id=tenant_ctx.user.id,
    )
    variant = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    sale = await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        actor_user_id=tenant_ctx.user.id,
    )
    return register, day, variant, sale


async def test_an_ungranted_user_cannot_sell_on_a_restricted_profile(db, tenant_ctx) -> None:
    register, _day, variant, _sale = await _open_restricted_day(db, tenant_ctx)
    stranger = await _user(db, "stranger")
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            actor_user_id=stranger.id,
        )


async def test_an_ungranted_user_cannot_return_exchange_or_close(db, tenant_ctx) -> None:
    register, day, variant, sale = await _open_restricted_day(db, tenant_ctx)
    stranger = await _user(db, "stranger")
    tid = tenant_ctx.tenant_id
    line = {"variant_id": str(variant.id), "quantity": 1}
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.return_sale(
            db, tid, day.id, order_id=sale["order_id"], lines=[line], actor_user_id=stranger.id
        )
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.exchange(
            db,
            tid,
            day.id,
            order_id=sale["order_id"],
            return_lines=[line],
            new_lines=[line],
            actor_user_id=stranger.id,
        )
    with pytest.raises(PermissionDeniedError, match="does not operate"):
        await PosService.close_session(db, tid, day.id, closed_by=stranger.id)


async def test_a_manager_override_covers_the_restricted_profile(db, tenant_ctx) -> None:
    _register, day, _variant, _sale = await _open_restricted_day(db, tenant_ctx)
    manager = await _user(db, "manager")
    closed = await PosService.close_session(
        db, tenant_ctx.tenant_id, day.id, closed_by=manager.id, shift_override=True
    )
    assert closed.status == "CLOSED"


async def test_a_sale_after_the_close_is_refused(db, tenant_ctx) -> None:
    register, day, variant, _sale = await _open_restricted_day(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, day.id, closed_by=tenant_ctx.user.id)
    with pytest.raises(ConflictError, match="day has not been started|closed"):
        await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            actor_user_id=tenant_ctx.user.id,
        )


@pytest.mark.parametrize("bad", [1.9, "1.5", 0, -1, True, None, "abc"])
async def test_a_quantity_must_be_a_whole_positive_number(db, tenant_ctx, bad) -> None:
    register, _day, variant, _sale = await _open_restricted_day(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[{"variant_id": str(variant.id), "quantity": bad}],
            actor_user_id=tenant_ctx.user.id,
        )


@pytest.mark.parametrize("ok", [2, "2", 2.0])
def test_whole_quantities_are_accepted_in_any_spelling(ok) -> None:
    assert PosService._positive_qty(ok) == 2


async def test_the_same_variant_twice_in_one_sale_is_refused(db, tenant_ctx) -> None:
    register, _day, variant, _sale = await _open_restricted_day(db, tenant_ctx)
    line = {"variant_id": str(variant.id), "quantity": 1}
    with pytest.raises(ValidationError, match="once"):
        await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[line, dict(line)],
            actor_user_id=tenant_ctx.user.id,
        )


async def test_the_sessions_list_honours_its_limit(db, tenant_ctx) -> None:
    """The export asks for 500 sessions; a hidden cap at 50 would drop days without a word."""
    from tests.test_pos_returns import _register

    register = await _register(db, tenant_ctx)
    await PosService.open_day(db, tenant_ctx.tenant_id, register.id, opening_float="0.00")
    one = await PosService.list_sessions(db, tenant_ctx.tenant_id, limit=1)
    assert len(one) == 1
    many = await PosService.list_sessions(db, tenant_ctx.tenant_id, limit=500)
    assert len(many) >= 1

"""ACTIVITY feed: a read-only timeline over the real tables must tell the truth and never leak."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db import bind_tenant
from app.main import create_app
from app.modules.activity.service import KINDS, ActivityService, Cursor
from app.modules.expenses.service import ExpenseService
from app.modules.pos.service import PosService
from tests._pos_sell import sell as pos_sell


async def _shift(db, tenant_ctx, opening="100.00"):
    from app.modules.inventory.service import InventoryService

    wh = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    reg = await PosService.create_register(
        db, tenant_ctx.tenant_id, name="كاشير", code=f"R-{uuid.uuid4().hex[:6]}", warehouse_id=wh.id
    )
    return await PosService.open_session(db, tenant_ctx.tenant_id, reg.id, opening_float=opening)


async def _expense(db, tenant_ctx, shift, amount="10.00", desc="x"):
    cat = (await ExpenseService.ensure_default_categories(db, tenant_ctx.tenant_id))[0]
    return await ExpenseService.create(
        db,
        tenant_ctx.tenant_id,
        category_id=cat.id,
        description=desc,
        amount=amount,
        payment_method="cash",
    )


def test_routes_are_mounted_and_read_only() -> None:
    paths = create_app().openapi()["paths"]
    assert {"/api/v1/activity", "/api/v1/activity/summary"} <= set(paths)
    # nothing but GET: the timeline can never write
    assert set(paths["/api/v1/activity"]) == {"get"}
    assert set(paths["/api/v1/activity/summary"]) == {"get"}


async def test_every_kind_runs_alone_and_together(db, tenant_ctx) -> None:
    """A UNION takes its column names from its first branch; each subset must still be valid SQL."""
    for k in KINDS:
        rows, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, kinds=(k,), limit=5)
        assert rows == [] or {r["kind"] for r in rows} == {k}
    rows, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, kinds=tuple(reversed(KINDS)))
    assert isinstance(rows, list)


async def test_a_shift_and_an_expense_show_up_newest_first(db, tenant_ctx) -> None:
    shift = await _shift(db, tenant_ctx)
    exp = await _expense(db, tenant_ctx, shift, "45.50", "أكياس")
    rows, nxt = await ActivityService.feed(db, tenant_ctx.tenant_id)
    assert nxt is None
    kinds = [r["kind"] for r in rows]
    assert "expense" in kinds and "shift" in kinds
    assert [r["occurred_at"] for r in rows] == sorted(
        (r["occurred_at"] for r in rows), reverse=True
    )
    e = next(r for r in rows if r["kind"] == "expense")
    assert e["doc"] == exp.number and e["amount"] == Decimal("45.50")
    assert e["actor_id"] is None or isinstance(e["actor_id"], str)
    assert "أكياس" in e["detail"]


async def test_a_voided_expense_is_marked_not_hidden(db, tenant_ctx) -> None:
    shift = await _shift(db, tenant_ctx)
    exp = await _expense(db, tenant_ctx, shift, "20.00", "تالف")
    await ExpenseService.void(
        db, tenant_ctx.tenant_id, exp.id, reason="غلط", voided_by=tenant_ctx.user.id
    )
    rows, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, kinds=("expense",))
    assert len(rows) == 1 and "ملغي" in rows[0]["detail"]


async def test_filters_narrow_by_kind_actor_window_and_search(db, tenant_ctx) -> None:
    shift = await _shift(db, tenant_ctx)
    await _expense(db, tenant_ctx, shift, "5.00", "ورق طباعة")
    await _expense(db, tenant_ctx, shift, "6.00", "مياه")
    only_exp, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, kinds=("expense",))
    assert len(only_exp) == 2 and {r["kind"] for r in only_exp} == {"expense"}
    hit, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, search="ورق")
    assert [r["detail"] for r in hit] == ["ورق طباعة"]
    # a LIKE wildcard typed by the user is just a character to look for, not a pattern
    none, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, search="%")
    assert none == []
    future = datetime.now(UTC) + timedelta(days=2)
    empty, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, date_from=future)
    assert empty == []
    past, _ = await ActivityService.feed(
        db, tenant_ctx.tenant_id, date_to=datetime.now(UTC) - timedelta(days=2)
    )
    assert past == []
    nobody, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, actor_id=uuid.uuid4())
    assert nobody == []


async def test_paging_walks_every_row_once_even_when_rows_share_an_instant(db, tenant_ctx) -> None:
    shift = await _shift(db, tenant_ctx)
    made = [await _expense(db, tenant_ctx, shift, "1.00", f"e{i}") for i in range(7)]
    # the nasty case: all seven stamped with the very same instant
    await db.execute(
        text("UPDATE expenses SET created_at = :t WHERE tenant_id = :tid"),
        {"t": datetime(2026, 1, 1, 12, 0, tzinfo=UTC), "tid": tenant_ctx.tenant_id},
    )
    seen: list[str] = []
    cursor = None
    for _ in range(20):
        rows, cursor = await ActivityService.feed(
            db, tenant_ctx.tenant_id, kinds=("expense",), limit=3, cursor=cursor
        )
        seen += [r["ekey"] for r in rows]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == len(made), "a row was repeated or skipped between pages"


def test_cursor_round_trips_and_rejects_garbage() -> None:
    c = Cursor(at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC), ref="abc")
    back = Cursor.decode(c.encode())
    assert back.at == c.at and back.ref == "abc"
    for bad in ("", "zzz", "e30=", "bm90LWpzb24="):
        with pytest.raises(ValueError):
            Cursor.decode(bad)


async def test_summary_counts_match_the_feed(db, tenant_ctx) -> None:
    shift = await _shift(db, tenant_ctx)
    await _expense(db, tenant_ctx, shift)
    await _expense(db, tenant_ctx, shift)
    counts = await ActivityService.summary(db, tenant_ctx.tenant_id)
    assert set(counts) == set(KINDS)
    for k in KINDS:
        rows, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, kinds=(k,), limit=200)
        assert counts[k] == len(rows), k


async def test_a_tenant_never_sees_another_tenants_activity(db, tenant_ctx) -> None:
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.modules.identity.models import Role, Tenant, TenantUser, User

    shift = await _shift(db, tenant_ctx)
    await _expense(db, tenant_ctx, shift, "77.00", "سري")
    mine, _ = await ActivityService.feed(db, tenant_ctx.tenant_id)

    role = (await db.execute(select(Role).where(Role.code == "owner"))).scalar_one()
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    user = User(
        email=f"o-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("secret-password"),
        full_name="Other",
    )
    db.add_all([other, user])
    await db.flush()
    await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.id)})
    db.add(TenantUser(tenant_id=other.id, user_id=user.id, role_id=role.id))
    await db.flush()
    await bind_tenant(db, other.id)
    theirs, _ = await ActivityService.feed(db, other.id)
    assert not any("سري" in (r["detail"] or "") for r in theirs)
    assert {r["ekey"] for r in theirs}.isdisjoint({r["ekey"] for r in mine})
    # asking for the OTHER tenant's id while bound to ours must still give nothing of theirs
    await bind_tenant(db, tenant_ctx.tenant_id)
    crossed, _ = await ActivityService.feed(db, other.id)
    assert crossed == []


async def test_a_partial_return_shows_the_money_handed_back_not_the_order_total(
    db, tenant_ctx
) -> None:
    """The return receipt hangs off the ORIGINAL order, whose grand_total is the whole sale.
    The feed must show what went back to the customer; showing the order total would overstate
    the refund (and any report built on it) by the value of everything not returned."""
    from tests.test_pos_returns import _customer, _register, _sellable_variant

    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await pos_sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        discount_total="10.00",
    )
    assert Decimal(sold["grand_total"]) == Decimal("40.00")
    back = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    assert Decimal(back["refunded_total"]) == Decimal("20.00")

    rows, _ = await ActivityService.feed(db, tenant_ctx.tenant_id, kinds=("sale", "return"))
    by_kind = {r["kind"]: r for r in rows}
    assert by_kind["sale"]["amount"] == Decimal("40.00")
    assert by_kind["return"]["amount"] == Decimal("20.00"), "the order total leaked into the refund"
    assert by_kind["return"]["doc"] == back["receipt_number"]
    # the item is named for the cashier, and the cashier is the shift's holder
    assert by_kind["return"]["detail"]
    assert by_kind["sale"]["actor_id"] == by_kind["return"]["actor_id"]


async def test_a_closed_shift_is_two_events_that_page_without_loss_or_repeat(
    db, tenant_ctx
) -> None:
    """Opening and closing a shift share one ref_id. Paging by ref_id alone would treat them as the
    same row and drop one at a page boundary (or repeat it); the event key tells them apart."""
    for _ in range(3):
        shift = await _shift(db, tenant_ctx)
        await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    everything, _ = await ActivityService.feed(
        db, tenant_ctx.tenant_id, kinds=("shift",), limit=200
    )
    assert len(everything) == 6
    assert len({r["ekey"] for r in everything}) == 6, "open and close collapsed into one event"
    assert len({r["ref_id"] for r in everything}) == 3
    # a page size of 1 puts a boundary between every open/close pair
    walked: list[str] = []
    cursor = None
    for _ in range(12):
        rows, cursor = await ActivityService.feed(
            db, tenant_ctx.tenant_id, kinds=("shift",), limit=1, cursor=cursor
        )
        walked += [r["ekey"] for r in rows]
        if cursor is None:
            break
    assert sorted(walked) == sorted(r["ekey"] for r in everything)


# ------------------------------------------------- the day is the merchant's -----


async def test_the_day_filter_uses_the_tenants_own_zone(db, tenant_ctx) -> None:
    """The same calendar date is a different window for a Cairo shop and a Dubai shop."""
    import sqlalchemy as sa

    from app.modules.activity.router import window_for

    async def zone(tz):
        await db.execute(
            sa.text("UPDATE tenants SET timezone = :z WHERE id = :t"),
            {"z": tz, "t": tenant_ctx.tenant_id},
        )

    day = date(2026, 1, 10)
    await zone("Africa/Cairo")  # UTC+2 in winter
    start, end = await window_for(db, tenant_ctx.tenant_id, day, day)
    assert start.astimezone(UTC) == datetime(2026, 1, 9, 22, 0, tzinfo=UTC)
    assert end.astimezone(UTC) == datetime(2026, 1, 10, 22, 0, tzinfo=UTC)

    await zone("Asia/Dubai")  # UTC+4
    start, end = await window_for(db, tenant_ctx.tenant_id, day, day)
    assert start.astimezone(UTC) == datetime(2026, 1, 9, 20, 0, tzinfo=UTC)


async def test_a_tenant_with_no_zone_still_gets_a_window(db, tenant_ctx) -> None:
    import sqlalchemy as sa

    from app.modules.activity.router import window_for

    await db.execute(
        sa.text("UPDATE tenants SET timezone = NULL WHERE id = :t"), {"t": tenant_ctx.tenant_id}
    )
    start, end = await window_for(db, tenant_ctx.tenant_id, date(2026, 1, 10), None)
    assert start is not None and end is None


async def test_a_backwards_range_is_still_refused(db, tenant_ctx) -> None:
    from fastapi import HTTPException

    from app.modules.activity.router import window_for

    with pytest.raises(HTTPException) as err:
        await window_for(db, tenant_ctx.tenant_id, date(2026, 1, 10), date(2026, 1, 9))
    assert err.value.status_code == 422

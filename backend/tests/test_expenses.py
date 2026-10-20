"""EXPENSES: a cash expense and the drawer are ONE fact; money is never rounded or doubled."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.expenses.service import ExpenseService, NumberingService, exact_money
from app.modules.pos.service import PosService


def test_expense_routes_are_mounted_and_guarded_against_double_submit() -> None:
    from app.core.idempotency import IDEMPOTENT_PATHS

    paths = set(create_app().openapi()["paths"])
    assert {
        "/api/v1/expenses",
        "/api/v1/expenses/{expense_id}/void",
        "/api/v1/expenses/categories",
    } <= paths
    assert "/api/v1/expenses" in IDEMPOTENT_PATHS


@pytest.mark.parametrize(
    "bad", ["0", "-5", "abc", "", "NaN", "Infinity", "10.005", "1e3x", "9999999999.00"]
)
def test_exact_money_rejects_what_it_must(bad) -> None:
    with pytest.raises(ValidationError):
        exact_money(bad)


@pytest.mark.parametrize(
    "good,expected", [("10", "10.00"), ("10.5", "10.50"), (" 7.25 ", "7.25"), (3, "3.00")]
)
def test_exact_money_accepts_and_never_rounds(good, expected) -> None:
    assert exact_money(good) == Decimal(expected)


# ----------------------------------------------------------- DB-backed -----


async def _must_fail(db, sql, params) -> None:
    """Run `sql` in a savepoint that is rolled back, and require the DATABASE to refuse it."""
    savepoint = await db.begin_nested()
    try:
        await db.execute(sql, params)
    except IntegrityError:
        await savepoint.rollback()
        return
    await savepoint.rollback()
    pytest.fail(f"the database accepted a row it must refuse: {params}")


async def _open_shift(db, tenant_ctx, opening="100.00"):
    from app.modules.inventory.service import InventoryService

    wh = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    reg = await PosService.create_register(
        db, tenant_ctx.tenant_id, name="كاشير", code=f"R-{uuid.uuid4().hex[:6]}", warehouse_id=wh.id
    )
    return await PosService.open_session(db, tenant_ctx.tenant_id, reg.id, opening_float=opening)


async def _category(db, tenant_ctx):
    cats = await ExpenseService.ensure_default_categories(db, tenant_ctx.tenant_id)
    return cats[0]


async def _drawer(db, tenant_ctx, session_id):
    return await PosService._cash_totals(db, tenant_ctx.tenant_id, session_id)


async def test_default_categories_are_seeded_once(db, tenant_ctx) -> None:
    a = await ExpenseService.ensure_default_categories(db, tenant_ctx.tenant_id)
    b = await ExpenseService.ensure_default_categories(db, tenant_ctx.tenant_id)
    assert len(a) == 11 and {c.id for c in a} == {c.id for c in b}


async def test_cash_expense_leaves_the_drawer_by_exactly_its_amount(db, tenant_ctx) -> None:
    shift = await _open_shift(db, tenant_ctx)
    cat = await _category(db, tenant_ctx)
    _, out_before = await _drawer(db, tenant_ctx, shift.id)
    exp = await ExpenseService.create(
        db,
        tenant_ctx.tenant_id,
        category_id=cat.id,
        description="أكياس",
        amount="45.50",
        payment_method="cash",
        session_id=shift.id,
    )
    _, out_after = await _drawer(db, tenant_ctx, shift.id)
    assert out_after - out_before == Decimal("45.50")
    assert (
        exp.amount == Decimal("45.50") and exp.status == "posted" and exp.number.startswith("EXP-")
    )
    row = (
        await db.execute(
            text(
                "select direction, reason, amount, reference_type, reference_id "
                "from pos_cash_movements "
                "where session_id=:s and reference_id=:e"
            ),
            {"s": shift.id, "e": exp.id},
        )
    ).one()
    assert (row.direction, row.reason, row.amount, row.reference_type) == (
        "out",
        "pay_out",
        Decimal("45.50"),
        "expense",
    )


async def test_non_cash_expense_never_touches_the_drawer(db, tenant_ctx) -> None:
    shift = await _open_shift(db, tenant_ctx)
    cat = await _category(db, tenant_ctx)
    before = await _drawer(db, tenant_ctx, shift.id)
    await ExpenseService.create(
        db,
        tenant_ctx.tenant_id,
        category_id=cat.id,
        description="إنترنت",
        amount="300",
        payment_method="bank_transfer",
    )
    assert await _drawer(db, tenant_ctx, shift.id) == before


async def test_cash_expense_without_a_shift_is_refused(db, tenant_ctx) -> None:
    cat = await _category(db, tenant_ctx)
    with pytest.raises(ConflictError, match="open a shift"):
        await ExpenseService.create(
            db,
            tenant_ctx.tenant_id,
            category_id=cat.id,
            description="x",
            amount="5",
            payment_method="cash",
        )


async def test_cash_expense_on_a_closed_shift_is_refused(db, tenant_ctx) -> None:
    shift = await _open_shift(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="100.00")
    cat = await _category(db, tenant_ctx)
    with pytest.raises(ConflictError, match="OPEN shift"):
        await ExpenseService.create(
            db,
            tenant_ctx.tenant_id,
            category_id=cat.id,
            description="x",
            amount="5",
            payment_method="cash",
            session_id=shift.id,
        )


async def test_non_cash_expense_cannot_be_tied_to_a_shift(db, tenant_ctx) -> None:
    shift = await _open_shift(db, tenant_ctx)
    cat = await _category(db, tenant_ctx)
    with pytest.raises(ValidationError, match="only a cash expense"):
        await ExpenseService.create(
            db,
            tenant_ctx.tenant_id,
            category_id=cat.id,
            description="x",
            amount="5",
            payment_method="card",
            session_id=shift.id,
        )


async def test_third_decimal_is_rejected_not_rounded(db, tenant_ctx) -> None:
    cat = await _category(db, tenant_ctx)
    with pytest.raises(ValidationError, match="2 decimal"):
        await ExpenseService.create(
            db,
            tenant_ctx.tenant_id,
            category_id=cat.id,
            description="x",
            amount="10.005",
            payment_method="card",
        )


async def test_unknown_category_and_inactive_category(db, tenant_ctx) -> None:
    with pytest.raises(NotFoundError):
        await ExpenseService.create(
            db,
            tenant_ctx.tenant_id,
            category_id=uuid.uuid4(),
            description="x",
            amount="5",
            payment_method="card",
        )
    cat = await _category(db, tenant_ctx)
    cat.is_active = False
    await db.flush()
    with pytest.raises(ConflictError, match="inactive"):
        await ExpenseService.create(
            db,
            tenant_ctx.tenant_id,
            category_id=cat.id,
            description="x",
            amount="5",
            payment_method="card",
        )


async def test_void_reverses_the_drawer_once(db, tenant_ctx) -> None:
    shift = await _open_shift(db, tenant_ctx)
    cat = await _category(db, tenant_ctx)
    inflow0, outflow0 = await _drawer(db, tenant_ctx, shift.id)
    exp = await ExpenseService.create(
        db,
        tenant_ctx.tenant_id,
        category_id=cat.id,
        description="غلط",
        amount="80",
        payment_method="cash",
        session_id=shift.id,
    )
    await ExpenseService.void(db, tenant_ctx.tenant_id, exp.id, reason="اتسجل بالغلط")
    inflow1, outflow1 = await _drawer(db, tenant_ctx, shift.id)
    # the pay_out stays in the ledger and a pay_in cancels it: net cash effect is zero
    assert outflow1 - outflow0 == Decimal("80.00") and inflow1 - inflow0 == Decimal("80.00")
    assert (
        exp.status == "voided" and exp.void_reason == "اتسجل بالغلط" and exp.voided_at is not None
    )
    with pytest.raises(ConflictError, match="already voided"):
        await ExpenseService.void(db, tenant_ctx.tenant_id, exp.id, reason="تاني")
    assert await _drawer(db, tenant_ctx, shift.id) == (
        inflow1,
        outflow1,
    )  # second void changed nothing


async def test_void_needs_a_reason_and_an_open_shift_for_cash(db, tenant_ctx) -> None:
    shift = await _open_shift(db, tenant_ctx)
    cat = await _category(db, tenant_ctx)
    exp = await ExpenseService.create(
        db,
        tenant_ctx.tenant_id,
        category_id=cat.id,
        description="x",
        amount="10",
        payment_method="cash",
        session_id=shift.id,
    )
    with pytest.raises(ValidationError, match="reason"):
        await ExpenseService.void(db, tenant_ctx.tenant_id, exp.id, reason="   ")
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="90.00")
    with pytest.raises(ConflictError, match="closed"):
        await ExpenseService.void(db, tenant_ctx.tenant_id, exp.id, reason="متأخر")
    assert exp.status == "posted"  # a refused void leaves it posted


async def test_numbers_are_sequential_and_per_kind(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    a = await NumberingService.next_number(db, t, "EXP")
    b = await NumberingService.next_number(db, t, "EXP")
    po = await NumberingService.next_number(db, t, "PO")
    assert (
        a.endswith("-0001")
        and b.endswith("-0002")
        and po.endswith("-0001")
        and a.startswith("EXP-")
    )


async def test_listing_totals_exclude_voided_and_filter(db, tenant_ctx) -> None:
    cat = await _category(db, tenant_ctx)
    t = tenant_ctx.tenant_id
    e1 = await ExpenseService.create(
        db, t, category_id=cat.id, description="a", amount="100", payment_method="card"
    )
    e2 = await ExpenseService.create(
        db, t, category_id=cat.id, description="b", amount="50.25", payment_method="card"
    )
    await ExpenseService.void(db, t, e2.id, reason="غلط")
    totals = await ExpenseService.totals(db, t)
    assert totals["total"] == Decimal("100.00") and totals["count"] == 1
    assert {x.id for x in await ExpenseService.list(db, t)} == {e1.id, e2.id}
    assert [x.id for x in await ExpenseService.list(db, t, status="voided")] == [e2.id]
    assert [
        x.id for x in await ExpenseService.list(db, t, payment_method="card", status="posted")
    ] == [e1.id]


async def test_database_itself_refuses_bad_rows(db, tenant_ctx) -> None:
    """Even a service written wrong cannot store a zero amount or a cash expense with no drawer."""
    cat = await _category(db, tenant_ctx)
    base = dict(t=tenant_ctx.tenant_id, c=cat.id)
    sql = text(
        "insert into expenses (id, tenant_id, number, category_id, description, amount, "
        "payment_method, "
        "expense_date, status) values "
        "(gen_random_uuid(), :t, :n, :c, 'x', :a, :m, current_date, 'posted')"
    )
    for amount, method in [("0", "card"), ("-1", "card"), ("5", "cash"), ("5", "crypto")]:
        await _must_fail(
            db, sql, {**base, "n": f"X-{uuid.uuid4().hex[:6]}", "a": amount, "m": method}
        )


async def test_duplicate_document_number_is_refused_by_the_database(db, tenant_ctx) -> None:
    cat = await _category(db, tenant_ctx)
    sql = text(
        "insert into expenses (id, tenant_id, number, category_id, description, amount, "
        "payment_method, "
        "expense_date, status) values "
        "(gen_random_uuid(), :t, 'EXP-DUP', :c, 'x', 5, 'card', current_date, 'posted')"
    )
    await db.execute(sql, {"t": tenant_ctx.tenant_id, "c": cat.id})
    await _must_fail(db, sql, {"t": tenant_ctx.tenant_id, "c": cat.id})

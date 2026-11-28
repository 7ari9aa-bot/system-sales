"""Customer accounts on a real database: append-only ledger, real limits, safe replays."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.applications.apparel.modules.customer_accounts.service import CustomerAccountService as S
from app.modules.errors import ConflictError, NotFoundError, ValidationError
from tests._pos_helpers import in_tx as _in_tx
from tests._pos_helpers import make_tenant as _make_tenant
from tests._pos_helpers import purge_test_tenant as _purge_test_tenant
from tests.test_pos_returns import _customer

D = Decimal


async def _acct(db, tenant_ctx, limit="500"):
    customer = await _customer(db, tenant_ctx)
    await S.open_account(db, tenant_ctx.tenant_id, customer.id, credit_limit=limit)
    return customer


async def test_a_customer_without_an_account_gets_no_credit(db, tenant_ctx) -> None:
    customer = await _customer(db, tenant_ctx)
    with pytest.raises(ConflictError):
        await S.charge(db, tenant_ctx.tenant_id, customer.id, sale_total="100")


async def test_opening_twice_edits_the_terms_not_a_duplicate(db, tenant_ctx) -> None:
    customer = await _customer(db, tenant_ctx)
    a = await S.open_account(db, tenant_ctx.tenant_id, customer.id, credit_limit="100")
    b = await S.open_account(db, tenant_ctx.tenant_id, customer.id, credit_limit="900")
    assert a.id == b.id and D(str(b.credit_limit)) == D("900.00")


async def test_an_archived_customer_cannot_be_given_an_account(db, tenant_ctx) -> None:
    from datetime import UTC, datetime

    customer = await _customer(db, tenant_ctx)
    customer.deleted_at = datetime.now(UTC)
    await db.flush()
    with pytest.raises(NotFoundError):
        await S.open_account(db, tenant_ctx.tenant_id, customer.id)


async def test_an_unknown_customer_cannot_be_given_an_account(db, tenant_ctx) -> None:
    with pytest.raises(NotFoundError):
        await S.open_account(db, tenant_ctx.tenant_id, uuid.uuid4())


async def test_a_sale_on_account_then_payments_walk_the_balance_to_zero(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx)
    await S.charge(db, t, c.id, sale_total="300", paid_now="100")  # 200 on account
    assert await S.balance(db, t, c.id) == D("200.00")
    await S.receive_payment(db, t, c.id, amount="50")
    await S.receive_payment(db, t, c.id, amount="150")
    assert await S.balance(db, t, c.id) == D("0.00")
    rows = await S.statement(db, t, c.id)
    assert [r.entry_type for r in rows][::-1] == ["charge", "payment", "payment"]
    assert D(str(rows[0].balance_after)) == D("0.00")


async def test_a_fully_paid_sale_posts_nothing(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx)
    assert await S.charge(db, t, c.id, sale_total="100", paid_now="100") is None
    assert await S.statement(db, t, c.id) == []


async def test_the_credit_limit_refuses_and_names_the_excess(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx, limit="500")
    await S.charge(db, t, c.id, sale_total="400")
    with pytest.raises(ConflictError, match="100"):
        await S.charge(db, t, c.id, sale_total="200")
    assert await S.balance(db, t, c.id) == D("400.00")  # the refused sale left no trace


async def test_a_blocked_customer_cannot_buy_on_account(db, tenant_ctx) -> None:
    c = await _acct(db, tenant_ctx)
    with pytest.raises(ConflictError):
        await S.charge(db, tenant_ctx.tenant_id, c.id, sale_total="10", blocked=True)


async def test_overpaying_a_debt_is_refused_it_must_be_a_deposit(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx)
    await S.charge(db, t, c.id, sale_total="100")
    with pytest.raises(ConflictError):
        await S.receive_payment(db, t, c.id, amount="100.01")
    with pytest.raises(ConflictError):  # nothing owed at all
        c2 = await _acct(db, tenant_ctx)
        await S.receive_payment(db, t, c2.id, amount="5")


async def test_a_deposit_is_credit_and_a_sale_uses_it_up(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx)
    await S.take_deposit(db, t, c.id, amount="200")
    assert await S.balance(db, t, c.id) == D("-200.00")
    used = await S.apply_deposit_to_sale(db, t, c.id, sale_total="150")
    assert used == D("150.00")
    assert await S.balance(db, t, c.id) == D("-50.00")  # 50 of credit left
    used2 = await S.apply_deposit_to_sale(db, t, c.id, sale_total="500")
    assert used2 == D("50.00")  # never more than is held
    assert await S.balance(db, t, c.id) == D("0.00")
    assert await S.apply_deposit_to_sale(db, t, c.id, sale_total="10") == D("0.00")


async def test_a_replayed_request_posts_once(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx)
    first = await S.charge(db, t, c.id, sale_total="100", idempotency_key="till1-sale-77")
    again = await S.charge(db, t, c.id, sale_total="100", idempotency_key="till1-sale-77")
    assert again.id == first.id
    assert await S.balance(db, t, c.id) == D("100.00")


async def test_adjustment_needs_a_reason_and_a_reversal_cancels_exactly(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await S.adjust(db, t, c.id, amount="10", reason="  ")
    wrong = await S.charge(db, t, c.id, sale_total="123.45")
    await S.reverse(db, t, wrong.id, reason="رقم غلط")
    assert await S.balance(db, t, c.id) == D("0.00")
    with pytest.raises(ConflictError):  # only once
        await S.reverse(db, t, wrong.id, reason="مرة تانية")


async def test_a_reversal_cannot_be_reversed(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx)
    e = await S.charge(db, t, c.id, sale_total="50")
    rev = await S.reverse(db, t, e.id, reason="غلط")
    with pytest.raises(ConflictError):
        await S.reverse(db, t, rev.id, reason="x")


# ---- the database is the last line ----


async def test_the_database_refuses_to_edit_or_delete_the_ledger(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    c = await _acct(db, tenant_ctx)
    e = await S.charge(db, t, c.id, sale_total="100")
    for sql in (
        "UPDATE customer_ledger SET amount = 1 WHERE id = :i",
        "DELETE FROM customer_ledger WHERE id = :i",
    ):
        with pytest.raises((DBAPIError, IntegrityError)):
            async with db.begin_nested():
                await db.execute(text(sql), {"i": e.id})
    assert await S.balance(db, t, c.id) == D("100.00")


@pytest.mark.parametrize(
    "etype,amount",
    [("payment", "10"), ("deposit", "10"), ("charge", "-10"), ("deposit_applied", "-10")],
)
async def test_the_database_refuses_a_wrong_sign(db, tenant_ctx, etype, amount) -> None:
    c = await _acct(db, tenant_ctx)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO customer_ledger (id, tenant_id, customer_id, entry_type, "
                    "amount, balance_after) VALUES (:i, :t, :c, :e, :a, 0)"
                ),
                {"i": uuid.uuid4(), "t": tenant_ctx.tenant_id, "c": c.id, "e": etype, "a": amount},
            )


# ---- two tills, one customer ----


@pytest.fixture
async def two_tenants(db_url, admin_url):
    ea, fa, ta, ua = await _make_tenant(db_url, "a")
    eb, fb, tb, ub = await _make_tenant(db_url, "b")
    try:
        yield (fa, ta), (fb, tb)
    finally:
        await ea.dispose()
        await eb.dispose()
        await _purge_test_tenant(admin_url, ta, ua)
        await _purge_test_tenant(admin_url, tb, ub)


async def _make_customer(factory, tenant_id):
    from app.applications.apparel.modules.customers.models import Customer

    async def make(s):
        c = Customer(tenant_id=tenant_id, name="عميل")
        s.add(c)
        await s.flush()
        await S.open_account(s, tenant_id, c.id, credit_limit="500")
        return c.id

    result = await _in_tx(factory, tenant_id, make)
    assert not isinstance(result, Exception), result
    return result


async def test_two_tills_cannot_both_slip_under_the_limit(two_tenants) -> None:
    (fa, ta), _ = two_tenants
    cid = await _make_customer(fa, ta)
    # limit 500; each sale is 300, so only ONE may succeed however the tills interleave
    results = await asyncio.gather(
        *[_in_tx(fa, ta, lambda s, n=n: S.charge(s, ta, cid, sale_total="300")) for n in range(4)]
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    refused = [r for r in results if isinstance(r, ConflictError)]
    assert len(ok) == 1 and len(refused) == 3, results
    bal = await _in_tx(fa, ta, lambda s: S.balance(s, ta, cid))
    assert bal == D("300.00")


async def test_one_shop_never_sees_anothers_customer_debts(two_tenants) -> None:
    (fa, ta), (fb, tb) = two_tenants
    cid = await _make_customer(fa, ta)
    await _in_tx(fa, ta, lambda s: S.charge(s, ta, cid, sale_total="100"))
    assert await _in_tx(fb, tb, lambda s: S.balance(s, ta, cid)) == D("0.00")
    assert await _in_tx(fb, tb, lambda s: S.statement(s, ta, cid)) == []
    attack = await _in_tx(fb, tb, lambda s: S.take_deposit(s, ta, cid, amount="5"))
    assert isinstance(attack, Exception)

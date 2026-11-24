"""The money half of a POS return and an exchange — the §189 phase-2 gaps, closed.

Every test here asserts a ROW, not a screen: a ``Refund`` against the original payment, an ``out``
row on the drawer ledger, a ``PosSessionReconciliation`` per method at close, a
``PosSessionHandover`` per hand-off. A "the difference is reported" assertion is exactly what was
wrong before, so none of them would pass on the old code.

DB-free tests first (the pure allocation policy), then the DB-backed flows.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.modules.pos.refund import Tender, allocate, allocate_by_method, plan_for

RETURNS_PATH = "/api/v1/pos/sessions/{session_id}/returns"
EXCHANGES_PATH = "/api/v1/pos/sessions/{session_id}/exchanges"


# ------------------------------------------------------- DB-free: the policy --


def test_refund_goes_cash_first_then_the_original_order() -> None:
    """A 250 refund on a 200-cash + 300-card sale: 200 cash, then 50 card."""
    cash = Tender(uuid.uuid4(), "cash", Decimal("200.00"))
    card = Tender(uuid.uuid4(), "card", Decimal("300.00"))
    plan = allocate("250.00", [card, cash])
    assert [(s.method, s.amount) for s in plan.slices] == [
        ("cash", Decimal("200.00")),
        ("card", Decimal("50.00")),
    ]
    assert plan.refunded == Decimal("250.00")
    assert plan.uncollected == Decimal("0.00")
    assert plan.cash == Decimal("200.00")


def test_refund_never_exceeds_what_a_tender_collected() -> None:
    """A tender that already gave back its whole amount is skipped, not overdrawn."""
    cash = Tender(uuid.uuid4(), "cash", Decimal("100.00"), refunded=Decimal("100.00"))
    card = Tender(uuid.uuid4(), "card", Decimal("300.00"))
    plan = allocate("150.00", [cash, card])
    assert [(s.method, s.amount) for s in plan.slices] == [("card", Decimal("150.00"))]


def test_refund_of_value_the_sale_never_collected_is_reported_not_paid() -> None:
    """An on-account sale collected 100 of a 500 invoice: only 100 can come back."""
    cash = Tender(uuid.uuid4(), "cash", Decimal("100.00"))
    plan = allocate("500.00", [cash])
    assert plan.refunded == Decimal("100.00")
    assert plan.uncollected == Decimal("400.00")


def test_no_tenders_means_nothing_is_paid_out() -> None:
    plan = allocate("75.00", [])
    assert plan.slices == ()
    assert plan.refunded == Decimal("0.00")
    assert plan.uncollected == Decimal("75.00")


def test_explicit_refund_cannot_invent_a_method_the_sale_never_used() -> None:
    from app.modules.errors import ValidationError

    cash = Tender(uuid.uuid4(), "cash", Decimal("100.00"))
    with pytest.raises(ValidationError):
        allocate_by_method([("card", "50.00")], [cash])


def test_explicit_refund_cannot_exceed_that_methods_room() -> None:
    from app.modules.errors import ValidationError

    cash = Tender(uuid.uuid4(), "cash", Decimal("100.00"))
    card = Tender(uuid.uuid4(), "card", Decimal("300.00"))
    with pytest.raises(ValidationError):
        allocate_by_method([("cash", "150.00")], [cash, card])


def test_explicit_refund_is_honoured_when_it_fits() -> None:
    cash = Tender(uuid.uuid4(), "cash", Decimal("200.00"))
    card = Tender(uuid.uuid4(), "card", Decimal("300.00"))
    plan = plan_for("100.00", [cash, card], requested=[("card", "100.00")])
    assert [(s.method, s.amount) for s in plan.slices] == [("card", Decimal("100.00"))]
    assert plan.cash == Decimal("0.00")


def test_returns_and_exchanges_are_idempotency_guarded() -> None:
    """A retry of the same request cannot refund twice: the platform refuses the second run."""
    from app.core.idempotency import should_guard

    assert should_guard("POST", "/api/v1/pos/sessions/x/returns") is True
    assert should_guard("POST", "/api/v1/pos/sessions/x/exchanges") is True


# ------------------------------------------------- DB-backed: the flows move --


async def _paid_till(db, tenant_ctx, *, methods=("cash",), opening="0.00"):
    """A till that takes payments, an open day, and a sellable 100.00 variant."""
    from app.modules.pos.profiles import PosProfileService
    from app.modules.pos.service import PosService
    from app.modules.settings.service import SettingsService
    from tests.test_pos_returns import _customer, _register, _sellable_variant, _warehouse

    await SettingsService(db, tenant_ctx.tenant_id).set("pos.take_payments", True)
    warehouse = await _warehouse(db, tenant_ctx)
    register = await _register(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"P{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
        allowed_payment_methods=list(methods),
    )
    shift = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, profile_id=profile.id, opening_float=opening
    )
    variant = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    customer = await _customer(db, tenant_ctx)
    return shift, variant, customer


async def _sale(db, tenant_ctx, shift, variant, customer, *, quantity=1, payments):
    from app.modules.pos.service import PosService

    return await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        shift.register_id,
        items=[{"variant_id": str(variant.id), "quantity": quantity}],
        customer_id=customer.id,
        payments=payments,
    )


async def _refund_rows(db, tenant_ctx):
    from app.modules.orders.models import Refund

    return list(
        (await db.execute(sa.select(Refund).where(Refund.tenant_id == tenant_ctx.tenant_id)))
        .scalars()
        .all()
    )


async def _cash_rows(db, tenant_ctx, session_id):
    from app.modules.pos.models import PosCashMovement

    return list(
        (
            await db.execute(
                sa.select(PosCashMovement).where(
                    PosCashMovement.tenant_id == tenant_ctx.tenant_id,
                    PosCashMovement.session_id == session_id,
                )
            )
        )
        .scalars()
        .all()
    )


async def test_cash_sale_then_cash_return_refunds_and_lowers_the_drawer(db, tenant_ctx):
    """The report's first closure test: a 500 cash sale, a 100 return, the drawer drops 100."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=5,
        payments=[{"method": "cash", "amount": "500.00"}],
    )
    before = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    assert Decimal(before["expected_cash"]) == Decimal("500.00")

    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )

    assert Decimal(result["refunded"]) == Decimal("100.00")
    assert result["refund_mode"] == "tender"
    assert result["refund_by_method"] == {"cash": "100.00"}

    refunds = await _refund_rows(db, tenant_ctx)
    assert len(refunds) == 1
    assert Decimal(str(refunds[0].amount)) == Decimal("100.00")
    assert refunds[0].status == "processed"

    after = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    assert Decimal(after["expected_cash"]) == Decimal("400.00")
    out_rows = [row for row in await _cash_rows(db, tenant_ctx, shift.id) if row.direction == "out"]
    assert [(row.reason, Decimal(str(row.amount))) for row in out_rows] == [
        ("cash_refund", Decimal("100.00"))
    ]


async def test_split_tender_return_is_split_across_the_original_methods(db, tenant_ctx):
    """200 cash + 300 card, a 250 return: 200 comes out of the drawer, 50 reverses the card."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=5,
        payments=[
            {"method": "cash", "amount": "200.00"},
            {"method": "card", "amount": "300.00", "reference": "AUTH-1"},
        ],
    )

    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[
            {"variant_id": str(variant.id), "quantity": 1},
            {"variant_id": str(variant.id), "quantity": 1},
        ],
        refund=None,
    )
    # 2 pieces back = 200.00, all of it cash-first.
    assert result["refund_by_method"] == {"cash": "200.00"}

    second = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    # The third piece: the cash tender is exhausted, so 100 goes back on the card.
    # A pending reversal is not money returned: it is named as awaiting, not as refunded.
    assert second["refund_by_method"] == {}
    assert second["awaiting_confirmation"][0]["method"] == "card"
    assert second["awaiting_confirmation"][0]["amount"] == "100.00"
    assert second["refund_mode"] == "tender"

    summary = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    # Only the cash leg touches the drawer: 200 came in, 200 went back out, so it is empty. The
    # 300 the card collected never entered it, and the 100 card refund never left it.
    assert Decimal(summary["expected_cash"]) == Decimal("0.00")
    assert summary["by_method"] == {"cash": "200.00", "card": "300.00"}


async def test_successive_partial_refunds_on_one_tender_keep_working(db, tenant_ctx):
    """The report's own scenario: 1,000 cash, 200 back, then 300 back.

    The first partial refund flips the payment to ``partially_refunded``. While the lookup matched
    ``captured`` only, the second return found no tender and reported the money as never collected.
    """
    from app.modules.orders.models import OrderPayment
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=10,
        payments=[{"method": "cash", "amount": "1000.00"}],
    )
    first = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 2}],
    )
    assert Decimal(first["refunded"]) == Decimal("200.00")
    payment = (
        await db.execute(sa.select(OrderPayment).where(OrderPayment.order_id == sold["order_id"]))
    ).scalar_one()
    assert payment.status == "partially_refunded"

    second = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 3}],
    )
    assert Decimal(second["refunded"]) == Decimal("300.00")
    assert second["refund_by_method"] == {"cash": "300.00"}
    assert second["refund_mode"] == "tender"

    summary = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    assert Decimal(summary["expected_cash"]) == Decimal("500.00")
    assert len(await _refund_rows(db, tenant_ctx)) == 2


async def test_a_card_refund_waits_for_the_terminal_reference(db, tenant_ctx):
    """A card reversal happens on the terminal, so writing the row is not the money going back."""
    from app.modules.orders.models import OrderPayment
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[{"method": "card", "amount": "200.00", "reference": "AUTH-9"}],
    )
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    assert result["refund_by_method"] == {}
    assert result["awaiting_confirmation"][0]["method"] == "card"
    assert result["awaiting_confirmation"] == [
        {
            "refund_id": result["awaiting_confirmation"][0]["refund_id"],
            "method": "card",
            "amount": "100.00",
        }
    ]

    rows = await _refund_rows(db, tenant_ctx)
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].external_reference is None
    assert rows[0].processed_at is None
    # Nothing derived has moved yet: the card still holds the money.
    payment = (
        await db.execute(sa.select(OrderPayment).where(OrderPayment.order_id == sold["order_id"]))
    ).scalar_one()
    assert payment.status == "captured"

    confirmed = await PosService.confirm_refund(db, tenant_ctx.tenant_id, rows[0].id, "RRN-778812")
    assert confirmed["status"] == "processed"
    assert confirmed["external_reference"] == "RRN-778812"
    assert confirmed["payment_status"] == "partially_refunded"
    await db.refresh(rows[0])
    assert rows[0].external_reference == "RRN-778812"
    assert rows[0].processed_at is not None


async def test_a_reference_typed_up_front_never_leaves_a_pending_row(db, tenant_ctx):
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "card", "amount": "100.00", "reference": "AUTH-1"}],
    )
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        refund_references={"card": "RRN-000111"},
    )
    assert result["awaiting_confirmation"] == []
    rows = await _refund_rows(db, tenant_ctx)
    assert [(row.status, row.external_reference) for row in rows] == [("processed", "RRN-000111")]


async def test_confirming_a_refund_needs_a_reference_and_happens_once(db, tenant_ctx):
    from app.modules.errors import ConflictError, ValidationError
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "card", "amount": "100.00", "reference": "AUTH-2"}],
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    refund = (await _refund_rows(db, tenant_ctx))[0]
    with pytest.raises(ValidationError):
        await PosService.confirm_refund(db, tenant_ctx.tenant_id, refund.id, "   ")
    await PosService.confirm_refund(db, tenant_ctx.tenant_id, refund.id, "RRN-1")
    with pytest.raises(ConflictError):
        await PosService.confirm_refund(db, tenant_ctx.tenant_id, refund.id, "RRN-2")


async def test_a_cash_only_shop_reports_the_card_reversal_instead_of_recording_it(db, tenant_ctx):
    """A shop that starts cash-only cannot reverse a card, so the till must not pretend it did."""
    from app.modules.pos.service import PosService
    from app.modules.settings.service import SettingsService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.refund_cash_only", True)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "card", "amount": "100.00", "reference": "AUTH-3"}],
    )
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    assert result["refund_mode"] == "cash_only"
    assert result["refunded"] == "0.00"
    assert result["terminal_only"] == [{"method": "card", "amount": "100.00"}]
    # Recorded as a pending manual reversal: described AND provable, still not money returned.
    (row,) = await _refund_rows(db, tenant_ctx)
    assert row.status == "pending"
    assert Decimal(str(row.amount)) == Decimal("100.00")
    assert result["awaiting_confirmation"][0]["refund_id"] == str(row.id)


async def test_a_second_return_cannot_refund_the_same_piece_twice(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    with pytest.raises(ConflictError):
        await PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )
    refunds = await _refund_rows(db, tenant_ctx)
    assert len(refunds) == 1


async def test_exchange_for_a_dearer_item_collects_the_difference(db, tenant_ctx):
    """A 100 shirt swapped for a 130 one: 30 is collected and lands in the drawer."""
    from app.modules.pos.service import PosService
    from tests.test_pos_returns import _sellable_variant

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    dearer = await _sellable_variant(db, tenant_ctx, price="130.00", stock=10)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )

    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(dearer.id), "quantity": 1}],
        payments=[{"method": "cash", "amount": "30.00"}],
    )

    assert result["settlement"] == "collected"
    assert Decimal(result["settled_amount"]) == Decimal("30.00")
    summary = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    # 100 in for the sale, 30 in for the difference, nothing out.
    assert Decimal(summary["expected_cash"]) == Decimal("130.00")


async def test_exchange_for_a_cheaper_item_refunds_the_difference(db, tenant_ctx):
    from app.modules.pos.service import PosService
    from tests.test_pos_returns import _sellable_variant

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    cheaper = await _sellable_variant(db, tenant_ctx, price="70.00", stock=10)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )

    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(cheaper.id), "quantity": 1}],
    )

    assert result["settlement"] == "refunded"
    assert Decimal(result["settled_amount"]) == Decimal("30.00")
    summary = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    assert Decimal(summary["expected_cash"]) == Decimal("70.00")


async def test_an_even_exchange_moves_no_money_and_says_so(db, tenant_ctx):
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )

    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )

    assert result["settlement"] == "exchange_only"
    assert Decimal(result["settled_amount"]) == Decimal("0.00")
    summary = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    assert Decimal(summary["expected_cash"]) == Decimal("100.00")


async def test_a_dearer_exchange_without_a_payment_is_refused(db, tenant_ctx):
    """The old behaviour (report the difference, collect nothing) is now a 422."""
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService
    from tests.test_pos_returns import _sellable_variant

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    dearer = await _sellable_variant(db, tenant_ctx, price="130.00", stock=10)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )

    with pytest.raises(ValidationError):
        await PosService.exchange(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            order_id=sold["order_id"],
            return_lines=[{"variant_id": str(variant.id), "quantity": 1}],
            new_lines=[{"variant_id": str(dearer.id), "quantity": 1}],
        )


async def test_close_settles_every_method_the_day_collected(db, tenant_ctx):
    """Card is counted like cash: expected vs counted vs the difference, one row per method."""
    from app.modules.pos.models import PosSessionReconciliation
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[
            {"method": "cash", "amount": "100.00"},
            {"method": "card", "amount": "100.00", "reference": "AUTH-9"},
        ],
    )

    closed = await PosService.close_session(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        counted_cash="100.00",
        counted_methods={"card": "90.00"},
        variance_reason="الماكينة خصمت عمولة",
    )

    rows = {
        row.method: row
        for row in (
            await db.execute(
                sa.select(PosSessionReconciliation).where(
                    PosSessionReconciliation.session_id == closed.id
                )
            )
        )
        .scalars()
        .all()
    }
    assert set(rows) == {"cash", "card"}
    assert Decimal(str(rows["card"].expected_amount)) == Decimal("100.00")
    assert Decimal(str(rows["card"].counted_amount)) == Decimal("90.00")
    assert Decimal(str(rows["card"].variance)) == Decimal("-10.00")
    assert Decimal(str(rows["cash"].variance)) == Decimal("0.00")


async def test_the_close_route_carries_the_method_counts(db, tenant_ctx):
    """The report's §2.3: the service settled every method, but the route could not receive them."""
    import sqlalchemy as sa

    from app.modules.pos.models import PosSessionReconciliation
    from app.modules.pos.router import CloseSessionRequest, close_session

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[
            {"method": "cash", "amount": "100.00"},
            {"method": "card", "amount": "100.00", "reference": "AUTH-7"},
        ],
    )

    class Ctx:
        session = db
        tenant_id = tenant_ctx.tenant_id

        class user:
            id = tenant_ctx.user.id

    class Override:
        active = True

    closed = await close_session(
        shift.id,
        Ctx(),
        Override(),
        CloseSessionRequest(counted_cash="100.00", counted_methods={"card": "95.00"}),
    )
    rows = {
        row.method: row
        for row in (
            (
                await db.execute(
                    sa.select(PosSessionReconciliation).where(
                        PosSessionReconciliation.session_id == shift.id
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    assert closed["status"] == "CLOSED"
    assert Decimal(str(rows["card"].counted_amount)) == Decimal("95.00")
    assert Decimal(str(rows["card"].variance)) == Decimal("-5.00")


async def test_close_refuses_to_skip_an_uncounted_card_when_the_shop_requires_it(db, tenant_ctx):
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService
    from app.modules.settings.service import SettingsService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.settle_payment_methods", True)
    await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[
            {"method": "cash", "amount": "50.00"},
            {"method": "card", "amount": "50.00", "reference": "AUTH-2"},
        ],
    )

    with pytest.raises(ValidationError):
        await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="50.00")


async def test_handover_records_a_custody_snapshot_per_cashier(db, tenant_ctx):
    """The drawer is counted at the hand-off, and the shortage is pinned on that moment."""
    from app.modules.pos.models import PosSessionHandover
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, opening="100.00")
    await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )

    handed = await PosService.handover_session(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        new_cashier_id=tenant_ctx.user.id,
        actor_user_id=tenant_ctx.user.id,
        counted_cash="180.00",
        variance_reason="نقص 20",
    )

    row = (
        (
            await db.execute(
                sa.select(PosSessionHandover).where(PosSessionHandover.session_id == handed.id)
            )
        )
        .scalars()
        .one()
    )
    assert Decimal(str(row.expected_cash)) == Decimal("200.00")
    assert Decimal(str(row.counted_cash)) == Decimal("180.00")
    assert Decimal(str(row.variance)) == Decimal("-20.00")
    assert row.to_user_id == tenant_ctx.user.id
    assert row.note == "نقص 20"


async def test_handover_refuses_to_move_a_drawer_nobody_counted(db, tenant_ctx):
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    shift, _variant, _customer_row = await _paid_till(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await PosService.handover_session(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            new_cashier_id=tenant_ctx.user.id,
            actor_user_id=tenant_ctx.user.id,
        )


# ------------------------------------------- DB-backed: no silent record-only --


async def _apparel_shop_that_skipped_setup(db, tenant_ctx):
    """An apparel shop whose owner tapped 'skip' on the setup: no preset, so no payments."""
    from app.core.activity_setup import mark_not_started, skip_setup
    from app.modules.settings.service import SettingsService

    await mark_not_started(db, tenant_ctx.tenant_id)
    await SettingsService(db, tenant_ctx.tenant_id).set("business.vertical", "apparel")
    await skip_setup(db, tenant_ctx.tenant_id, user_id=tenant_ctx.user.id)


async def test_an_apparel_shop_that_skipped_setup_cannot_sell_without_collecting(db, tenant_ctx):
    """§2.3: the sale that looks normal and records no money is refused."""
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    await _apparel_shop_that_skipped_setup(db, tenant_ctx)
    shift, variant, customer = await _paid_till(db, tenant_ctx)
    # The till above turned payments on for its own profile; turn the shop switch back off so this
    # is the skipped-setup state the report describes.
    from app.modules.settings.service import SettingsService

    await SettingsService(db, tenant_ctx.tenant_id).set("pos.take_payments", False)

    mode = await PosService.payments_mode(db, tenant_ctx.tenant_id, shift)
    assert mode["mode"] == "record_only"
    assert mode["apparel_setup_incomplete"] is True

    with pytest.raises(ValidationError, match="records sales but no payments"):
        await _sale(db, tenant_ctx, shift, variant, customer, payments=[])


async def test_record_only_selling_is_allowed_once_the_owner_says_so(db, tenant_ctx):
    from app.modules.settings.service import SettingsService

    await _apparel_shop_that_skipped_setup(db, tenant_ctx)
    shift, variant, customer = await _paid_till(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.take_payments", False)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.allow_record_only_sales", True)

    sold = await _sale(db, tenant_ctx, shift, variant, customer, payments=[])
    assert sold["paid"] is None


async def test_a_shop_on_another_vertical_is_not_blocked(db, tenant_ctx):
    """The guard is for the apparel shop that never chose record-only, not a blanket rule."""
    from app.modules.pos.service import PosService
    from app.modules.settings.service import SettingsService

    await SettingsService(db, tenant_ctx.tenant_id).set("business.vertical", "general")
    shift, variant, customer = await _paid_till(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.take_payments", False)

    mode = await PosService.payments_mode(db, tenant_ctx.tenant_id, shift)
    assert mode["mode"] == "record_only"
    assert mode["apparel_setup_incomplete"] is False
    sold = await _sale(db, tenant_ctx, shift, variant, customer, payments=[])
    assert sold["paid"] is None


# ------------------------------------------------------- DB-backed: the void --


async def test_a_confirmed_sale_can_be_voided_and_nothing_is_deleted(db, tenant_ctx):
    """§5.1: wrong size rung up. Stock back, money back, a POS-VOID- document, history intact."""
    from app.modules.inventory.service import InventoryService
    from app.modules.pos.models import PosCashMovement, PosReceipt
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, opening="0.00")
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[{"method": "cash", "amount": "200.00"}],
    )
    assert await InventoryService.total_on_hand(db, tenant_ctx.tenant_id, variant.id) == 48

    result = await PosService.void_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        reason="المقاس غلط",
        actor_user_id=tenant_ctx.user.id,
        shift_override=True,
    )

    assert result["void_receipt_number"].startswith("POS-VOID-")
    assert result["reason"] == "المقاس غلط"
    assert Decimal(result["refunded"]) == Decimal("200.00")
    assert result["refund_by_method"] == {"cash": "200.00"}

    # The goods are back on the shelf.
    assert await InventoryService.total_on_hand(db, tenant_ctx.tenant_id, variant.id) == 50

    # The sale receipt and its cash-in row are still there; the void added its own rows.
    receipts = list(
        (await db.execute(sa.select(PosReceipt).where(PosReceipt.order_id == sold["order_id"])))
        .scalars()
        .all()
    )
    assert sorted(r.kind for r in receipts) == ["sale", "void"]
    summary = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    assert Decimal(summary["expected_cash"]) == Decimal("0.00")
    rows = await _cash_rows(db, tenant_ctx, shift.id)
    assert sorted((r.direction, r.reason) for r in rows) == [
        ("in", "cash_sale"),
        ("out", "cash_refund"),
    ]
    assert PosCashMovement is not None


async def test_a_voided_sale_is_not_counted_in_the_shift_or_the_day(db, tenant_ctx):
    """The shift's own total and the day's rollup must agree with what was actually sold.

    The receipt of a voided sale is kept for the audit trail, so counting "every kind='sale'
    receipt" made the Z report and the daily row still include a sale the shop had just voided -
    the owner's takings would be higher than the drawer and the bank.
    """
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, opening="0.00")
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "cash", "amount": "100.00"}],
    )
    await PosService.void_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        reason="المقاس غلط",
        actor_user_id=tenant_ctx.user.id,
        shift_override=True,
    )
    closed = await PosService.close_session(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        closed_by=tenant_ctx.user.id,
        counted_cash="0.00",
    )
    await db.flush()

    # The day's projection is rebuilt from the ledgers; the voided sale must not be in it.
    from app.modules.analytics.timekit import merchant_day
    from app.modules.pos.models import PosDailySales

    day = merchant_day(closed.closed_at, await PosService._shop_timezone(db, tenant_ctx.tenant_id))
    assert (
        await PosService.upsert_daily_projection(db, tenant_ctx.tenant_id, business_date=day) == 1
    )
    row = (
        await db.execute(
            sa.select(PosDailySales).where(PosDailySales.tenant_id == tenant_ctx.tenant_id)
        )
    ).scalar_one()
    assert row.invoice_count == 0
    assert Decimal(str(row.sales_total)) == Decimal("0.00")


async def test_a_void_needs_a_manager_override(db, tenant_ctx):
    from app.modules.errors import PermissionDeniedError
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    with pytest.raises(PermissionDeniedError):
        await PosService.void_sale(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            order_id=sold["order_id"],
            reason="x",
            actor_user_id=tenant_ctx.user.id,
        )


async def test_a_void_needs_a_reason(db, tenant_ctx):
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    with pytest.raises(ValidationError):
        await PosService.void_sale(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            order_id=sold["order_id"],
            reason="   ",
            actor_user_id=tenant_ctx.user.id,
            shift_override=True,
        )


async def test_a_sale_cannot_be_voided_twice(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    await PosService.void_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        reason="x",
        actor_user_id=tenant_ctx.user.id,
        shift_override=True,
    )
    with pytest.raises(ConflictError):
        await PosService.void_sale(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            order_id=sold["order_id"],
            reason="x",
            actor_user_id=tenant_ctx.user.id,
            shift_override=True,
        )


async def test_a_partly_returned_sale_is_finished_as_a_return_not_a_void(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[{"method": "cash", "amount": "200.00"}],
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    with pytest.raises(ConflictError):
        await PosService.void_sale(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            order_id=sold["order_id"],
            reason="x",
            actor_user_id=tenant_ctx.user.id,
            shift_override=True,
        )


def test_the_void_route_is_mounted() -> None:
    from app.main import create_app

    assert "/api/v1/pos/sessions/{session_id}/voids" in set(create_app().openapi()["paths"])


# ------------------------------------------------- DB-backed: returned condition --


async def _balance(db, tenant_ctx, variant, warehouse_id):
    from app.modules.inventory.models import InventoryBalance

    return (
        await db.execute(
            sa.select(InventoryBalance).where(
                InventoryBalance.tenant_id == tenant_ctx.tenant_id,
                InventoryBalance.variant_id == variant.id,
                InventoryBalance.warehouse_id == warehouse_id,
            )
        )
    ).scalar_one()


async def test_a_sellable_return_goes_back_on_the_shelf(db, tenant_ctx):
    from app.modules.pos.service import PosService
    from tests.test_pos_returns import _warehouse

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    warehouse = await _warehouse(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1, "condition": "sellable"}],
    )
    balance = await _balance(db, tenant_ctx, variant, warehouse.id)
    assert int(balance.on_hand) == 50
    assert int(balance.quarantined or 0) == 0


async def test_a_damaged_return_is_in_the_shop_but_never_offered_to_a_customer(db, tenant_ctx):
    """§7.1: the torn dress is physically back, and availability must not count it."""
    from app.modules.pos.service import PosService
    from tests.test_pos_returns import _warehouse

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    warehouse = await _warehouse(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1, "condition": "damaged"}],
    )
    balance = await _balance(db, tenant_ctx, variant, warehouse.id)
    # It is in the shop (on_hand 50) and every unit of it is quarantined, so sellable is 49.
    assert int(balance.on_hand) == 50
    assert int(balance.quarantined or 0) == 1
    assert int(balance.on_hand) - int(balance.quarantined or 0) == 49


async def test_a_written_off_return_is_not_stock_at_all(db, tenant_ctx):
    from app.modules.pos.service import PosService
    from tests.test_pos_returns import _warehouse

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    warehouse = await _warehouse(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1, "condition": "writeoff"}],
    )
    # The money still goes back; the unit does not return to stock.
    assert Decimal(result["refunded"]) == Decimal("100.00")
    balance = await _balance(db, tenant_ctx, variant, warehouse.id)
    assert int(balance.on_hand) == 49


async def test_a_supplier_return_is_not_stock_and_keeps_the_condition_on_the_line(db, tenant_ctx):
    from app.modules.pos.models import PosReturnLine
    from app.modules.pos.service import PosService
    from tests.test_pos_returns import _warehouse

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    warehouse = await _warehouse(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1, "condition": "supplier"}],
    )
    balance = await _balance(db, tenant_ctx, variant, warehouse.id)
    assert int(balance.on_hand) == 49
    line = (
        await db.execute(
            sa.select(PosReturnLine).where(PosReturnLine.receipt_id == result["receipt_id"])
        )
    ).scalar_one()
    assert line.condition == "supplier"


async def test_an_unknown_condition_is_refused(db, tenant_ctx):
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db, tenant_ctx, shift, variant, customer, payments=[{"method": "cash", "amount": "100.00"}]
    )
    with pytest.raises(ValidationError, match="condition must be one of"):
        await PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1, "condition": "melted"}],
        )


# ---------------------------------------------------------------- void: the books ---


@pytest.mark.asyncio
async def test_a_void_gives_the_cost_layer_back_so_the_shelf_is_worth_something(db, tenant_ctx):
    """The sale consumed a FIFO layer. A void that only adds quantity leaves stock worth zero,
    and the next sale books a cost of nothing - so the layer comes back at the sold unit cost."""
    from app.modules.inventory.services.valuation import ValuationService
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    # Stock that arrived at 40.00 a piece: the layer the sale will consume.
    warehouse_id = await _warehouse_of(db, tenant_ctx, shift)
    await ValuationService.create_cost_layer(
        db,
        tenant_ctx.tenant_id,
        variant_id=variant.id,
        warehouse_id=warehouse_id,
        quantity=50,
        unit_cost="40.00",
        source_type="opening",
    )
    sale = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[{"method": "cash", "amount": "200.00"}],
    )

    before = await ValuationService.calculate_valuation(
        db, tenant_ctx.tenant_id, variant_id=variant.id
    )
    await PosService.void_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sale["order_id"] if isinstance(sale, dict) else sale.order_id,
        reason="اتسجلت مرتين",
        actor_user_id=tenant_ctx.user.id,
        shift_override=True,
    )
    after = await ValuationService.calculate_valuation(
        db, tenant_ctx.tenant_id, variant_id=variant.id
    )

    # Two pieces came back at the cost they left with: the shelf's value is restored, not zero.
    assert Decimal(str(after["total_valuation"])) > Decimal(str(before["total_valuation"]))
    layers = await ValuationService.get_active_layers(
        db,
        tenant_ctx.tenant_id,
        variant_id=variant.id,
        warehouse_id=await _warehouse_of(db, tenant_ctx, shift),
    )
    assert any(layer.source_type == "void" for layer in layers)


async def _warehouse_of(db, tenant_ctx, shift):
    from app.modules.pos.models import PosRegister

    register = (
        await db.execute(sa.select(PosRegister).where(PosRegister.id == shift.register_id))
    ).scalar_one()
    return register.warehouse_id


@pytest.mark.asyncio
async def test_a_voided_sale_leaves_the_days_sales_and_the_shift_report(db, tenant_ctx):
    """Revenue the shop never kept must not appear as revenue, and the void is its own document."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sale = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "cash", "amount": "100.00"}],
    )
    order_id = sale["order_id"] if isinstance(sale, dict) else sale.order_id

    before = await PosService.session_report(db, tenant_ctx.tenant_id, shift.id)
    assert before["sales"]["invoice_count"] == 1

    voided = await PosService.void_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=order_id,
        reason="المقاس غلط",
        actor_user_id=tenant_ctx.user.id,
        shift_override=True,
    )
    after = await PosService.session_report(db, tenant_ctx.tenant_id, shift.id)

    assert after["sales"]["invoice_count"] == 0
    assert Decimal(after["sales"]["total"]) == Decimal("0.00")
    assert after["voids"]["void_count"] == 1
    assert after["voids"]["documents"][0]["receipt_number"] == voided["void_receipt_number"]
    # The void is NOT a return: the return report stays empty.
    assert after["returns"]["return_count"] == 0


@pytest.mark.asyncio
async def test_a_voided_sale_is_not_profit(db, tenant_ctx):
    """Profit is revenue minus cost. A reversed sale contributes neither."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sale = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "cash", "amount": "100.00"}],
    )
    order_id = sale["order_id"] if isinstance(sale, dict) else sale.order_id
    await PosService.void_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=order_id,
        reason="غلط في الصنف",
        actor_user_id=tenant_ctx.user.id,
        shift_override=True,
    )

    from app.modules.orders.models import Order

    status = (await db.execute(sa.select(Order.status).where(Order.id == order_id))).scalar_one()
    # The profit report excludes cancelled orders, so the reversal reaches it through the status.
    assert status == "cancelled"


# ----------------------------------- the refund's derived writes (P1) ----
# A POS refund wrote the Refund rows and the drawer movement but left the reversed PAYMENT saying
# "captured" and the customer still worth the money the shop had given back. These assert the two
# derived facts the shared refund path has always written.


async def _payment_rows(db, tenant_ctx, order_id):
    from app.modules.orders.models import OrderPayment

    return list(
        (
            await db.execute(
                sa.select(OrderPayment).where(
                    OrderPayment.tenant_id == tenant_ctx.tenant_id,
                    OrderPayment.order_id == order_id,
                )
            )
        )
        .scalars()
        .all()
    )


async def _customer_worth(db, tenant_ctx, customer_id):
    from app.modules.customers.models import Customer

    await db.flush()
    return Decimal(
        str(
            (
                await db.execute(
                    sa.select(Customer.lifetime_value).where(
                        Customer.tenant_id == tenant_ctx.tenant_id,
                        Customer.id == customer_id,
                    )
                )
            ).scalar_one()
        )
    )


async def _order_status(db, tenant_ctx, order_id):
    from app.modules.orders.models import Order

    await db.flush()
    return (
        await db.execute(
            sa.select(Order.status).where(
                Order.tenant_id == tenant_ctx.tenant_id, Order.id == order_id
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_a_partial_return_marks_the_payment_partially_refunded_and_lowers_the_customer(
    db, tenant_ctx
):
    """2 pieces sold for 200 cash, 1 came back: the payment is partially refunded, worth 100."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[{"method": "cash", "amount": "200.00"}],
    )
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("200.00")

    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )

    payments = await _payment_rows(db, tenant_ctx, sold["order_id"])
    assert [p.status for p in payments] == ["partially_refunded"]
    # The customer is worth what is left of the money, not what was once collected.
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("100.00")
    # A partial return is not a refunded sale, and the sale keeps its status.
    assert await _order_status(db, tenant_ctx, sold["order_id"]) == "confirmed"


@pytest.mark.asyncio
async def test_returning_the_whole_sale_refunds_the_payment_and_the_order(db, tenant_ctx):
    """The whole 200 came back: the payment reads refunded and the sale is no longer "completed"."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[{"method": "cash", "amount": "200.00"}],
    )

    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 2}],
    )

    payments = await _payment_rows(db, tenant_ctx, sold["order_id"])
    assert [p.status for p in payments] == ["refunded"]
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("0.00")
    # The SALE keeps its own status: a till sale never enters the completed lifecycle, and its
    # revenue is offset by the return document itself (which is what the day totals and the
    # shift report read). A status rewrite here would double-count the reversal.
    assert await _order_status(db, tenant_ctx, sold["order_id"]) == "confirmed"


@pytest.mark.asyncio
async def test_a_cheaper_exchange_refunds_its_difference_on_the_customer_too(db, tenant_ctx):
    """A cheaper replacement gives back the difference: the payment and the worth follow it."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx)
    cheap = await _sellable_variant_of(db, tenant_ctx, price="60.00", stock=20)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[{"method": "cash", "amount": "200.00"}],
    )
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("200.00")

    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(variant.id), "quantity": 2}],
        new_lines=[{"variant_id": str(cheap.id), "quantity": 2}],
        actor_user_id=tenant_ctx.user.id,
    )
    assert result["settlement"] == "refunded"
    assert Decimal(result["settled_amount"]) == Decimal("80.00")

    payments = await _payment_rows(db, tenant_ctx, sold["order_id"])
    assert [p.status for p in payments] == ["partially_refunded"]
    # 200 collected - 80 given back = 120 kept.
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("120.00")


async def _sellable_variant_of(db, tenant_ctx, *, price, stock):
    from tests.test_pos_returns import _sellable_variant

    return await _sellable_variant(db, tenant_ctx, price=price, stock=stock)


@pytest.mark.asyncio
async def test_the_confirm_route_records_the_terminal_reference(db, tenant_ctx) -> None:
    """The endpoint the returns screen calls after the cashier reverses on the machine."""
    from pydantic import ValidationError as ModelValidationError

    from app.modules.pos.router import ConfirmRefundRequest, confirm_refund
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "card", "amount": "100.00", "reference": "AUTH-4"}],
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    refund = (await _refund_rows(db, tenant_ctx))[0]

    class Ctx:
        session = db
        tenant_id = tenant_ctx.tenant_id

        class user:
            id = tenant_ctx.user.id

    class Override:
        active = True

    with pytest.raises(ModelValidationError):
        # The route model refuses an empty reference before the service is even reached.
        ConfirmRefundRequest(external_reference="")

    out = await confirm_refund(
        refund.id, ConfirmRefundRequest(external_reference="RRN-4242"), Ctx(), Override()
    )
    assert out["status"] == "processed"
    assert out["external_reference"] == "RRN-4242"
    # The whole tender came back, so the payment is fully refunded, not partially.
    assert out["payment_status"] == "refunded"


@pytest.mark.asyncio
async def test_a_partly_refunded_sale_is_not_marked_fully_refunded(db, tenant_ctx) -> None:
    """The report's blocker 1: the state was read off the touched tenders, not the whole sale.

    A 1,000 sale (100 cash + 900 card) whose 100 cash comes back still holds 900. Calling the sale
    "refunded" dropped it out of revenue with the card money unaccounted for.
    """
    from app.modules.orders.models import Order, OrderPayment, Refund
    from app.modules.orders.service import OrderService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=10,
        payments=[
            {"method": "cash", "amount": "100.00"},
            {"method": "card", "amount": "900.00", "reference": "AUTH-9"},
        ],
    )
    order = (
        await db.execute(sa.select(Order).where(Order.id == uuid.UUID(str(sold["order_id"]))))
    ).scalar_one()
    # A completed sale is the case the rule protects: it must not flip while money is still held.
    order.status = "completed"
    payments = {
        row.method: row
        for row in (
            await db.execute(sa.select(OrderPayment).where(OrderPayment.order_id == order.id))
        )
        .scalars()
        .all()
    }
    cash, card = payments["cash"], payments["card"]

    db.add(
        Refund(
            tenant_id=tenant_ctx.tenant_id,
            payment_id=cash.id,
            amount=Decimal("100.00"),
            reason="مرتجع جزئي",
            status="processed",
        )
    )
    await db.flush()
    await OrderService.apply_refunded_payment_states(db, tenant_ctx.tenant_id, order, [cash.id])
    await db.refresh(order)
    assert order.status == "completed", "900 card is still paid and never returned"
    assert cash.status == "refunded"
    assert card.status == "captured"

    # Now the card comes back too: only then is the sale refunded.
    db.add(
        Refund(
            tenant_id=tenant_ctx.tenant_id,
            payment_id=card.id,
            amount=Decimal("900.00"),
            reason="مرتجع جزئي",
            status="processed",
        )
    )
    await db.flush()
    await OrderService.apply_refunded_payment_states(db, tenant_ctx.tenant_id, order, [card.id])
    await db.refresh(order)
    assert order.status == "refunded"


@pytest.mark.asyncio
async def test_cash_only_shop_is_told_this_refunds_card_part_not_the_whole_card(
    db, tenant_ctx
) -> None:
    """The report's blocker 3: terminal_only was the tender's whole room, not this refund's share.

    100 on card, a 30 return: the cashier has to reverse 30 on the machine, not 100.
    """
    from app.modules.pos.service import PosService
    from app.modules.settings.service import SettingsService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.refund_cash_only", True)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "card", "amount": "100.00", "reference": "AUTH-3"}],
    )
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        refund=[{"method": "card", "amount": "30.00"}],
    )
    assert out["refund_mode"] == "cash_only"
    assert out["terminal_only"] == [{"method": "card", "amount": "30.00"}]
    assert out["refunded"] == "0.00"
    (row,) = await _refund_rows(db, tenant_ctx)
    assert row.status == "pending"
    assert out["awaiting_confirmation"][0]["refund_id"] == str(row.id)


@pytest.mark.asyncio
async def test_a_pending_reversal_survives_a_page_reload(db, tenant_ctx) -> None:
    """The report's blocker 2: the promise lived in useState, so a refresh lost the money."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "card", "amount": "100.00", "reference": "AUTH-7"}],
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    pending = await PosService.list_pending_refunds(db, tenant_ctx.tenant_id)
    assert len(pending) == 1
    assert pending[0]["method"] == "card"
    assert pending[0]["amount"] == "100.00"
    assert pending[0]["order_id"] == str(sold["order_id"])
    assert pending[0]["order_number"], "the cashier has to know which invoice is owed"

    await PosService.confirm_refund(
        db, tenant_ctx.tenant_id, uuid.UUID(pending[0]["refund_id"]), "RRN-5150"
    )
    # Once confirmed it is no longer owed, so it leaves the list.
    assert await PosService.list_pending_refunds(db, tenant_ctx.tenant_id) == []


@pytest.mark.asyncio
async def test_a_void_reports_the_card_reversal_it_left_pending(db, tenant_ctx) -> None:
    """The report's blocker 2, void path: the answer did not carry awaiting_confirmation."""
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "card", "amount": "100.00", "reference": "AUTH-8"}],
    )
    out = await PosService.void_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        reason="رن على الصنف الغلط",
        actor_user_id=tenant_ctx.user.id,
        shift_override=True,
    )
    (pending,) = out["awaiting_confirmation"]
    assert pending["method"] == "card"
    assert pending["amount"] == "100.00"
    assert out["terminal_only"] == []


@pytest.mark.asyncio
async def test_a_pending_reversal_does_not_lower_the_customer_value(db, tenant_ctx) -> None:
    """The report's blocker 1: pending was subtracted from the customer's value as if it went back.

    1,000 on card, a 300 return the machine has not confirmed: the customer still paid 1,000 and
    ``refund_position`` must not call the invoice refunded.
    """
    from app.modules.orders.service import OrderService
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=10,
        payments=[{"method": "card", "amount": "1000.00", "reference": "AUTH-1"}],
    )
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("1000.00")

    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 3}],
    )
    assert out["refunded"] == "0.00"
    assert len(out["awaiting_confirmation"]) == 1

    # Nothing moved: the promise is not the payment.
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("1000.00")
    position = await OrderService.refund_position(
        db, tenant_ctx.tenant_id, uuid.UUID(str(sold["order_id"]))
    )
    assert Decimal(str(position["refunded"])) == Decimal("0.00")
    assert position["refund_state"] != "refunded"

    # Confirming the terminal's reference is what makes it money returned.
    await PosService.confirm_refund(
        db,
        tenant_ctx.tenant_id,
        uuid.UUID(out["awaiting_confirmation"][0]["refund_id"]),
        "RRN-300",
    )
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("700.00")
    position = await OrderService.refund_position(
        db, tenant_ctx.tenant_id, uuid.UUID(str(sold["order_id"]))
    )
    assert Decimal(str(position["refunded"])) == Decimal("300.00")


@pytest.mark.asyncio
async def test_cash_only_records_the_manual_reversal_as_a_pending_row(db, tenant_ctx) -> None:
    """The report's blocker 3: terminal_only was described in the answer and recorded nowhere."""
    from app.modules.orders.service import OrderService
    from app.modules.pos.service import PosService
    from app.modules.settings.service import SettingsService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.refund_cash_only", True)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        payments=[{"method": "card", "amount": "100.00", "reference": "AUTH-2"}],
    )
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        refund=[{"method": "card", "amount": "30.00"}],
    )
    assert out["refund_mode"] == "cash_only"
    assert out["terminal_only"] == [{"method": "card", "amount": "30.00"}]
    assert out["refunded"] == "0.00"
    # The proof exists before the cashier touches the terminal, and it is not money returned yet.
    (row,) = await _refund_rows(db, tenant_ctx)
    assert row.status == "pending"
    assert Decimal(str(row.amount)) == Decimal("30.00")
    assert out["awaiting_confirmation"][0]["refund_id"] == str(row.id)
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("100.00")

    await PosService.confirm_refund(db, tenant_ctx.tenant_id, row.id, "RRN-30")
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("70.00")
    position = await OrderService.refund_position(
        db, tenant_ctx.tenant_id, uuid.UUID(str(sold["order_id"]))
    )
    assert Decimal(str(position["refunded"])) == Decimal("30.00")


@pytest.mark.asyncio
async def test_a_declined_reversal_is_rejected_and_the_room_comes_back(db, tenant_ctx) -> None:
    """The report's follow-up: a declined card had no way out, and its hold blocked a retry."""
    from app.modules.errors import ConflictError
    from app.modules.orders.service import OrderService
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[{"method": "card", "amount": "200.00", "reference": "AUTH-4"}],
    )
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    refund_id = uuid.UUID(out["awaiting_confirmation"][0]["refund_id"])

    rejected = await PosService.reject_refund(
        db, tenant_ctx.tenant_id, refund_id, "الماكينة رفضت العملية"
    )
    assert rejected["status"] == "rejected"
    assert await PosService.list_pending_refunds(db, tenant_ctx.tenant_id) == []
    position = await OrderService.refund_position(
        db, tenant_ctx.tenant_id, uuid.UUID(str(sold["order_id"]))
    )
    assert Decimal(str(position["refunded"])) == Decimal("0.00")

    # The reservation is released: the same money can be refunded again, once.
    again = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    assert len(again["awaiting_confirmation"]) == 1

    with pytest.raises(ConflictError):
        await PosService.reject_refund(db, tenant_ctx.tenant_id, refund_id, "تاني")


@pytest.mark.asyncio
async def test_a_rejected_reversal_can_be_refunded_on_another_tender(db, tenant_ctx) -> None:
    """Cash instead of the declined card: a new row, never a second claim on the same money."""
    from app.modules.orders.service import OrderService
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=10,
        payments=[
            {"method": "cash", "amount": "100.00"},
            {"method": "card", "amount": "900.00", "reference": "AUTH-5"},
        ],
    )
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        refund=[{"method": "card", "amount": "100.00"}],
    )
    refund_id = uuid.UUID(out["awaiting_confirmation"][0]["refund_id"])
    result = await PosService.reject_refund(
        db,
        tenant_ctx.tenant_id,
        refund_id,
        "الماكينة مش متصلة",
        replacement_method="cash",
        session_id=shift.id,
    )
    assert result["replacement"]["method"] == "cash"
    assert result["replacement"]["status"] == "processed"
    assert Decimal(str(result["replacement"]["amount"])) == Decimal("100.00")
    position = await OrderService.refund_position(
        db, tenant_ctx.tenant_id, uuid.UUID(str(sold["order_id"]))
    )
    assert Decimal(str(position["refunded"])) == Decimal("100.00")


async def _cash_out(db, tenant_ctx, session_id):
    from app.modules.pos.models import PosCashMovement

    await db.flush()
    return (
        (
            await db.execute(
                sa.select(PosCashMovement).where(
                    PosCashMovement.tenant_id == tenant_ctx.tenant_id,
                    PosCashMovement.session_id == session_id,
                    PosCashMovement.direction == "out",
                    PosCashMovement.reason == "cash_refund",
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_a_cash_replacement_leaves_the_drawer_and_moves_the_payment(db, tenant_ctx) -> None:
    """Blocker 1: the replacement was ``processed`` on paper only: no movement, no derived state."""
    from app.modules.orders.models import OrderPayment
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[
            {"method": "cash", "amount": "100.00"},
            {"method": "card", "amount": "100.00", "reference": "AUTH-6"},
        ],
    )
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        refund=[{"method": "card", "amount": "100.00"}],
    )
    refund_id = uuid.UUID(out["awaiting_confirmation"][0]["refund_id"])
    result = await PosService.reject_refund(
        db,
        tenant_ctx.tenant_id,
        refund_id,
        "الماكينة مش متصلة",
        replacement_method="cash",
        session_id=shift.id,
    )
    assert result["replacement"]["status"] == "processed"
    (movement,) = await _cash_out(db, tenant_ctx, shift.id)
    assert Decimal(str(movement.amount)) == Decimal("100.00")
    await db.flush()
    card = (
        await db.execute(
            sa.select(OrderPayment).where(
                OrderPayment.tenant_id == tenant_ctx.tenant_id,
                OrderPayment.method == "card",
            )
        )
    ).scalar_one()
    assert card.status == "captured"
    assert await _customer_worth(db, tenant_ctx, customer.id) == Decimal("100.00")


@pytest.mark.asyncio
async def test_a_replacement_that_cannot_cover_the_whole_amount_is_refused(db, tenant_ctx) -> None:
    """Blocker 1b: 60 of 100 recorded as done left a 40 nobody was chasing."""
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=3,
        payments=[
            {"method": "cash", "amount": "60.00"},
            {"method": "card", "amount": "240.00", "reference": "AUTH-7"},
        ],
    )
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        refund=[{"method": "card", "amount": "100.00"}],
    )
    refund_id = uuid.UUID(out["awaiting_confirmation"][0]["refund_id"])
    with pytest.raises(ValidationError):
        await PosService.reject_refund(
            db,
            tenant_ctx.tenant_id,
            refund_id,
            "الماكينة مش متصلة",
            replacement_method="cash",
            session_id=shift.id,
        )
    pending = await PosService.list_pending_refunds(db, tenant_ctx.tenant_id)
    assert [row["refund_id"] for row in pending] == [str(refund_id)]
    assert await _cash_out(db, tenant_ctx, shift.id) == []


@pytest.mark.asyncio
async def test_cash_only_on_two_card_payments_records_the_amount_once(db, tenant_ctx) -> None:
    """Blocker 2: the method total was repeated per payment, so 30 was recorded twice as 60."""
    from app.modules.orders.service import OrderService
    from app.modules.pos.service import PosService
    from app.modules.settings.service import SettingsService

    shift, variant, customer = await _paid_till(db, tenant_ctx, methods=("cash", "card"))
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.refund_cash_only", True)
    sold = await _sale(
        db,
        tenant_ctx,
        shift,
        variant,
        customer,
        quantity=2,
        payments=[
            {"method": "card", "amount": "100.00", "reference": "AUTH-8"},
            {"method": "card", "amount": "100.00", "reference": "AUTH-9"},
        ],
    )
    out = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        refund=[{"method": "card", "amount": "30.00"}],
    )
    rows = await _refund_rows(db, tenant_ctx)
    assert len(rows) == 1
    assert sum(Decimal(str(row.amount)) for row in rows) == Decimal("30.00")
    assert sum(Decimal(str(row["amount"])) for row in out["awaiting_confirmation"]) == Decimal(
        "30.00"
    )
    position = await OrderService.refund_position(
        db, tenant_ctx.tenant_id, uuid.UUID(str(sold["order_id"]))
    )
    assert Decimal(str(position["refunded"])) == Decimal("0.00")


@pytest.mark.asyncio
async def test_confirm_and_reject_both_lock_the_refund_row(db, tenant_ctx) -> None:
    """Blocker 3: a plain read let confirm and reject both see ``pending`` and both win."""
    import inspect

    from app.modules.pos.service import PosService

    for fn in (PosService.confirm_refund, PosService.reject_refund):
        assert "with_for_update()" in inspect.getsource(fn), fn.__name__

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
    assert second["refund_by_method"] == {"card": "100.00"}
    assert second["refund_mode"] == "tender"

    summary = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    # Only the cash leg touches the drawer: 200 came in, 200 went back out, so it is empty. The
    # 300 the card collected never entered it, and the 100 card refund never left it.
    assert Decimal(summary["expected_cash"]) == Decimal("0.00")
    assert summary["by_method"] == {"cash": "200.00", "card": "300.00"}


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

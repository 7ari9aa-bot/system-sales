"""§189 phase 1 — shift integrity: floats, one-drawer-per-cashier, staleness.

Two test classes, per AGENT_BRIEF §7:

* **DB-free guards** run everywhere: the new routes are mounted, the new wire
  shapes exist, and the day-staleness predicate is pure.
* **DB-backed** tests run only where a database URL is configured (CI); conftest
  skips them locally. They are reported as UNVERIFIED when only local runs were
  possible.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.main import create_app

SESSIONS_PATH = "/api/v1/pos/sessions"
CLOSE_PREVIEW_PATH = "/api/v1/pos/sessions/{session_id}/close-preview"
SESSION_RECEIPTS_PATH = "/api/v1/pos/sessions/{session_id}/receipts"
RECEIPT_PATH = "/api/v1/pos/receipts/{receipt_id}"


# --------------------------------------------------------- DB-free guards --


def test_phase1_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {SESSIONS_PATH, CLOSE_PREVIEW_PATH, SESSION_RECEIPTS_PATH, RECEIPT_PATH} <= paths


def test_open_session_wire_accepts_per_method_floats() -> None:
    from app.modules.pos.router import OpenSessionRequest

    body = OpenSessionRequest(
        opening_float="50.00",
        floats_by_method={"cash": "50.00", "card": "20.00"},
    )
    assert body.floats_by_method == {"cash": "50.00", "card": "20.00"}


def test_sell_wire_accepts_held_cart_resume() -> None:
    from app.modules.pos.router import SellRequest

    body = SellRequest(
        items=[{"variant_id": str(uuid.uuid4()), "quantity": 1}],
        held_cart_id=uuid.uuid4(),
    )
    assert body.held_cart_id is not None


def test_profile_wire_accepts_default_and_return_methods() -> None:
    from app.modules.pos.router import CreateProfileRequest

    body = CreateProfileRequest(
        name="Till",
        code="P1",
        warehouse_id=uuid.uuid4(),
        default_payment_method="card",
        returns_allowed_methods=["cash", "card"],
    )
    assert body.default_payment_method == "card"
    assert body.returns_allowed_methods == ["cash", "card"]


def test_profile_wire_refuses_unknown_default_method() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from app.modules.pos.router import CreateProfileRequest

    with pytest.raises(PydanticValidationError):
        CreateProfileRequest(
            name="Till",
            code="P1",
            warehouse_id=uuid.uuid4(),
            default_payment_method="crypto",
        )


def test_stale_session_is_refused_fresh_one_is_not() -> None:
    from app.modules.errors import ConflictError
    from app.modules.pos.models import PosSession
    from app.modules.pos.service import PosService

    fresh = PosSession(register_id=uuid.uuid4(), opened_at=datetime.now(UTC))
    PosService._ensure_session_current(fresh)

    stale = PosSession(register_id=uuid.uuid4(), opened_at=datetime.now(UTC) - timedelta(days=2))
    with pytest.raises(ConflictError):
        PosService._ensure_session_current(stale)


# ----------------------------------------------------------- DB-backed -----


async def _warehouse(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService

    return await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)


async def _register(db, tenant_ctx, **kwargs):
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    return await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
        **kwargs,
    )


async def _sellable_variant(db, tenant_ctx, price="25.00"):
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    warehouse = await _warehouse(db, tenant_ctx)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="كوباية", slug=f"c-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="سعة كبيرة", price=price
    )
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=10,
        reason="purchase",
    )
    return variant


async def _customer(db, tenant_ctx):
    from app.modules.customers.service import CustomerService

    return await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون نقدي", source="pos"
    )


async def test_one_open_drawer_per_user(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    register_a = await _register(db, tenant_ctx)
    register_b = await _register(db, tenant_ctx)
    await PosService.open_session(
        db,
        tenant_ctx.tenant_id,
        register_a.id,
        opened_by=tenant_ctx.user.id,
    )
    with pytest.raises(ConflictError):
        await PosService.open_session(
            db,
            tenant_ctx.tenant_id,
            register_b.id,
            opened_by=tenant_ctx.user.id,
        )
    # A second cashier is fine.
    other = await PosService.open_session(
        db, tenant_ctx.tenant_id, register_b.id, opened_by=None, cashier_user_id=None
    )
    assert other.cashier_user_id is None


async def test_per_method_floats_are_written_and_cash_mirrors(db, tenant_ctx):

    from app.modules.pos.models import PosSessionFloat
    from app.modules.pos.profiles import PosProfileService
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="بروفايل",
        code=f"P-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db,
        tenant_ctx.tenant_id,
        register.id,
        opened_by=tenant_ctx.user.id,
        profile_id=profile.id,
        floats_by_method={"cash": "100.00", "card": "0.00"},
    )
    rows = (
        (
            await db.execute(
                select(PosSessionFloat).where(PosSessionFloat.session_id == pos_session.id)
            )
        )
        .scalars()
        .all()
    )
    by_method = {r.method: Decimal(str(r.amount)) for r in rows}
    assert by_method == {"cash": Decimal("100.00"), "card": Decimal("0.00")}
    assert Decimal(pos_session.opening_float) == Decimal("100.00")


async def test_float_method_outside_profile_is_refused(db, tenant_ctx):
    from app.modules.errors import ValidationError
    from app.modules.pos.profiles import PosProfileService
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="كاش فقط",
        code=f"P-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
        allowed_payment_methods=["cash"],
    )
    register = await _register(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await PosService.open_session(
            db,
            tenant_ctx.tenant_id,
            register.id,
            profile_id=profile.id,
            floats_by_method={"card": "10.00"},
        )


async def test_stale_session_refuses_to_sell(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)

    pos_session.opened_at = datetime.now(UTC) - timedelta(days=2)
    await db.flush()
    with pytest.raises(ConflictError):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            customer_id=customer.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
        )
    # Reading and closing a stale session stay allowed — the day must close.
    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, pos_session.id)
    assert preview["status"] == "OPEN"
    await PosService.close_session(db, tenant_ctx.tenant_id, pos_session.id, counted_cash="0.00")


async def test_close_preview_shows_per_method_targets(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opening_float="50.00"
    )
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        tenders=[
            {"method": "cash", "amount": "15.00"},
            {"method": "card", "amount": "10.00"},
        ],
    )
    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, pos_session.id)
    by_method = {r["method"]: Decimal(r["expected"]) for r in preview["by_method"]}
    assert by_method["cash"] == Decimal("65.00")  # float 50 + cash leg 15
    assert by_method["card"] == Decimal("10.00")
    assert preview["invoice_count"] == 1
    assert Decimal(preview["sales_total"]) == Decimal("25.00")


async def test_card_refund_nets_in_the_close_arithmetic(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        method="card",
    )
    await PosService.refund(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        amount="10.00",
        method="card",
    )
    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, pos_session.id)
    by_method = {r["method"]: Decimal(r["expected"]) for r in preview["by_method"]}
    assert by_method["card"] == Decimal("15.00")  # 25 captured − 10 refunded
    assert by_method["cash"] == Decimal("0.00")  # float only

    closed = await PosService.close_session(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        counted_cash="0.00",
        counted_by_method={"cash": "0.00", "card": "15.00"},
    )
    rows = await PosService.list_reconciliation(db, tenant_ctx.tenant_id, closed.id)
    card = next(r for r in rows if r.method == "card")
    assert Decimal(str(card.expected_amount)) == Decimal("15.00")
    assert Decimal(str(card.variance)) == Decimal("0.00")


async def test_held_cart_resume_is_atomic(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    held = await PosService.hold_cart(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        customer_id=customer.id,
    )

    result = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        held_cart_id=held.id,
    )
    assert result["receipt_number"].startswith("POS-")
    with pytest.raises(ConflictError):
        # A second resume of the same cart is refused — it is already sold.
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            held_cart_id=held.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
        )


async def test_profile_cannot_be_disabled_with_open_session(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.profiles import PosProfileService
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="بروفايل شغال",
        code=f"P-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )
    register = await _register(db, tenant_ctx)
    await PosService.open_session(
        db,
        tenant_ctx.tenant_id,
        register.id,
        profile_id=profile.id,
        opened_by=tenant_ctx.user.id,
    )
    with pytest.raises(ConflictError):
        await PosProfileService.update(db, tenant_ctx.tenant_id, profile.id, is_active=False)
    # After the close, disabling is fine.
    sessions = await PosService.list_sessions(
        db, tenant_ctx.tenant_id, status="OPEN", register_id=register.id
    )
    await PosService.close_session(
        db,
        tenant_ctx.tenant_id,
        sessions[0].id,
        counted_cash="0.00",
        closed_by=tenant_ctx.user.id,
    )
    updated = await PosProfileService.update(db, tenant_ctx.tenant_id, profile.id, is_active=False)
    assert updated.is_active is False


async def test_profile_default_method_charges_the_whole_total(db, tenant_ctx):

    from app.modules.orders.models import OrderPayment
    from app.modules.pos.profiles import PosProfileService
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="كارت الافتراضي",
        code=f"P-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
        default_payment_method="card",
    )
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db,
        tenant_ctx.tenant_id,
        register.id,
        profile_id=profile.id,
        opened_by=tenant_ctx.user.id,
    )
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    result = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        actor_user_id=tenant_ctx.user.id,
    )
    payment = (
        (await db.execute(select(OrderPayment).where(OrderPayment.order_id == result["order_id"])))
        .scalars()
        .one()
    )
    assert payment.method == "card"
    assert payment.status == "captured"


async def test_tenders_must_settle_the_whole_order(db, tenant_ctx):
    """ERPNext `validate_pos`: a split that does not total the order is refused.

    Overpaying with a card would silently credit the order; shorting it would
    print a receipt for a sale it did not settle. Cash over-tender goes
    through ``tendered_cash`` instead, where the change is computed.
    """
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)

    with pytest.raises(ValidationError):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            customer_id=customer.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],  # 25.00
            tenders=[
                {"method": "cash", "amount": "20.00"},
                {"method": "card", "amount": "30.00"},  # 50 on a 25 order
            ],
        )
    with pytest.raises(ValidationError):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            customer_id=customer.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],  # 25.00
            tenders=[{"method": "card", "amount": "20.00"}],  # short
        )


async def test_closing_a_shift_clears_its_parked_carts_and_only_its_own(db, tenant_ctx):
    """A parked cart is a basket, not a sale. It cannot outlive its shift.

    After the close nobody could resume it, so the close deletes it in the same transaction.
    Another drawer's carts are not touched.
    """
    from app.modules.errors import NotFoundError
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    other_register = await _register(db, tenant_ctx)
    mine = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    theirs = await PosService.open_session(db, tenant_ctx.tenant_id, other_register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    line = [{"variant_id": str(variant.id), "quantity": 1}]
    a = await PosService.hold_cart(db, tenant_ctx.tenant_id, mine.id, items=line)
    await PosService.hold_cart(db, tenant_ctx.tenant_id, mine.id, items=line)
    survivor = await PosService.hold_cart(db, tenant_ctx.tenant_id, theirs.id, items=line)

    assert len(await PosService.list_held_carts(db, tenant_ctx.tenant_id, mine.id)) == 2
    await PosService.close_session(db, tenant_ctx.tenant_id, mine.id, counted_cash="0")

    assert await PosService.list_held_carts(db, tenant_ctx.tenant_id, mine.id) == []
    with pytest.raises(NotFoundError):
        await PosService.get_held_cart(db, tenant_ctx.tenant_id, a.id)
    assert [
        h.id for h in await PosService.list_held_carts(db, tenant_ctx.tenant_id, theirs.id)
    ] == [survivor.id]

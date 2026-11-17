"""Tests for manual cash drawer movements (pay-in, pay-out, cash drop) and shift handover."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.main import create_app
from app.modules.errors import ConflictError, PermissionDeniedError, ValidationError
from app.modules.identity.models import Role, TenantUser, User
from app.modules.pos.service import PosService
from tests._pos_helpers import till


def test_routes_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert "/api/v1/pos/sessions/{session_id}/cash-movements" in paths
    assert "/api/v1/pos/sessions/{session_id}/handover" in paths


@pytest.mark.asyncio
async def test_pay_in_accepted(db, tenant_ctx) -> None:
    shift, _, _ = await till(db, tenant_ctx)

    movement = await PosService.add_cash_movement(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        direction="in",
        reason="pay_in",
        amount="150.00",
        notes="Morning top-up",
        actor_user_id=tenant_ctx.user.id,
    )

    assert movement.id is not None
    assert movement.direction == "in"
    assert movement.reason == "pay_in"
    assert movement.amount == Decimal("150.00")
    assert movement.notes == "Morning top-up"
    assert movement.created_by_user_id == tenant_ctx.user.id

    rows = await PosService.list_cash_movements(db, tenant_ctx.tenant_id, shift.id)
    assert len(rows) == 1
    assert rows[0].id == movement.id


@pytest.mark.asyncio
async def test_pay_out_and_cash_drop_accepted(db, tenant_ctx) -> None:
    shift, _, _ = await till(db, tenant_ctx)

    payout = await PosService.add_cash_movement(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        direction="out",
        reason="pay_out",
        amount="50.00",
        notes="Office coffee supplies",
        actor_user_id=tenant_ctx.user.id,
    )
    assert payout.direction == "out"
    assert payout.reason == "pay_out"

    drop = await PosService.add_cash_movement(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        direction="out",
        reason="cash_drop",
        amount="500.00",
        notes="Safe drop midday",
        actor_user_id=tenant_ctx.user.id,
    )
    assert drop.direction == "out"
    assert drop.reason == "cash_drop"

    movements = await PosService.list_cash_movements(db, tenant_ctx.tenant_id, shift.id)
    assert len(movements) == 2


@pytest.mark.asyncio
async def test_invalid_direction_or_reason_refused(db, tenant_ctx) -> None:
    shift, _, _ = await till(db, tenant_ctx)

    with pytest.raises(ValidationError, match="requires direction"):
        await PosService.add_cash_movement(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            direction="out",
            reason="pay_in",
            amount="100.00",
        )

    with pytest.raises(ValidationError, match="requires direction"):
        await PosService.add_cash_movement(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            direction="in",
            reason="pay_out",
            amount="100.00",
        )

    with pytest.raises(ValidationError, match="reason must be one of"):
        await PosService.add_cash_movement(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            direction="in",
            reason="cash_sale",
            amount="100.00",
        )


@pytest.mark.asyncio
async def test_closed_session_refused(db, tenant_ctx) -> None:
    shift, _, _ = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)

    with pytest.raises(ConflictError, match="cannot add cash movement to a closed session"):
        await PosService.add_cash_movement(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            direction="in",
            reason="pay_in",
            amount="100.00",
        )


@pytest.mark.asyncio
async def test_drawer_totals_reflect_movements(db, tenant_ctx) -> None:
    shift, _, _ = await till(db, tenant_ctx)

    await PosService.add_cash_movement(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        direction="in",
        reason="pay_in",
        amount="200.00",
    )
    await PosService.add_cash_movement(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        direction="out",
        reason="cash_drop",
        amount="50.00",
    )

    data = await PosService.get_session(db, tenant_ctx.tenant_id, shift.id)
    assert data["inflow"] == Decimal("200.00")
    assert data["outflow"] == Decimal("50.00")


@pytest.mark.asyncio
async def test_shift_handover(db, tenant_ctx) -> None:
    shift, _, _ = await till(db, tenant_ctx)

    from sqlalchemy import select

    new_user = User(
        email=f"cashier2_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Second Cashier",
        password_hash="x",
        is_active=True,
    )
    db.add(new_user)
    role = (await db.execute(select(Role).where(Role.code == "owner"))).scalar_one()
    tu = TenantUser(
        tenant_id=tenant_ctx.tenant_id,
        user_id=new_user.id,
        role_id=role.id,
    )
    db.add(tu)
    await db.flush()

    updated = await PosService.handover_session(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        new_cashier_id=new_user.id,
        actor_user_id=shift.cashier_user_id,
    )
    assert updated.cashier_user_id == new_user.id
    assert updated.status == "OPEN"


@pytest.mark.asyncio
async def test_handover_closed_session_refused(db, tenant_ctx) -> None:
    shift, _, _ = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)

    with pytest.raises(ConflictError, match="cannot hand over a closed session"):
        await PosService.handover_session(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            new_cashier_id=uuid.uuid4(),
            actor_user_id=shift.cashier_user_id,
        )


@pytest.mark.asyncio
async def test_handover_wrong_holder_refused_without_override(db, tenant_ctx) -> None:
    shift, _, _ = await till(db, tenant_ctx)

    holder_user = User(
        email=f"holder_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Holder Cashier",
        password_hash="x",
        is_active=True,
    )
    db.add(holder_user)
    target_user = User(
        email=f"target_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Target Cashier",
        password_hash="x",
        is_active=True,
    )
    db.add(target_user)
    await db.flush()

    shift.cashier_user_id = holder_user.id
    await db.flush()

    wrong_actor = uuid.uuid4()
    with pytest.raises(PermissionDeniedError, match="held by another cashier"):
        await PosService.handover_session(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            new_cashier_id=target_user.id,
            actor_user_id=wrong_actor,
            shift_override=False,
        )

    # But with shift_override=True, manager passes
    updated = await PosService.handover_session(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        new_cashier_id=target_user.id,
        actor_user_id=wrong_actor,
        shift_override=True,
    )
    assert updated.cashier_user_id == target_user.id

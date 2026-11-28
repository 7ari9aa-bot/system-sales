"""Closing a drawer that does not match: the reason is written down, and a big gap is approved.

The count and the variance already existed. What a cash shop also needs is WHY the drawer was off
and, above a limit the owner sets, a manager's name against it. A drawer that matches closes as it
always did, and a till that never turned payments on is not touched at all.

The owner is often the only cashier, so approval is allowed on one's own shift: it is recorded,
not forbidden.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.applications.apparel.modules.pos.service import PosService
from app.modules.settings.service import SettingsService
from tests._pos_helpers import start_day, till

pytestmark = pytest.mark.asyncio

D = Decimal


async def _shop(db, tenant_ctx, *, reason_required=None, threshold=None, payments=True):
    shift, variant, customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    svc = SettingsService(db, tenant_ctx.tenant_id)
    if payments:
        await svc.set("pos.take_payments", True)
    if reason_required is not None:
        await svc.set("pos.variance_reason_required", reason_required)
    if threshold is not None:
        await svc.set("pos.variance_approval_threshold", threshold)
    register = await PosService._get_register(db, tenant_ctx.tenant_id, shift.register_id)
    register.profile_id = shift.profile_id
    await db.flush()
    await start_day(db, tenant_ctx, shift.register_id, opening="200.00")
    return await PosService._today_session(db, tenant_ctx.tenant_id, register)


async def _close(db, tenant_ctx, shift, counted, **extra):
    return await PosService.close_session(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        closed_by=tenant_ctx.user.id,
        counted_cash=counted,
        **extra,
    )


async def test_a_drawer_that_matches_closes_without_a_reason(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    closed = await _close(db, tenant_ctx, shift, "200.00")
    assert closed.variance == D("0.00")
    assert closed.variance_reason is None
    assert closed.variance_approved_by_user_id is None


async def test_a_shortage_without_a_reason_is_refused_and_the_day_stays_open(
    db, tenant_ctx
) -> None:
    shift = await _shop(db, tenant_ctx)
    with pytest.raises(ValidationError, match="variance_reason"):
        await _close(db, tenant_ctx, shift, "195.00")
    assert (await PosService._get_session(db, tenant_ctx.tenant_id, shift.id)).status == "OPEN"


async def test_an_overage_without_a_reason_is_refused_too(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    with pytest.raises(ValidationError, match="variance_reason"):
        await _close(db, tenant_ctx, shift, "205.00")


async def test_a_reason_is_saved_trimmed_with_the_variance(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    closed = await _close(db, tenant_ctx, shift, "195.00", variance_reason="  باقي ناقص  ")
    assert closed.variance == D("-5.00")
    assert closed.variance_reason == "باقي ناقص"


async def test_a_blank_reason_counts_as_none(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    with pytest.raises(ValidationError, match="variance_reason"):
        await _close(db, tenant_ctx, shift, "195.00", variance_reason="   ")


async def test_a_reason_on_a_matching_drawer_is_not_stored(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    closed = await _close(db, tenant_ctx, shift, "200.00", variance_reason="not needed")
    assert closed.variance_reason is None


async def test_the_owner_can_turn_the_reason_requirement_off(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, reason_required=False)
    closed = await _close(db, tenant_ctx, shift, "195.00")
    assert closed.variance == D("-5.00")
    assert closed.variance_reason is None


async def test_a_reason_longer_than_the_limit_is_refused_not_cut(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    with pytest.raises(ValidationError, match="variance_reason"):
        await _close(db, tenant_ctx, shift, "195.00", variance_reason="x" * 501)


# ── approval above a limit ─────────────────────────────────────────────────────────────────────


async def test_with_no_limit_set_any_size_of_gap_closes_with_a_reason(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    closed = await _close(db, tenant_ctx, shift, "50.00", variance_reason="سرقة")
    assert closed.variance == D("-150.00")
    assert closed.variance_approved_by_user_id is None


async def test_a_gap_above_the_limit_needs_a_manager(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, threshold=20)
    with pytest.raises(ValidationError, match="approval"):
        await _close(db, tenant_ctx, shift, "170.00", variance_reason="ناقص")
    assert (await PosService._get_session(db, tenant_ctx.tenant_id, shift.id)).status == "OPEN"


async def test_a_manager_approves_a_gap_above_the_limit_and_is_recorded(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, threshold=20)
    closed = await _close(
        db, tenant_ctx, shift, "170.00", variance_reason="ناقص", shift_override=True
    )
    assert closed.variance == D("-30.00")
    assert closed.variance_approved_by_user_id == tenant_ctx.user.id
    assert closed.variance_approved_at is not None


async def test_a_gap_at_exactly_the_limit_needs_no_approval(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, threshold=20)
    closed = await _close(db, tenant_ctx, shift, "180.00", variance_reason="ناقص")
    assert closed.variance == D("-20.00")
    assert closed.variance_approved_by_user_id is None


async def test_an_overage_above_the_limit_needs_a_manager_just_like_a_shortage(
    db, tenant_ctx
) -> None:
    shift = await _shop(db, tenant_ctx, threshold=20)
    with pytest.raises(ValidationError, match="approval"):
        await _close(db, tenant_ctx, shift, "230.00", variance_reason="زيادة")


async def test_a_manager_who_is_also_the_cashier_may_approve_their_own_shift(
    db, tenant_ctx
) -> None:
    """One-person shop: the owner is the cashier. Approval is recorded, never forbidden."""
    shift = await _shop(db, tenant_ctx, threshold=20)
    shift.cashier_user_id = tenant_ctx.user.id  # one-person shop: the manager holds the shift
    await db.flush()
    closed = await _close(
        db, tenant_ctx, shift, "100.00", variance_reason="ناقص", shift_override=True
    )
    assert closed.variance_approved_by_user_id == tenant_ctx.user.id


async def test_a_small_gap_within_the_limit_records_no_approver_even_for_a_manager(
    db, tenant_ctx
) -> None:
    shift = await _shop(db, tenant_ctx, threshold=20)
    closed = await _close(
        db, tenant_ctx, shift, "195.00", variance_reason="ناقص", shift_override=True
    )
    assert closed.variance_approved_by_user_id is None


async def test_the_reason_is_checked_before_the_approval(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, threshold=20)
    with pytest.raises(ValidationError, match="variance_reason"):
        await _close(db, tenant_ctx, shift, "100.00", shift_override=True)


# ── a till that does not count is not touched ──────────────────────────────────────────────────


async def test_a_till_that_never_turned_payments_on_closes_exactly_as_before(
    db, tenant_ctx
) -> None:
    shift = await _shop(db, tenant_ctx, payments=False)
    closed = await PosService.close_session(
        db, tenant_ctx.tenant_id, shift.id, closed_by=tenant_ctx.user.id
    )
    assert closed.counted_cash is None
    assert closed.variance is None
    assert closed.variance_reason is None
    assert closed.variance_approved_by_user_id is None


async def test_a_reason_on_a_till_that_does_not_count_is_refused(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx, payments=False)
    with pytest.raises(ValidationError, match="does not count a drawer"):
        await PosService.close_session(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            closed_by=tenant_ctx.user.id,
            variance_reason="x",
        )


async def test_the_default_threshold_is_off_and_the_reason_is_required(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    assert await svc.value("pos.variance_reason_required") is True
    assert D(str(await svc.value("pos.variance_approval_threshold"))) == D("0")


async def test_the_approval_limit_cannot_be_negative(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    with pytest.raises(Exception):  # noqa: B017 - any validation refusal is right
        await svc.set("pos.variance_approval_threshold", -1)


async def test_another_shops_session_cannot_be_closed_with_a_reason(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    with pytest.raises(Exception):  # noqa: B017 - not found, whichever error type
        await PosService.close_session(
            db,
            uuid.uuid4(),
            shift.id,
            closed_by=tenant_ctx.user.id,
            counted_cash="195.00",
            variance_reason="x",
        )


# ── what the close returns, through the real route ─────────────────────────────────────────────


async def _call(db, tenant_ctx, method, path, *, perms, body=None):
    from httpx import ASGITransport, AsyncClient

    from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
    from tests.security.test_role_authz_matrix import _authz_app

    ctx = TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code="x",
            is_platform_admin=False,
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="x",
        permission_codes=perms,
    )
    app = _authz_app()

    async def _db():
        yield db

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=20
    ) as client:
        return await client.request(method, path, json=body)


CASHIER = {"orders:read", "orders:write"}
MANAGER = CASHIER | {"pos:override"}


async def test_the_close_answer_shows_the_count_the_gap_and_the_reason(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    r = await _call(
        db,
        tenant_ctx,
        "POST",
        f"/api/v1/pos/sessions/{shift.id}/close",
        perms=CASHIER,
        body={"counted_cash": "195.00", "variance_reason": "باقي ناقص"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counted_cash"] == "195.00"
    assert body["variance"] == "-5.00"
    assert body["variance_reason"] == "باقي ناقص"
    assert body["variance_approved_by_user_id"] is None


async def test_the_route_refuses_a_gap_with_no_reason(db, tenant_ctx) -> None:
    shift = await _shop(db, tenant_ctx)
    r = await _call(
        db,
        tenant_ctx,
        "POST",
        f"/api/v1/pos/sessions/{shift.id}/close",
        perms=CASHIER,
        body={"counted_cash": "195.00"},
    )
    assert r.status_code in (400, 422), r.text
    assert "variance_reason" in r.text


async def test_a_cashier_cannot_close_a_gap_above_the_limit_but_a_manager_can(
    db, tenant_ctx
) -> None:
    shift = await _shop(db, tenant_ctx, threshold=20)
    path = f"/api/v1/pos/sessions/{shift.id}/close"
    body = {"counted_cash": "150.00", "variance_reason": "ناقص"}
    refused = await _call(db, tenant_ctx, "POST", path, perms=CASHIER, body=body)
    assert refused.status_code in (400, 422), refused.text
    ok = await _call(db, tenant_ctx, "POST", path, perms=MANAGER, body=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["variance_approved_by_user_id"] == str(tenant_ctx.user.id)


async def test_a_till_that_does_not_count_returns_the_same_close_answer_as_before(
    db, tenant_ctx
) -> None:
    shift = await _shop(db, tenant_ctx, payments=False)
    r = await _call(db, tenant_ctx, "POST", f"/api/v1/pos/sessions/{shift.id}/close", perms=CASHIER)
    assert r.status_code == 200, r.text
    assert "counted_cash" not in r.json()
    assert "variance" not in r.json()


async def test_the_custody_report_is_manager_only(db, tenant_ctx) -> None:
    q = "start=2026-11-01&end=2026-12-01"
    denied = await _call(
        db, tenant_ctx, "GET", f"/api/v1/pos/reports/cashier-custody?{q}", perms=CASHIER
    )
    assert denied.status_code == 403
    ok = await _call(
        db, tenant_ctx, "GET", f"/api/v1/pos/reports/cashier-custody?{q}", perms=MANAGER
    )
    assert ok.status_code == 200, ok.text
    assert ok.json() == []


async def test_the_custody_report_refuses_a_bad_date(db, tenant_ctx) -> None:
    r = await _call(
        db,
        tenant_ctx,
        "GET",
        "/api/v1/pos/reports/cashier-custody?start=nope&end=2026-12-01",
        perms=MANAGER,
    )
    assert r.status_code in (400, 422)

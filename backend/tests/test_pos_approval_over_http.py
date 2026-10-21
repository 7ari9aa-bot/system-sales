"""The whole approval path over real HTTP: the real router, real service, real database.

A cashier (no ``pos:override``) crosses the owner's ceiling and is told, with a stable code, that a
manager must approve. The same request retried with the manager's id + PIN goes through, and the
approval is attributed to that manager. This is the exact contract the till's PIN dialog relies on.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.errors import DomainError, build_error_body
from app.modules.identity.deps import get_tenant_ctx
from app.modules.pos.models import PosCashMovement
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.router import router as pos_router
from app.modules.pos.service import PosService
from tests.test_pos_manager_pin import _ctx, _setup  # noqa: F401  (also brings the Redis fixture)
from tests.test_pos_returns import _register, _warehouse

pytestmark = pytest.mark.asyncio


def _app(ctx) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=build_error_body(exc))

    app.include_router(pos_router, prefix="/api/v1")

    async def _the_cashier():
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _the_cashier
    return app


async def _shift_with_ceiling(db, tenant_ctx, cashier, cash_out_ceiling):
    register = await _register(db, tenant_ctx)
    wh = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="p",
        code=f"P{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        discount_ceiling_pct="100",
        allowed_payment_methods=["cash"],
        cash_out_ceiling=cash_out_ceiling,
    )
    # The shift belongs to the cashier, as in a real shop.
    return await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, profile_id=profile.id, cashier_user_id=cashier.id
    )


def _out(amount):
    return {"direction": "out", "reason": "pay_out", "amount": amount}


async def test_over_the_ceiling_then_a_manager_pin_then_it_goes_through(db, tenant_ctx):
    manager, cashier, ctx = await _setup(db, tenant_ctx, pin="4821")
    shift = await _shift_with_ceiling(db, tenant_ctx, cashier, "100.00")
    url = f"/api/v1/pos/sessions/{shift.id}/cash-movements"

    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as http:
        # 1. Over the ceiling, no manager: refused with a code the till can act on.
        refused = await http.post(url, json=_out("250.00"))
        assert refused.status_code == 400
        error = refused.json()["error"]
        assert error["code"] == "approval_required"
        assert error["details"] == {"limit": "cash_out", "ceiling": "100.00"}

        # 2. A wrong PIN is an ordinary refusal that does not say whether the manager exists.
        wrong = await http.post(
            url,
            json=_out("250.00"),
            headers={"X-Manager-Id": str(manager.id), "X-Manager-Pin": "0000"},
        )
        assert wrong.status_code == 403

        # 3. The right PIN: the SAME request now goes through.
        ok = await http.post(
            url,
            json=_out("250.00"),
            headers={"X-Manager-Id": str(manager.id), "X-Manager-Pin": "4821"},
        )
        assert ok.status_code == 201, ok.text
        assert Decimal(ok.json()["amount"]) == Decimal("250.00")

        # 4. Under the ceiling needs nobody.
        assert (await http.post(url, json=_out("99.00"))).status_code == 201

    booked = (
        (
            await db.execute(
                __import__("sqlalchemy")
                .select(PosCashMovement.amount)
                .where(PosCashMovement.session_id == shift.id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(booked) == [Decimal("99.00"), Decimal("250.00")]  # the refused 250 left no row


async def test_internal_error_details_are_not_leaked_to_clients() -> None:
    """Only an error that opts in shows its details; the rest keep the exact old four keys."""
    from app.core.errors import ConflictError, build_error_body

    quiet = ConflictError("nope", details={"spend": "123.45", "cap": "200"})
    assert build_error_body(quiet, "r1") == {
        "error": {"code": "conflict", "message": "nope", "retryable": False, "request_id": "r1"}
    }

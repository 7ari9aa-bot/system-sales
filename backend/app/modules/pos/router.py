"""POS routes — thin REST over PosService (§189)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.pos.service import PosService

router = APIRouter(prefix="/pos", tags=["pos"])

PosWriteCtx = Annotated[TenantContext, Depends(require_permission("orders:write"))]


class CreateRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    code: str = Field(min_length=1, max_length=31)
    warehouse_id: UUID


class OpenSessionRequest(BaseModel):
    opening_float: str = Field(default="0.00", pattern=r"^\d+(\.\d{1,2})?$")


class CashMovementRequest(BaseModel):
    direction: str = Field(pattern="^(in|out)$")
    reason: str = Field(
        pattern="^(pay_in|pay_out|cash_drop|float_adjust)$",
        # cash_sale/cash_refund are the sell flow's rows — the pattern makes
        # that a wire contract, not just a service rule (§189).
    )
    amount: str = Field(pattern=r"^\d+(\.\d{1,2})?$")
    reference_id: UUID | None = None


class SellRequest(BaseModel):
    customer_id: UUID
    items: list[dict] = Field(min_length=1)
    method: str = Field(default="cash", pattern="^(cash|card|wallet|bank_transfer)$")
    amount: str | None = Field(default=None, pattern=r"^\d+(\.\d{1,2})?$")


class CloseSessionRequest(BaseModel):
    counted_cash: str = Field(pattern=r"^\d+(\.\d{1,2})?$")


def _session_out(pos_session, inflow=None, outflow=None, expected_now=None) -> dict:
    out = {
        "id": str(pos_session.id),
        "register_id": str(pos_session.register_id),
        "status": pos_session.status,
        "opening_float": str(pos_session.opening_float),
        "opened_at": pos_session.opened_at.isoformat(),
    }
    if pos_session.status == "CLOSED":
        out.update(
            {
                "counted_cash": str(pos_session.counted_cash),
                "expected_cash": str(pos_session.expected_cash),
                "variance": str(pos_session.variance),
                "closed_at": pos_session.closed_at.isoformat(),
            }
        )
    elif inflow is not None:
        out.update(
            {
                "inflow": str(inflow),
                "outflow": str(outflow),
                "expected_now": str(expected_now),
            }
        )
    return out


def _register_out(register) -> dict:
    return {
        "id": str(register.id),
        "name": register.name,
        "code": register.code,
        "warehouse_id": str(register.warehouse_id),
        "is_active": register.is_active,
    }


@router.post("/registers", status_code=201)
async def create_register(body: CreateRegisterRequest, ctx: PosWriteCtx):
    register = await PosService.create_register(
        ctx.session,
        ctx.tenant_id,
        name=body.name,
        code=body.code,
        warehouse_id=body.warehouse_id,
    )
    return _register_out(register)


@router.get("/registers")
async def list_registers(ctx: TenantCtxDep):
    return [_register_out(r) for r in await PosService.list_registers(ctx.session, ctx.tenant_id)]


@router.post("/registers/{register_id}/sessions", status_code=201)
async def open_session(register_id: UUID, body: OpenSessionRequest, ctx: PosWriteCtx):
    pos_session = await PosService.open_session(
        ctx.session,
        ctx.tenant_id,
        register_id,
        opening_float=body.opening_float,
        opened_by=ctx.user.id,
    )
    return _session_out(pos_session)


@router.get("/sessions/{session_id}")
async def get_session(session_id: UUID, ctx: TenantCtxDep):
    detail = await PosService.get_session(ctx.session, ctx.tenant_id, session_id)
    return _session_out(
        detail["session"],
        inflow=detail["inflow"],
        outflow=detail["outflow"],
        expected_now=detail["expected_now"],
    )


@router.post("/sessions/{session_id}/cash-movements", status_code=201)
async def record_cash_movement(session_id: UUID, body: CashMovementRequest, ctx: PosWriteCtx):
    row = await PosService.record_cash_movement(
        ctx.session,
        ctx.tenant_id,
        session_id,
        direction=body.direction,
        reason=body.reason,
        amount=body.amount,
        created_by=ctx.user.id,
        reference_id=body.reference_id,
    )
    return {
        "id": str(row.id),
        "direction": row.direction,
        "reason": row.reason,
        "amount": str(row.amount),
    }


@router.post("/sessions/{session_id}/sell")
async def sell(session_id: UUID, body: SellRequest, ctx: PosWriteCtx):
    """§189: the whole sell is one command chain in one transaction."""
    result = await PosService.sell(
        ctx.session,
        ctx.tenant_id,
        session_id,
        customer_id=body.customer_id,
        items=body.items,
        method=body.method,
        amount=body.amount,
        actor_user_id=ctx.user.id,
    )
    return {k: str(v) for k, v in result.items()}


@router.post("/sessions/{session_id}/close")
async def close_session(session_id: UUID, body: CloseSessionRequest, ctx: PosWriteCtx):
    pos_session = await PosService.close_session(
        ctx.session,
        ctx.tenant_id,
        session_id,
        counted_cash=body.counted_cash,
        closed_by=ctx.user.id,
    )
    return _session_out(pos_session)

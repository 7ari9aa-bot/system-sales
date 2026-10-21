"""EXPENSES routes: categories, post/void an expense, list with totals.

Reading needs `orders:read`. Posting a CASH expense is a drawer event, so the cashier
(`orders:write`) may do it. VOIDING reverses money, so it needs `inventory:write`
(manager/owner, not the frontline `staff` role).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.modules.expenses.service import ExpenseService
from app.modules.identity.deps import TenantContext, require_permission

router = APIRouter(prefix="/expenses", tags=["expenses"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("orders:read"))]
PostCtx = Annotated[TenantContext, Depends(require_permission("orders:write"))]
VoidCtx = Annotated[TenantContext, Depends(require_permission("inventory:write"))]


class CategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ExpenseRequest(BaseModel):
    category_id: uuid.UUID
    description: str = Field(min_length=1, max_length=255)
    # A string on purpose: a JSON float (0.1 + 0.2) would already be wrong on the wire.
    amount: str = Field(min_length=1, max_length=20)
    payment_method: str = Field(pattern="^(cash|card|wallet|bank_transfer)$")
    expense_date: date | None = None
    session_id: uuid.UUID | None = None


class VoidRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class CategoryOut(BaseModel):
    id: str
    name: str
    is_active: bool


class ExpenseOut(BaseModel):
    id: str
    number: str
    category_id: str
    description: str
    # Decimal as a string, always 2 places: a JSON float would lose the cents.
    amount: str
    payment_method: str
    expense_date: str
    session_id: str | None
    status: str
    voided_at: str | None
    void_reason: str | None
    created_at: str | None
    created_by_user_id: str | None


class ExpenseTotalsOut(BaseModel):
    total: str
    count: int
    by_method: dict[str, str]
    by_category: dict[str, str]


class ExpenseListOut(BaseModel):
    items: list[ExpenseOut]
    totals: ExpenseTotalsOut


def _category(c) -> dict:
    return {"id": str(c.id), "name": c.name, "is_active": c.is_active}


def _expense(e) -> dict:
    return {
        "id": str(e.id),
        "number": e.number,
        "category_id": str(e.category_id),
        "description": e.description,
        "amount": f"{e.amount:.2f}",
        "payment_method": e.payment_method,
        "expense_date": e.expense_date.isoformat(),
        "session_id": str(e.session_id) if e.session_id else None,
        "status": e.status,
        "voided_at": e.voided_at.isoformat() if e.voided_at else None,
        "void_reason": e.void_reason,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "created_by_user_id": str(e.created_by_user_id) if e.created_by_user_id else None,
    }


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(ctx: ReadCtx):
    rows = await ExpenseService.ensure_default_categories(ctx.session, ctx.tenant_id)
    return [_category(c) for c in rows if c.is_active]


@router.post("/categories", status_code=201, response_model=CategoryOut)
async def create_category(body: CategoryRequest, ctx: VoidCtx):
    await ExpenseService.ensure_default_categories(ctx.session, ctx.tenant_id)
    return _category(await ExpenseService.create_category(ctx.session, ctx.tenant_id, body.name))


@router.post("", status_code=201, response_model=ExpenseOut)
async def create_expense(body: ExpenseRequest, ctx: PostCtx):
    row = await ExpenseService.create(
        ctx.session,
        ctx.tenant_id,
        category_id=body.category_id,
        description=body.description,
        amount=body.amount,
        payment_method=body.payment_method,
        expense_date=body.expense_date,
        session_id=body.session_id,
        created_by=ctx.user.id,
        shift_override="pos:override" in ctx.permission_codes,
    )
    return _expense(row)


@router.get("", response_model=ExpenseListOut)
async def list_expenses(
    ctx: ReadCtx,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: uuid.UUID | None = None,
    payment_method: Annotated[
        str | None, Query(pattern="^(cash|card|wallet|bank_transfer)$")
    ] = None,
    status: Annotated[str | None, Query(pattern="^(posted|voided)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows = await ExpenseService.list(
        ctx.session,
        ctx.tenant_id,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        payment_method=payment_method,
        status=status,
        limit=limit,
        offset=offset,
    )
    totals = await ExpenseService.totals(
        ctx.session, ctx.tenant_id, date_from=date_from, date_to=date_to
    )
    return {
        "items": [_expense(e) for e in rows],
        "totals": {
            "total": f"{totals['total']:.2f}",
            "count": totals["count"],
            "by_method": {k: f"{v:.2f}" for k, v in totals["by_method"].items()},
            "by_category": {k: f"{v:.2f}" for k, v in totals["by_category"].items()},
        },
    }


@router.get("/{expense_id}", response_model=ExpenseOut)
async def get_expense(expense_id: uuid.UUID, ctx: ReadCtx):
    return _expense(await ExpenseService.get(ctx.session, ctx.tenant_id, expense_id))


@router.post("/{expense_id}/void", response_model=ExpenseOut)
async def void_expense(expense_id: uuid.UUID, body: VoidRequest, ctx: VoidCtx):
    row = await ExpenseService.void(
        ctx.session,
        ctx.tenant_id,
        expense_id,
        reason=body.reason,
        voided_by=ctx.user.id,
        shift_override="pos:override" in ctx.permission_codes,
    )
    return _expense(row)

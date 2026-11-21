"""CUSTOMER ACCOUNT routes: credit sales, instalments, deposits and the statement.

Taking a payment or a deposit is frontline work (`customers:write`, the cashier has it). Opening
credit, setting a limit, adjusting a balance and reversing an entry change what the shop is owed,
so they need `pos:override`: the owner and the manager hold it, the cashier does not.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field

from app.modules.customer_accounts.models import CustomerLedgerEntry
from app.modules.customer_accounts.service import CustomerAccountService as Svc
from app.modules.identity.deps import TenantContext, require_permission

router = APIRouter(prefix="/customer-accounts", tags=["customer-accounts"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("customers:read"))]
FrontCtx = Annotated[TenantContext, Depends(require_permission("customers:write"))]
ManageCtx = Annotated[TenantContext, Depends(require_permission("pos:override"))]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=127)]


class OpenRequest(BaseModel):
    # a fraction-free money string; null = no limit, "0" = deposits and cash only
    credit_limit: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=255)


class AmountRequest(BaseModel):
    amount: str = Field(min_length=1, max_length=20)


class AdjustRequest(BaseModel):
    amount: str = Field(min_length=1, max_length=21, description="+ raises debt, - lowers it")
    reason: str = Field(min_length=1, max_length=500)


class ReverseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AccountOut(BaseModel):
    customer_id: uuid.UUID
    credit_limit: Decimal | None
    note: str | None
    balance: Decimal
    # what the customer owes (>0), or the credit the shop holds for them (<0)
    owes: Decimal
    credit_held: Decimal
    available_credit: Decimal | None


class EntryOut(BaseModel):
    id: uuid.UUID
    seq: int
    entry_type: str
    amount: Decimal
    balance_after: Decimal
    order_id: uuid.UUID | None
    reverses_entry_id: uuid.UUID | None
    reason: str | None
    created_at: str


def _entry(e: CustomerLedgerEntry) -> EntryOut:
    return EntryOut(
        id=e.id,
        seq=e.seq,
        entry_type=e.entry_type,
        amount=Decimal(str(e.amount)),
        balance_after=Decimal(str(e.balance_after)),
        order_id=e.order_id,
        reverses_entry_id=e.reverses_entry_id,
        reason=e.reason,
        created_at=e.created_at.isoformat(),
    )


async def _account_out(ctx: TenantContext, customer_id: uuid.UUID) -> AccountOut:
    from app.modules.errors import NotFoundError

    account = await Svc.get_account(ctx.session, ctx.tenant_id, customer_id)
    if account is None:
        raise NotFoundError("هذا العميل ليس له حساب آجل")
    balance = await Svc.balance(ctx.session, ctx.tenant_id, customer_id)
    limit = None if account.credit_limit is None else Decimal(str(account.credit_limit))
    return AccountOut(
        customer_id=customer_id,
        credit_limit=limit,
        note=account.note,
        balance=balance,
        owes=max(balance, Decimal("0.00")),
        credit_held=max(-balance, Decimal("0.00")),
        available_credit=None if limit is None else max(limit - balance, Decimal("0.00")),
    )


@router.put("/{customer_id}", response_model=AccountOut)
async def open_account(customer_id: uuid.UUID, body: OpenRequest, ctx: ManageCtx):
    await Svc.open_account(
        ctx.session, ctx.tenant_id, customer_id, credit_limit=body.credit_limit, note=body.note
    )
    return await _account_out(ctx, customer_id)


@router.get("/{customer_id}", response_model=AccountOut)
async def get_account(customer_id: uuid.UUID, ctx: ReadCtx):
    return await _account_out(ctx, customer_id)


@router.get("/{customer_id}/statement", response_model=list[EntryOut])
async def statement(
    customer_id: uuid.UUID, ctx: ReadCtx, limit: Annotated[int, Query(ge=1, le=1000)] = 200
):
    rows = await Svc.statement(ctx.session, ctx.tenant_id, customer_id, limit=limit)
    return [_entry(r) for r in rows]


@router.post("/{customer_id}/payments", response_model=EntryOut, status_code=201)
async def receive_payment(
    customer_id: uuid.UUID, body: AmountRequest, ctx: FrontCtx, idempotency_key: IdemKey = None
):
    row = await Svc.receive_payment(
        ctx.session,
        ctx.tenant_id,
        customer_id,
        amount=body.amount,
        idempotency_key=idempotency_key,
        actor_user_id=ctx.user.id,
    )
    return _entry(row)


@router.post("/{customer_id}/deposits", response_model=EntryOut, status_code=201)
async def take_deposit(
    customer_id: uuid.UUID, body: AmountRequest, ctx: FrontCtx, idempotency_key: IdemKey = None
):
    row = await Svc.take_deposit(
        ctx.session,
        ctx.tenant_id,
        customer_id,
        amount=body.amount,
        idempotency_key=idempotency_key,
        actor_user_id=ctx.user.id,
    )
    return _entry(row)


@router.post("/{customer_id}/adjustments", response_model=EntryOut, status_code=201)
async def adjust(customer_id: uuid.UUID, body: AdjustRequest, ctx: ManageCtx):
    row = await Svc.adjust(
        ctx.session,
        ctx.tenant_id,
        customer_id,
        amount=body.amount,
        reason=body.reason,
        actor_user_id=ctx.user.id,
    )
    return _entry(row)


@router.post("/entries/{entry_id}/reverse", response_model=EntryOut, status_code=201)
async def reverse(entry_id: uuid.UUID, body: ReverseRequest, ctx: ManageCtx):
    row = await Svc.reverse(
        ctx.session, ctx.tenant_id, entry_id, reason=body.reason, actor_user_id=ctx.user.id
    )
    return _entry(row)

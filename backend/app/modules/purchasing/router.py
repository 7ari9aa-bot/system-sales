"""PURCHASING routes: suppliers, purchase orders, supplier payments, supplier returns, costs.

Reading needs `inventory:read`. Everything that creates stock, spends money or decides a return
needs `inventory:write` (manager / owner, not the frontline `staff` role).
Amounts travel as STRINGS ("45.50"): a JSON float would already be wrong on the wire.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.modules.identity.deps import TenantContext, require_permission
from app.modules.purchasing.service import (
    CostService,
    PurchaseService,
    SupplierPaymentService,
    SupplierReturnService,
    SupplierService,
)

router = APIRouter(tags=["purchasing"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("inventory:read"))]
WriteCtx = Annotated[TenantContext, Depends(require_permission("inventory:write"))]

METHOD = "^(cash|card|wallet|bank_transfer)$"


def _m(value: Decimal | None) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


def _id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


# ------------------------------------------------------------- suppliers ----


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=31)
    city: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


class SupplierPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=31)
    city: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class StatementOut(BaseModel):
    total_supplied: str
    orders_count: int
    last_order_date: str | None
    items_count: int
    paid: str
    credit_returns: str
    # What the shop still owes (negative: the supplier owes the shop).
    balance: str


class SupplierOut(BaseModel):
    id: str
    name: str
    company: str | None
    contact_name: str | None
    phone: str | None
    city: str | None
    address: str | None
    notes: str | None
    status: str
    statement: StatementOut | None = None


def _statement(st: dict) -> StatementOut:
    return StatementOut(
        total_supplied=_m(st["total_supplied"]),
        orders_count=st["orders_count"],
        last_order_date=st["last_order_date"].isoformat() if st["last_order_date"] else None,
        items_count=st["items_count"],
        paid=_m(st["paid"]),
        credit_returns=_m(st["credit_returns"]),
        balance=_m(st["balance"]),
    )


def _supplier(row, st: dict | None = None) -> SupplierOut:
    return SupplierOut(
        id=str(row.id),
        name=row.name,
        company=row.company,
        contact_name=row.contact_name,
        phone=row.phone,
        city=row.city,
        address=row.address,
        notes=row.notes,
        status=row.status,
        statement=_statement(st) if st else None,
    )


@router.get("/suppliers", response_model=list[SupplierOut])
async def list_suppliers(
    ctx: ReadCtx, status: Annotated[str | None, Query(pattern="^(active|inactive)$")] = None
):
    rows = await SupplierService.list(ctx.session, ctx.tenant_id, status=status)
    return [
        _supplier(r, await SupplierService.statement(ctx.session, ctx.tenant_id, r.id))
        for r in rows
    ]


@router.post("/suppliers", status_code=201, response_model=SupplierOut)
async def create_supplier(body: SupplierIn, ctx: WriteCtx):
    return _supplier(await SupplierService.create(ctx.session, ctx.tenant_id, **body.model_dump()))


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
async def get_supplier(supplier_id: uuid.UUID, ctx: ReadCtx):
    row = await SupplierService.get(ctx.session, ctx.tenant_id, supplier_id)
    return _supplier(row, await SupplierService.statement(ctx.session, ctx.tenant_id, row.id))


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(supplier_id: uuid.UUID, body: SupplierPatch, ctx: WriteCtx):
    row = await SupplierService.update(
        ctx.session, ctx.tenant_id, supplier_id, **body.model_dump(exclude_unset=True)
    )
    return _supplier(row, await SupplierService.statement(ctx.session, ctx.tenant_id, row.id))


# -------------------------------------------------------- purchase orders ----


class PoLineIn(BaseModel):
    variant_id: uuid.UUID
    quantity: str = Field(min_length=1, max_length=10)
    unit_cost: str = Field(min_length=1, max_length=20)


class PoIn(BaseModel):
    supplier_id: uuid.UUID
    lines: list[PoLineIn] = Field(min_length=1, max_length=200)
    order_date: date | None = None
    warehouse_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=255)
    # The till records goods that already arrived. A draft (false) moves nothing until /receive.
    receive_now: bool = False


class PoLineOut(BaseModel):
    variant_id: str
    quantity: int
    unit_cost: str
    line_total: str


class PoOut(BaseModel):
    id: str
    number: str
    supplier_id: str
    warehouse_id: str
    order_date: str
    status: str  # draft | received | cancelled
    total: str
    paid: str
    # Derived from the payments, never stored: unpaid | partial | paid
    payment_status: str
    balance: str
    note: str | None
    received_at: str | None
    created_by_user_id: str | None
    lines: list[PoLineOut]


async def _po_out(ctx, order) -> PoOut:
    lines = await PurchaseService._lines_in(ctx.session, ctx.tenant_id, order.id)
    paid = await PurchaseService.paid_for(ctx.session, ctx.tenant_id, order.id)
    total = Decimal(order.total)
    return PoOut(
        id=str(order.id),
        number=order.number,
        supplier_id=str(order.supplier_id),
        warehouse_id=str(order.warehouse_id),
        order_date=order.order_date.isoformat(),
        status=order.status,
        total=_m(total),
        paid=_m(paid),
        payment_status=PurchaseService.payment_state(total, paid),
        balance=_m(total - paid) if order.status == "received" else _m(Decimal("0")),
        note=order.note,
        received_at=order.received_at.isoformat() if order.received_at else None,
        created_by_user_id=_id(order.created_by_user_id),
        lines=[
            PoLineOut(
                variant_id=str(ln.variant_id),
                quantity=ln.quantity,
                unit_cost=_m(ln.unit_cost),
                line_total=_m(ln.line_total),
            )
            for ln in lines
        ],
    )


@router.get("/purchase-orders", response_model=list[PoOut])
async def list_purchase_orders(
    ctx: ReadCtx,
    supplier_id: uuid.UUID | None = None,
    status: Annotated[str | None, Query(pattern="^(draft|received|cancelled)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows = await PurchaseService.list(
        ctx.session,
        ctx.tenant_id,
        supplier_id=supplier_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [await _po_out(ctx, r) for r in rows]


@router.post("/purchase-orders", status_code=201, response_model=PoOut)
async def create_purchase_order(body: PoIn, ctx: WriteCtx):
    order = await PurchaseService.create(
        ctx.session,
        ctx.tenant_id,
        supplier_id=body.supplier_id,
        lines=[ln.model_dump(mode="json") for ln in body.lines],
        order_date=body.order_date,
        warehouse_id=body.warehouse_id,
        note=body.note,
        receive_now=body.receive_now,
        created_by=ctx.user.id,
    )
    return await _po_out(ctx, order)


@router.get("/purchase-orders/{order_id}", response_model=PoOut)
async def get_purchase_order(order_id: uuid.UUID, ctx: ReadCtx):
    return await _po_out(ctx, await PurchaseService.get(ctx.session, ctx.tenant_id, order_id))


@router.post("/purchase-orders/{order_id}/receive", response_model=PoOut)
async def receive_purchase_order(order_id: uuid.UUID, ctx: WriteCtx):
    return await _po_out(ctx, await PurchaseService.receive(ctx.session, ctx.tenant_id, order_id))


@router.post("/purchase-orders/{order_id}/cancel", response_model=PoOut)
async def cancel_purchase_order(order_id: uuid.UUID, ctx: WriteCtx):
    return await _po_out(ctx, await PurchaseService.cancel(ctx.session, ctx.tenant_id, order_id))


# ---------------------------------------------------------- payments ----


class PaymentIn(BaseModel):
    supplier_id: uuid.UUID
    amount: str = Field(min_length=1, max_length=20)
    method: str = Field(pattern=METHOD)
    purchase_order_id: uuid.UUID | None = None
    paid_on: date | None = None
    session_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=255)


class PaymentOut(BaseModel):
    id: str
    supplier_id: str
    purchase_order_id: str | None
    amount: str
    method: str
    paid_on: str
    session_id: str | None
    note: str | None


@router.post("/supplier-payments", status_code=201, response_model=PaymentOut)
async def create_supplier_payment(body: PaymentIn, ctx: WriteCtx):
    p = await SupplierPaymentService.create(
        ctx.session, ctx.tenant_id, created_by=ctx.user.id, **body.model_dump()
    )
    return PaymentOut(
        id=str(p.id),
        supplier_id=str(p.supplier_id),
        purchase_order_id=_id(p.purchase_order_id),
        amount=_m(p.amount),
        method=p.method,
        paid_on=p.paid_on.isoformat(),
        session_id=_id(p.session_id),
        note=p.note,
    )


class PaymentRowOut(PaymentOut):
    # Set on a reversal row: the payment it cancels. A reversal counts as negative in the balance.
    reverses_payment_id: str | None
    created_by_user_id: str | None


@router.get("/supplier-payments", response_model=list[PaymentRowOut])
async def list_supplier_payments(
    ctx: ReadCtx,
    supplier_id: uuid.UUID | None = None,
    purchase_order_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows = await SupplierPaymentService.list(
        ctx.session,
        ctx.tenant_id,
        supplier_id=supplier_id,
        purchase_order_id=purchase_order_id,
        limit=limit,
        offset=offset,
    )
    return [
        PaymentRowOut(
            id=str(p.id),
            supplier_id=str(p.supplier_id),
            purchase_order_id=_id(p.purchase_order_id),
            amount=_m(p.amount),
            method=p.method,
            paid_on=p.paid_on.isoformat(),
            session_id=_id(p.session_id),
            note=p.note,
            reverses_payment_id=_id(p.reverses_payment_id),
            created_by_user_id=_id(p.created_by_user_id),
        )
        for p in rows
    ]


# ------------------------------------------------------------ returns ----


class ReturnLineIn(BaseModel):
    variant_id: uuid.UUID
    quantity: str = Field(min_length=1, max_length=10)
    # Required only when the return names no purchase order; otherwise the order's own price is
    # used.
    unit_cost: str | None = Field(default=None, max_length=20)


class ReturnIn(BaseModel):
    supplier_id: uuid.UUID
    lines: list[ReturnLineIn] = Field(min_length=1, max_length=200)
    settlement: str = Field(pattern="^(cash|credit|replace)$")
    purchase_order_id: uuid.UUID | None = None
    return_date: date | None = None
    note: str | None = Field(default=None, max_length=255)


class ReturnAccept(BaseModel):
    # A cash refund lands in an open shift's drawer.
    session_id: uuid.UUID | None = None


class ReturnLineOut(BaseModel):
    variant_id: str
    quantity: int
    unit_cost: str
    line_total: str


class ReturnOut(BaseModel):
    id: str
    number: str
    supplier_id: str
    purchase_order_id: str | None
    settlement: str
    status: str  # review | accepted | rejected
    total: str
    return_date: str
    note: str | None
    decided_at: str | None
    lines: list[ReturnLineOut]


async def _return_out(ctx, ret) -> ReturnOut:
    lines = await SupplierReturnService.lines_of(ctx.session, ctx.tenant_id, ret.id)
    return ReturnOut(
        id=str(ret.id),
        number=ret.number,
        supplier_id=str(ret.supplier_id),
        purchase_order_id=_id(ret.purchase_order_id),
        settlement=ret.settlement,
        status=ret.status,
        total=_m(ret.total),
        return_date=ret.return_date.isoformat(),
        note=ret.note,
        decided_at=ret.decided_at.isoformat() if ret.decided_at else None,
        lines=[
            ReturnLineOut(
                variant_id=str(ln.variant_id),
                quantity=ln.quantity,
                unit_cost=_m(ln.unit_cost),
                line_total=_m(ln.line_total),
            )
            for ln in lines
        ],
    )


@router.get("/supplier-returns", response_model=list[ReturnOut])
async def list_supplier_returns(
    ctx: ReadCtx,
    supplier_id: uuid.UUID | None = None,
    status: Annotated[str | None, Query(pattern="^(review|accepted|rejected)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows = await SupplierReturnService.list(
        ctx.session,
        ctx.tenant_id,
        supplier_id=supplier_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [await _return_out(ctx, r) for r in rows]


@router.post("/supplier-returns", status_code=201, response_model=ReturnOut)
async def create_supplier_return(body: ReturnIn, ctx: WriteCtx):
    ret = await SupplierReturnService.create(
        ctx.session,
        ctx.tenant_id,
        supplier_id=body.supplier_id,
        lines=[ln.model_dump(mode="json", exclude_none=True) for ln in body.lines],
        settlement=body.settlement,
        purchase_order_id=body.purchase_order_id,
        return_date=body.return_date,
        note=body.note,
        created_by=ctx.user.id,
    )
    return await _return_out(ctx, ret)


@router.get("/supplier-returns/{return_id}", response_model=ReturnOut)
async def get_supplier_return(return_id: uuid.UUID, ctx: ReadCtx):
    return await _return_out(
        ctx, await SupplierReturnService.get(ctx.session, ctx.tenant_id, return_id)
    )


@router.post("/supplier-returns/{return_id}/accept", response_model=ReturnOut)
async def accept_supplier_return(return_id: uuid.UUID, body: ReturnAccept, ctx: WriteCtx):
    ret = await SupplierReturnService.accept(
        ctx.session, ctx.tenant_id, return_id, session_id=body.session_id, decided_by=ctx.user.id
    )
    return await _return_out(ctx, ret)


@router.post("/supplier-returns/{return_id}/reject", response_model=ReturnOut)
async def reject_supplier_return(return_id: uuid.UUID, ctx: WriteCtx):
    return await _return_out(
        ctx, await SupplierReturnService.reject(ctx.session, ctx.tenant_id, return_id)
    )


# --------------------------------------------------------------- costs ----


class CostOut(BaseModel):
    variant_id: str
    avg_cost: str | None


@router.get("/variant-costs/{variant_id}", response_model=CostOut)
async def get_variant_cost(variant_id: uuid.UUID, ctx: ReadCtx):
    cost = await CostService.get(ctx.session, ctx.tenant_id, variant_id)
    return CostOut(variant_id=str(variant_id), avg_cost=None if cost is None else f"{cost:.4f}")


class CostHistoryOut(BaseModel):
    old_avg_cost: str | None  # None: the cost was unknown before this delivery
    new_avg_cost: str
    on_hand_before: int
    received_quantity: int
    unit_cost: str
    purchase_order_id: str | None
    created_at: str


@router.get("/variant-costs/{variant_id}/history", response_model=list[CostHistoryOut])
async def get_variant_cost_history(
    variant_id: uuid.UUID, ctx: ReadCtx, limit: Annotated[int, Query(ge=1, le=500)] = 100
):
    rows = await CostService.history(ctx.session, ctx.tenant_id, variant_id, limit=limit)
    return [
        CostHistoryOut(
            old_avg_cost=None if h.old_avg_cost is None else f"{h.old_avg_cost:.4f}",
            new_avg_cost=f"{h.new_avg_cost:.4f}",
            on_hand_before=h.on_hand_before,
            received_quantity=h.received_quantity,
            unit_cost=_m(h.unit_cost),
            purchase_order_id=_id(h.purchase_order_id),
            created_at=h.created_at.isoformat(),
        )
        for h in rows
    ]

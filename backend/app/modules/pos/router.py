"""POS routes — thin REST over PosService + PosProfileService (§189).

The scan/quote/sell/close surface is the cashier's day: a code resolves to a
variant, a cart prices, a split tender settles, and the shift closes with a
per-method reconciliation. The profile routes configure the terminal.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.modules.errors import ValidationError
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.pos.override import OverrideDep
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from app.modules.pos.stock_view import StockViewService

router = APIRouter(prefix="/pos", tags=["pos"])

PosWriteCtx = Annotated[TenantContext, Depends(require_permission("orders:write"))]
PosManagerCtx = Annotated[TenantContext, Depends(require_permission("pos:override"))]
PosConfigCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

_MONEY = r"^\d+(\.\d{1,2})?$"


# ------------------------------------------------------------- profiles ----


class CreateProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    code: str = Field(min_length=1, max_length=31)
    warehouse_id: UUID
    default_customer_id: UUID | None = None
    allowed_payment_methods: list[str] | None = None
    require_customer: bool = False
    default_payment_method: str | None = Field(
        default=None, pattern="^(cash|card|wallet|bank_transfer)$"
    )
    item_group_ids: list[str] | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=127)
    warehouse_id: UUID | None = None
    default_customer_id: UUID | None = None
    allowed_payment_methods: list[str] | None = None
    require_customer: bool | None = None
    is_active: bool | None = None
    default_payment_method: str | None = Field(
        default=None, pattern="^(cash|card|wallet|bank_transfer)$"
    )
    item_group_ids: list[str] | None = None


class GrantUserRequest(BaseModel):
    user_id: UUID


def _profile_out(profile) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "code": profile.code,
        "warehouse_id": str(profile.warehouse_id),
        "default_customer_id": (
            str(profile.default_customer_id) if profile.default_customer_id else None
        ),
        "allowed_payment_methods": list(profile.allowed_payment_methods or []),
        "require_customer": profile.require_customer,
        "is_active": profile.is_active,
        "default_payment_method": profile.default_payment_method,
        "item_group_ids": [str(g) for g in (profile.item_group_ids or [])],
    }


@router.post("/profiles", status_code=201)
async def create_profile(body: CreateProfileRequest, ctx: PosConfigCtx):
    profile = await PosProfileService.create(
        ctx.session,
        ctx.tenant_id,
        name=body.name,
        code=body.code,
        warehouse_id=body.warehouse_id,
        default_customer_id=body.default_customer_id,
        allowed_payment_methods=body.allowed_payment_methods,
        require_customer=body.require_customer,
        default_payment_method=body.default_payment_method,
        item_group_ids=body.item_group_ids,
    )
    return _profile_out(profile)


@router.get("/profiles")
async def list_profiles(ctx: TenantCtxDep):
    return [
        _profile_out(p) for p in await PosProfileService.list_profiles(ctx.session, ctx.tenant_id)
    ]


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: UUID, ctx: TenantCtxDep):
    return _profile_out(await PosProfileService.get(ctx.session, ctx.tenant_id, profile_id))


@router.patch("/profiles/{profile_id}")
async def update_profile(profile_id: UUID, body: UpdateProfileRequest, ctx: PosConfigCtx):
    profile = await PosProfileService.update(
        ctx.session,
        ctx.tenant_id,
        profile_id,
        name=body.name,
        warehouse_id=body.warehouse_id,
        default_customer_id=body.default_customer_id,
        allowed_payment_methods=body.allowed_payment_methods,
        require_customer=body.require_customer,
        is_active=body.is_active,
        default_payment_method=body.default_payment_method,
        item_group_ids=body.item_group_ids,
    )
    return _profile_out(profile)


@router.post("/profiles/{profile_id}/users", status_code=201)
async def grant_profile_user(profile_id: UUID, body: GrantUserRequest, ctx: PosConfigCtx):
    row = await PosProfileService.grant_user(ctx.session, ctx.tenant_id, profile_id, body.user_id)
    return {"profile_id": str(row.profile_id), "user_id": str(row.user_id)}


@router.get("/profiles/{profile_id}/users")
async def list_profile_users(profile_id: UUID, ctx: TenantCtxDep):
    rows = await PosProfileService.list_users(ctx.session, ctx.tenant_id, profile_id)
    from app.modules.identity.service import UserService

    out = []
    for r in rows:
        full_name = None
        try:
            full_name = (await UserService.get(ctx.session, r.user_id)).full_name
        except Exception:  # noqa: BLE001 — a deleted user must not blank the list
            full_name = None
        out.append(
            {
                "profile_id": str(r.profile_id),
                "user_id": str(r.user_id),
                "full_name": full_name,
            }
        )
    return out


@router.delete("/profiles/{profile_id}/users/{user_id}", status_code=204)
async def revoke_profile_user(profile_id: UUID, user_id: UUID, ctx: PosConfigCtx):
    await PosProfileService.revoke_user(ctx.session, ctx.tenant_id, profile_id, user_id)


# ------------------------------------------------------------ registers ----


class CreateRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    code: str = Field(min_length=1, max_length=31)
    warehouse_id: UUID
    profile_id: UUID | None = None


class OpenSessionRequest(BaseModel):
    opening_float: str = Field(default="0.00", pattern=_MONEY)
    profile_id: UUID | None = None
    cashier_user_id: UUID | None = None
    # The drawer's float PER METHOD (ERPNext's per-method opening entry);
    # values are money strings, validated in the service.
    floats_by_method: dict[str, str] | None = None


class ScanRequest(BaseModel):
    identifier_type: str = Field(min_length=1, max_length=31)
    value: str = Field(min_length=1, max_length=255)


class QuoteRequest(BaseModel):
    items: list[dict] = Field(min_length=1)
    discount_total: str | None = Field(default=None, pattern=_MONEY)


class TenderLine(BaseModel):
    method: str = Field(pattern="^(cash|card|wallet|bank_transfer)$")
    amount: str = Field(pattern=_MONEY)


class SellRequest(BaseModel):
    # Optional ONLY when held_cart_id names the cart whose lines are the sale.
    items: list[dict] | None = None
    customer_id: UUID | None = None
    # Legacy single-tender shape; or pass `tenders` for a split payment.
    method: str | None = Field(default=None, pattern="^(cash|card|wallet|bank_transfer)$")
    amount: str | None = Field(default=None, pattern=_MONEY)
    tenders: list[TenderLine] | None = None
    discount_total: str | None = Field(default=None, pattern=_MONEY)
    tendered_cash: str | None = Field(default=None, pattern=_MONEY)
    # Atomic resume: the cart's lines become this sale inside one transaction.
    held_cart_id: UUID | None = None


class RecordSaleRequest(BaseModel):
    """A counter sale. The cashier records WHAT was sold; how it was paid is not part of it.

    ``extra="forbid"``: a client that still sends ``method``/``amount``/``tenders`` or a seller
    id is refused rather than ignored. Ignoring a payment field would let the client believe
    money was handled; the seller is always the authenticated caller, never a body field.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[dict] = Field(min_length=1)
    customer_id: UUID | None = None
    discount_total: str | None = Field(default=None, pattern=_MONEY)
    # A free-text remark on the invoice (e.g. "gift", "deliver tomorrow"); blank counts as none.
    note: str | None = Field(default=None, max_length=512)


class WorkingSessionOut(BaseModel):
    """The few session fields the till needs; extra keys of the legacy shape are kept."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    register_id: UUID
    profile_id: UUID | None = None
    status: str
    opened_at: str


class RecordSaleOut(BaseModel):
    order_id: UUID
    order_number: str
    receipt_id: UUID
    receipt_number: str
    grand_total: str


class CloseSessionRequest(BaseModel):
    counted_cash: str = Field(pattern=_MONEY)
    # Optional per-method counts; keys are payment methods, values are counts.
    counted_by_method: dict[str, str] | None = None


class HoldCartRequest(BaseModel):
    items: list[dict] = Field(min_length=1)
    customer_id: UUID | None = None
    discount_total: str | None = Field(default=None, pattern=_MONEY)
    label: str | None = Field(default=None, max_length=127)


class RefundRequest(BaseModel):
    order_id: UUID
    amount: str = Field(pattern=_MONEY)
    method: str = Field(default="cash", pattern="^(cash|card|wallet|bank_transfer)$")
    reason: str = Field(default="customer_return", max_length=31)
    # Deprecated and ignored: a money-only refund never restocks (it cannot know which goods came
    # back). Use /returns, which is line-aware. Kept so older clients still validate.
    restock: bool = False


class ReturnLine(BaseModel):
    variant_id: UUID
    quantity: int = Field(ge=1)


class ReturnRequest(BaseModel):
    """A line-level return of a POS sale (ERPNext's POS return document)."""

    order_id: UUID
    lines: list[ReturnLine] = Field(min_length=1)
    restock: bool = False


class ExchangeLine(BaseModel):
    variant_id: UUID
    quantity: int = Field(ge=1)


class ExchangeRequest(BaseModel):
    """The one-transaction exchange: return lines and their replacement sale
    settle together, and only the net difference moves money."""

    order_id: UUID
    return_lines: list[ExchangeLine] = Field(min_length=1)
    new_lines: list[ExchangeLine] = Field(min_length=1)
    restock: bool = True
    # Only the NET amount the customer still owes is tendered through these;
    # a net refund needs no tenders at all.
    tenders: list[TenderLine] | None = None
    method: str | None = Field(default=None, pattern="^(cash|card|wallet|bank_transfer)$")
    amount: str | None = Field(default=None, pattern=_MONEY)
    tendered_cash: str | None = Field(default=None, pattern=_MONEY)


def _session_out(pos_session, inflow=None, outflow=None, expected_now=None) -> dict:
    out = {
        "id": str(pos_session.id),
        "register_id": str(pos_session.register_id),
        "profile_id": str(pos_session.profile_id) if pos_session.profile_id else None,
        "cashier_user_id": (
            str(pos_session.cashier_user_id) if pos_session.cashier_user_id else None
        ),
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
        "profile_id": str(register.profile_id) if register.profile_id else None,
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
        profile_id=body.profile_id,
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
        profile_id=body.profile_id,
        cashier_user_id=body.cashier_user_id,
        floats_by_method=body.floats_by_method,
    )
    return _session_out(pos_session)


@router.get("/sessions")
async def list_sessions(
    ctx: TenantCtxDep,
    status: str | None = None,
    register_id: UUID | None = None,
):
    """Resume the till: sessions behind this drawer, newest first."""
    rows = await PosService.list_sessions(
        ctx.session, ctx.tenant_id, status=status, register_id=register_id
    )
    return [_session_out(s) for s in rows]


@router.get("/sessions/{session_id}")
async def get_session(session_id: UUID, ctx: TenantCtxDep):
    detail = await PosService.get_session(ctx.session, ctx.tenant_id, session_id)
    return _session_out(
        detail["session"],
        inflow=detail["inflow"],
        outflow=detail["outflow"],
        expected_now=detail["expected_now"],
    )


@router.post("/sessions/{session_id}/scan")
async def scan(session_id: UUID, body: ScanRequest, ctx: PosWriteCtx):
    """§179: a code resolves to one variant, priced — the till's entry point."""
    result = await PosService.scan(
        ctx.session,
        ctx.tenant_id,
        session_id,
        identifier_type=body.identifier_type,
        value=body.value,
    )
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in result.items()}


@router.post("/sessions/{session_id}/quote")
async def quote(session_id: UUID, body: QuoteRequest, ctx: PosWriteCtx):
    """Price a cart without writing anything — what the customer sees."""
    return await PosService.quote(
        ctx.session,
        ctx.tenant_id,
        session_id,
        items=body.items,
        discount_total=body.discount_total,
    )


@router.get("/sessions/{session_id}/close-preview")
async def get_close_preview(session_id: UUID, ctx: TenantCtxDep):
    """The close screen's target: per-method expected + sales summary."""
    preview = await PosService.close_preview(ctx.session, ctx.tenant_id, session_id)
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in preview.items()}


class OpenDayRequest(BaseModel):
    """Starting the day needs the drawer's real balance. No default, so none can be skipped."""

    model_config = ConfigDict(extra="forbid")

    opening_float: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class DayStateOut(BaseModel):
    """Whether the register's day has been started. ``session`` is None until it has."""

    started: bool
    session: WorkingSessionOut | None = None


@router.post("/registers/{register_id}/working-session", response_model=DayStateOut)
async def working_session(register_id: UUID, ctx: PosWriteCtx):
    """Has today been started on this register? Read-only: it never opens a day.

    Returns the day's session once an opening balance was entered, otherwise
    ``started: false`` and the screen asks for the balance (``POST .../open-day``).
    """
    found = await PosService.working_session(ctx.session, ctx.tenant_id, register_id)
    return {"started": found is not None, "session": _session_out(found) if found else None}


@router.post("/registers/{register_id}/open-day", response_model=DayStateOut, status_code=201)
async def open_day(register_id: UUID, body: OpenDayRequest, ctx: PosWriteCtx):
    """Start the day with the drawer's real opening balance (required). Idempotent: a second
    call returns the day already open and keeps the first figure."""
    opened = await PosService.open_day(
        ctx.session,
        ctx.tenant_id,
        register_id,
        opening_float=body.opening_float,
        actor_user_id=ctx.user.id,
    )
    return {"started": True, "session": _session_out(opened)}


@router.post("/registers/{register_id}/sales", status_code=201, response_model=RecordSaleOut)
async def record_sale(register_id: UUID, body: RecordSaleRequest, ctx: PosWriteCtx):
    """Record a sale: no shift to open, no payment to take. Stock comes off the shelf."""
    return await PosService.record_sale(
        ctx.session,
        ctx.tenant_id,
        register_id,
        items=body.items,
        customer_id=body.customer_id,
        discount_total=body.discount_total,
        note=(body.note or "").strip() or None,
        actor_user_id=ctx.user.id,
    )


@router.post("/sessions/{session_id}/sell")
async def sell(session_id: UUID, body: SellRequest, ctx: PosWriteCtx, override: OverrideDep):
    """§189: the whole sell is one command chain in one transaction."""
    tenders = (
        [{"method": t.method, "amount": t.amount} for t in body.tenders] if body.tenders else None
    )
    result = await PosService.sell(
        ctx.session,
        ctx.tenant_id,
        session_id,
        customer_id=body.customer_id,
        items=body.items,
        tenders=tenders,
        method=body.method,
        amount=body.amount,
        discount_total=body.discount_total,
        tendered_cash=body.tendered_cash,
        held_cart_id=body.held_cart_id,
        actor_user_id=ctx.user.id,
        shift_override=override.active,
    )
    return {k: str(v) for k, v in result.items()}


@router.post("/sessions/{session_id}/close")
async def close_session(
    session_id: UUID, body: CloseSessionRequest, ctx: PosWriteCtx, override: OverrideDep
):
    pos_session = await PosService.close_session(
        ctx.session,
        ctx.tenant_id,
        session_id,
        counted_cash=body.counted_cash,
        counted_by_method=body.counted_by_method,
        closed_by=ctx.user.id,
        shift_override=override.active,
    )
    return _session_out(pos_session)


@router.get("/sessions/{session_id}/reconciliation")
async def get_reconciliation(session_id: UUID, ctx: TenantCtxDep):
    rows = await PosService.list_reconciliation(ctx.session, ctx.tenant_id, session_id)
    return [
        {
            "method": r.method,
            "expected_amount": str(r.expected_amount),
            "counted_amount": str(r.counted_amount),
            "variance": str(r.variance),
        }
        for r in rows
    ]


# ------------------------------------------------------------- receipts ----


@router.get("/receipts/search")
async def search_receipts(
    ctx: TenantCtxDep,
    q: Annotated[str, Query(min_length=3, max_length=40)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Find an original sale receipt on ANY shift — a return need not be on the sale's shift."""
    rows = await PosService.search_receipts(ctx.session, ctx.tenant_id, q=q, limit=limit)
    return [
        {
            **row,
            "id": str(row["id"]),
            "order_id": str(row["order_id"]),
            "session_id": str(row["session_id"]),
        }
        for row in rows
    ]


@router.get("/sessions/{session_id}/receipts")
async def list_receipts(session_id: UUID, ctx: TenantCtxDep):
    """The shift's receipts with their return state — the refund picker."""
    rows = await PosService.list_receipts(ctx.session, ctx.tenant_id, session_id)
    return [
        {
            **row,
            "id": str(row["id"]),
            "order_id": str(row["order_id"]),
            "session_id": str(row["session_id"]),
        }
        for row in rows
    ]


@router.get("/reports/top-products")
async def top_products_report(ctx: TenantCtxDep, since: str, until: str, limit: int = 20):
    """Best sellers over ``[since, until]`` (YYYY-MM-DD, inclusive).

    Quantity and net revenue, less what came back in the window. No cost or profit: an order line
    does not keep the cost at the time of sale.
    """
    try:
        lo, hi = date.fromisoformat(since), date.fromisoformat(until)
    except ValueError:
        raise ValidationError("since and until must be YYYY-MM-DD") from None
    if hi < lo:
        raise ValidationError("until must not be before since")
    if (hi - lo).days > 366:
        raise ValidationError("the range is limited to 366 days")
    return await PosService.top_products(
        ctx.session, ctx.tenant_id, since=lo, until=hi, limit=limit
    )


@router.get("/reports/sales")
async def sales_report(ctx: TenantCtxDep, since: str, until: str):
    """Sales per shop day over ``[since, until]`` (YYYY-MM-DD, inclusive), newest day first.

    Straight from the receipts and the shop's own calendar day, so a day equals the sum of its
    shifts. A range is capped so one request cannot scan the whole history.
    """
    try:
        lo, hi = date.fromisoformat(since), date.fromisoformat(until)
    except ValueError:
        raise ValidationError("since and until must be YYYY-MM-DD") from None
    if hi < lo:
        raise ValidationError("until must not be before since")
    if (hi - lo).days > 366:
        raise ValidationError("the range is limited to 366 days")
    return await PosService.sales_by_day(ctx.session, ctx.tenant_id, since=lo, until=hi)


@router.get("/reports/daily")
async def daily_report(
    ctx: TenantCtxDep,
    business_date: str,
    register_id: UUID | None = None,
):
    """The event-fed daily projection: one row per register for the date."""
    try:
        day = date.fromisoformat(business_date)
    except ValueError:
        raise ValidationError("business_date must be YYYY-MM-DD") from None
    rows = await PosService.daily_report(
        ctx.session, ctx.tenant_id, business_date=day, register_id=register_id
    )
    return [
        {
            "business_date": str(r.business_date),
            "register_id": str(r.register_id),
            "session_count": r.session_count,
            "invoice_count": r.invoice_count,
            "returns_count": r.returns_count,
            "sales_total": str(r.sales_total),
            "returns_total": str(r.returns_total),
            "taxes_total": str(r.taxes_total),
            "variance_total": str(r.variance_total),
            "by_method": list(r.by_method or []),
        }
        for r in rows
    ]


@router.get("/sessions/{session_id}/items")
async def browse_items(
    session_id: UUID,
    ctx: TenantCtxDep,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    """The till's catalog grid: active variants, ladder price, bin stock."""
    return await PosService.browse(
        ctx.session, ctx.tenant_id, session_id, q=q, limit=limit, offset=offset
    )


@router.get("/sessions/{session_id}/report")
async def get_session_report(session_id: UUID, ctx: TenantCtxDep):
    """The shift's report — per method, cash trail, sales, returns."""
    return await PosService.session_report(ctx.session, ctx.tenant_id, session_id)


@router.get("/receipts/{receipt_id}")
async def get_receipt(receipt_id: UUID, ctx: TenantCtxDep):
    """The printed artifact: receipt header + order lines + tenders."""
    payload = await PosService.get_receipt(ctx.session, ctx.tenant_id, receipt_id)
    return {
        "receipt": {
            **payload["receipt"],
            "id": str(payload["receipt"]["id"]),
        },
        "order": {
            **payload["order"],
            "id": str(payload["order"]["id"]),
        },
        "lines": [{**line, "variant_id": str(line["variant_id"])} for line in payload["lines"]],
        "tenders": payload["tenders"],
    }


class ReceiptEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.post("/receipts/{receipt_id}/email", status_code=202)
async def email_receipt(receipt_id: UUID, body: ReceiptEmailRequest, ctx: PosWriteCtx):
    """Queue "email me this receipt" — sent by the pos worker pool, never
    inline. Refused up front when the deployment has no email delivery."""
    result = await PosService.request_receipt_email(
        ctx.session,
        ctx.tenant_id,
        receipt_id,
        email=body.email,
        requested_by=ctx.user.id,
    )
    return {**result, "receipt_id": str(result["receipt_id"])}


# ---------------------------------------------------------- held carts ----


def _held_cart_out(held) -> dict:
    return {
        "id": str(held.id),
        "session_id": str(held.session_id),
        "items": list(held.items or []),
        "customer_id": str(held.customer_id) if held.customer_id else None,
        "discount_total": str(held.discount_total) if held.discount_total is not None else None,
        "label": held.label,
        "held_by_user_id": str(held.held_by_user_id) if held.held_by_user_id else None,
        "created_at": held.created_at.isoformat(),
    }


@router.post("/sessions/{session_id}/held-carts", status_code=201)
async def hold_cart(session_id: UUID, body: HoldCartRequest, ctx: PosWriteCtx):
    """Park a basket on the open session; reserve nothing, book nothing."""
    held = await PosService.hold_cart(
        ctx.session,
        ctx.tenant_id,
        session_id,
        items=body.items,
        customer_id=body.customer_id,
        discount_total=body.discount_total,
        label=body.label,
        held_by=ctx.user.id,
    )
    return _held_cart_out(held)


@router.get("/sessions/{session_id}/held-carts")
async def list_held_carts(session_id: UUID, ctx: TenantCtxDep):
    rows = await PosService.list_held_carts(ctx.session, ctx.tenant_id, session_id)
    return [_held_cart_out(h) for h in rows]


@router.get("/held-carts/{held_cart_id}")
async def get_held_cart(held_cart_id: UUID, ctx: TenantCtxDep):
    return _held_cart_out(await PosService.get_held_cart(ctx.session, ctx.tenant_id, held_cart_id))


@router.delete("/held-carts/{held_cart_id}", status_code=204)
async def release_held_cart(held_cart_id: UUID, ctx: PosWriteCtx):
    await PosService.release_held_cart(ctx.session, ctx.tenant_id, held_cart_id)


# ------------------------------------------------------------- refunds ----


@router.post("/sessions/{session_id}/refunds", status_code=201)
async def refund(session_id: UUID, body: RefundRequest, ctx: PosWriteCtx, override: OverrideDep):
    """Refund a POS sale by AMOUNT — the money-only path (goodwill, adjust).

    For returning goods, use ``/returns``: it is line-aware, priced at the
    original sale, and allocates the money across the original tenders.
    """
    return await PosService.refund(
        ctx.session,
        ctx.tenant_id,
        session_id,
        order_id=body.order_id,
        amount=body.amount,
        method=body.method,
        reason=body.reason,
        restock=False,
        actor_user_id=ctx.user.id,
        shift_override=override.active,
    )


@router.post("/sessions/{session_id}/returns", status_code=201)
async def return_sale(
    session_id: UUID, body: ReturnRequest, ctx: PosWriteCtx, override: OverrideDep
):
    """Line-level return of a POS sale, with its own POS-RET receipt."""
    result = await PosService.return_sale(
        ctx.session,
        ctx.tenant_id,
        session_id,
        order_id=body.order_id,
        lines=[
            {"variant_id": str(line.variant_id), "quantity": line.quantity} for line in body.lines
        ],
        restock=body.restock,
        actor_user_id=ctx.user.id,
        shift_override=override.active,
    )
    return {
        **result,
        "receipt_id": str(result["receipt_id"]),
    }


@router.post("/sessions/{session_id}/exchanges", status_code=201)
async def exchange(
    session_id: UUID, body: ExchangeRequest, ctx: PosWriteCtx, override: OverrideDep
):
    """One-transaction exchange: the return funds its replacement, and only
    the net difference moves money — two receipts, one commit."""
    tenders = (
        [{"method": t.method, "amount": t.amount} for t in body.tenders] if body.tenders else None
    )
    result = await PosService.exchange(
        ctx.session,
        ctx.tenant_id,
        session_id,
        order_id=body.order_id,
        return_lines=[
            {"variant_id": str(line.variant_id), "quantity": line.quantity}
            for line in body.return_lines
        ],
        new_lines=[
            {"variant_id": str(line.variant_id), "quantity": line.quantity}
            for line in body.new_lines
        ],
        restock=body.restock,
        tenders=tenders,
        method=body.method,
        amount=body.amount,
        tendered_cash=body.tendered_cash,
        actor_user_id=ctx.user.id,
        shift_override=override.active,
    )
    return {
        **result,
        "return_receipt_id": str(result["return_receipt_id"]),
        "new_receipt_id": str(result["new_receipt_id"]),
    }


class StockRow(BaseModel):
    variant_id: str
    product_id: str
    product_title: str
    category_id: str | None
    category: str | None
    sku: str | None
    options: dict[str, str]
    barcode: str | None
    price: str
    avg_cost: str | None  # null = nobody recorded a cost; it is NOT zero
    on_hand: int
    reserved: int
    reorder_level: int  # 0 = no alert configured
    status: str  # in | low | out, decided by the backend and nowhere else
    stock_cost_value: str | None
    stock_retail_value: str


class StockSummary(BaseModel):
    variants: int
    pieces: int
    out: int
    low: int
    alerts: int
    cost_value: str
    retail_value: str
    unknown_cost_variants: int


class ReorderLevelRequest(BaseModel):
    # strict: a JSON `true` or "3" must not become a level (bool is an int in Python).
    reorder_level: int = Field(strict=True, ge=0, le=1_000_000)


@router.get("/stock", response_model=list[StockRow])
async def list_stock(
    ctx: TenantCtxDep,
    term: Annotated[str | None, Query(max_length=100)] = None,
    category_id: UUID | None = None,
    status: Annotated[str | None, Query(pattern="^(in|low|out)$")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """One joined row per active variant: names, options, barcode, price, cost, on-hand, level."""
    return await StockViewService.list_stock(
        ctx.session,
        ctx.tenant_id,
        term=term,
        category_id=category_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/stock/summary", response_model=StockSummary)
async def stock_summary(ctx: TenantCtxDep):
    """Totals over every active variant, not over the page the screen shows."""
    return await StockViewService.summary(ctx.session, ctx.tenant_id)


@router.put("/stock/{variant_id}/reorder-level", response_model=ReorderLevelRequest)
async def set_reorder_level(
    variant_id: UUID,
    body: ReorderLevelRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    # Answer with what the database now holds, not an echo of the request.
    level = await StockViewService.set_reorder_level(
        ctx.session, ctx.tenant_id, variant_id, body.reorder_level
    )
    return ReorderLevelRequest(reorder_level=level)


class OpenStocktakeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=255)


class StocktakeCount(BaseModel):
    variant_id: UUID
    # strict: a JSON `true` or "3" must not become a count; null means "not counted".
    counted_qty: int | None = Field(default=None, strict=True, ge=0, le=1_000_000)


class StocktakeCountsRequest(BaseModel):
    counts: list[StocktakeCount] = Field(min_length=1, max_length=5000)


@router.get("/stocktakes")
async def list_stocktakes(
    ctx: TenantContext = Depends(require_permission("inventory:write")),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await StockViewService.list_stocktakes(ctx.session, ctx.tenant_id, limit=limit)


@router.post("/stocktakes", status_code=201)
async def open_stocktake(
    body: OpenStocktakeRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    """Start a count of the shop's warehouse. One open count at a time."""
    return await StockViewService.open_default_stocktake(
        ctx.session, ctx.tenant_id, user_id=ctx.user.id, note=body.note
    )


@router.get("/stocktakes/{stocktake_id}")
async def get_stocktake(
    stocktake_id: UUID,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    return await StockViewService.stocktake_detail(ctx.session, ctx.tenant_id, stocktake_id)


@router.put("/stocktakes/{stocktake_id}/counts")
async def save_stocktake_counts(
    stocktake_id: UUID,
    body: StocktakeCountsRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    """Save counted quantities. Nothing in stock moves until a manager approves."""
    saved = await StockViewService.record_stocktake_counts(
        ctx.session,
        ctx.tenant_id,
        stocktake_id,
        [{"variant_id": str(c.variant_id), "counted_qty": c.counted_qty} for c in body.counts],
    )
    return {"saved": saved}


@router.post("/stocktakes/{stocktake_id}/approve")
async def approve_stocktake(stocktake_id: UUID, ctx: PosManagerCtx):
    """Apply the count to the ledger. Manager/owner only: this is what changes the balances."""
    return await StockViewService.approve_stocktake(
        ctx.session, ctx.tenant_id, stocktake_id, user_id=ctx.user.id
    )


@router.post("/stocktakes/{stocktake_id}/cancel")
async def cancel_stocktake(
    stocktake_id: UUID,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    await StockViewService.cancel_stocktake(
        ctx.session, ctx.tenant_id, stocktake_id, user_id=ctx.user.id
    )
    return {"status": "CANCELLED"}

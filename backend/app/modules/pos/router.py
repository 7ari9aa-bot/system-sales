"""POS routes — thin REST over PosService + PosProfileService (§189).

The scan/quote/sell/close surface is the cashier's day: a code resolves to a
variant, a cart prices, a split tender settles, and the shift closes with a
per-method reconciliation. The profile routes configure the terminal.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictInt, field_validator

from app.modules.errors import ValidationError
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.pos.override import OverrideDep
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from app.modules.pos.stock_view import StockViewService

router = APIRouter(prefix="/pos", tags=["pos"])

PosReadCtx = Annotated[TenantContext, Depends(require_permission("orders:read"))]
PosStockReadCtx = Annotated[TenantContext, Depends(require_permission("inventory:read"))]
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
    # The shop owner's discount ceiling, percent 0 to 100. Absent or null = no ceiling.
    max_discount_pct: str | int | float | None = None


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
    # A number sets the ceiling; ``null`` sent on purpose removes it; leaving it out keeps it.
    max_discount_pct: str | int | float | None = None


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
        "max_discount_pct": (
            None if profile.max_discount_pct is None else str(profile.max_discount_pct)
        ),
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
        max_discount_pct=body.max_discount_pct,
    )
    return _profile_out(profile)


@router.get("/profiles")
async def list_profiles(ctx: PosReadCtx):
    return [
        _profile_out(p) for p in await PosProfileService.list_profiles(ctx.session, ctx.tenant_id)
    ]


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: UUID, ctx: PosReadCtx):
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
        # ``null`` sent on purpose clears it; a field left out of the body leaves it alone.
        clear_default_customer=(
            "default_customer_id" in body.model_fields_set and body.default_customer_id is None
        ),
        allowed_payment_methods=body.allowed_payment_methods,
        require_customer=body.require_customer,
        is_active=body.is_active,
        default_payment_method=body.default_payment_method,
        item_group_ids=body.item_group_ids,
        max_discount_pct=body.max_discount_pct,
        clear_max_discount=(
            "max_discount_pct" in body.model_fields_set and body.max_discount_pct is None
        ),
    )
    return _profile_out(profile)


@router.post("/profiles/{profile_id}/users", status_code=201)
async def grant_profile_user(profile_id: UUID, body: GrantUserRequest, ctx: PosConfigCtx):
    row = await PosProfileService.grant_user(ctx.session, ctx.tenant_id, profile_id, body.user_id)
    return {"profile_id": str(row.profile_id), "user_id": str(row.user_id)}


@router.get("/profiles/{profile_id}/users")
async def list_profile_users(profile_id: UUID, ctx: PosReadCtx):
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


class ScanRequest(BaseModel):
    identifier_type: str = Field(min_length=1, max_length=31)
    value: str = Field(min_length=1, max_length=255)


class CartLine(BaseModel):
    """One cart line: a real variant, a whole quantity of at least one, an optional line discount.

    ``StrictInt`` so ``true``, ``2.5`` and ``"2"`` are refused instead of quietly becoming 1 or 2.
    Keys the till does not read (a title, a display price) are dropped, never trusted.
    """

    model_config = ConfigDict(extra="ignore")

    variant_id: UUID
    quantity: StrictInt = Field(ge=1, le=100000)
    discount_pct: str | int | float | None = None

    @field_validator("discount_pct")
    @classmethod
    def _pct_in_range(cls, v):
        if v is None:
            return v
        if isinstance(v, bool):
            raise ValueError("discount_pct must be a number between 0 and 100")
        try:
            pct = Decimal(str(v))
        except Exception as exc:
            raise ValueError("discount_pct must be a number between 0 and 100") from exc
        if not pct.is_finite() or pct < 0 or pct > 100:
            raise ValueError("discount_pct must be between 0 and 100")
        return v


def _lines(items: list[CartLine]) -> list[dict]:
    """The service reads plain dicts; hand it the validated ones (ids as strings, as before)."""
    return [i.model_dump(mode="json", exclude_none=True) for i in items]


class QuoteRequest(BaseModel):
    items: list[CartLine] = Field(min_length=1)
    discount_total: str | None = Field(default=None, pattern=_MONEY)


class PaymentLine(BaseModel):
    """One way the customer paid. ``tendered`` is only for cash (the note handed over)."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(min_length=1, max_length=31)
    amount: str = Field(pattern=_MONEY)
    tendered: str | None = Field(default=None, pattern=_MONEY)
    # Card approval number, transfer reference. Required for the methods the shop lists in
    # ``pos.reference_required_methods``.
    reference: str | None = Field(default=None, max_length=63)


class PrescriptionRef(BaseModel):
    """The prescription a medicine was sold against: its number and who it is for."""

    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=63)
    name: str = Field(min_length=1, max_length=127)


class RecordSaleRequest(BaseModel):
    """A counter sale. The cashier records WHAT was sold and, if the shop turned it on, HOW it
    was paid.

    ``extra="forbid"``: a client that sends an unknown field or a seller id is refused rather
    than ignored; the seller is always the authenticated caller, never a body field. ``payments``
    is accepted only when the shop's ``pos.take_payments`` is on, and required then. Ignoring a
    payment field would let the client believe money was handled, so a till that does not record
    payments refuses it.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[CartLine] = Field(min_length=1)
    customer_id: UUID | None = None
    # OPTIONAL phone (and the name typed with it) of a customer who was not picked from the list.
    # With a phone, the sale is booked to the customer holding that number (created if new), so
    # the customer can later find their invoice from a chat. Ignored when ``customer_id`` is set:
    # an explicit pick always wins. An unusable number never refuses the sale (see
    # ``customer_notice`` on the response).
    customer_phone: str | None = Field(default=None, max_length=31)
    customer_name: str | None = Field(default=None, max_length=127)
    discount_total: str | None = Field(default=None, pattern=_MONEY)
    # A free-text remark on the invoice (e.g. "gift", "deliver tomorrow"); blank counts as none.
    note: str | None = Field(default=None, max_length=512)
    payments: list[PaymentLine] | None = Field(default=None, max_length=8)
    # Put whatever the customer did not pay now on their credit account. Needs a named customer
    # and the shop's pos.allow_sale_on_account; refused when the account's limit would be passed.
    on_account: bool = False
    # Required for a prescription-only product when the shop turned on ``prescription_required``;
    # kept on the invoice otherwise.
    prescription: PrescriptionRef | None = None


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
    # None when the sale is booked as asked. "phone_not_recorded" when a phone was typed but could
    # not be attached to the invoice: the sale itself still went through, but the customer will not
    # be able to follow it from a chat. The till shows a notice and the cashier can fix it.
    customer_notice: str | None = None
    # Set only when the till records payments: what was collected and the change handed back
    # (change is None when nothing was paid in cash).
    paid: str | None = None
    change: str | None = None
    # The part of the sale put on the customer's account; None when the sale was not on account.
    on_account: str | None = None
    # How much of the customer's held deposit paid for this sale (None when not on account).
    deposit_used: str | None = None


class HoldCartRequest(BaseModel):
    items: list[CartLine] = Field(min_length=1)
    customer_id: UUID | None = None
    discount_total: str | None = Field(default=None, pattern=_MONEY)
    label: str | None = Field(default=None, max_length=127)


class ReturnLine(BaseModel):
    variant_id: UUID
    quantity: StrictInt = Field(ge=1, le=100000)
    # One of the shop's pos.return_reasons; checked against that list when the return is made.
    reason: str | None = Field(default=None, max_length=63)
    # This piece's own shelf decision (a jacket back on the rail, a torn one not). None = the
    # request's choice, else the shop's pos.return_restock_default.
    restock: bool | None = None
    # The state the garment came back in, which decides where it goes: `sellable` (back on the
    # rail), `quarantine` (there, waiting for inspection), `damaged` (there, never sellable),
    # `writeoff` (destroyed, not stock), `supplier` (going back to the supplier, not stock).
    # None = sellable.
    condition: str | None = Field(default=None, max_length=15)


class RefundLine(BaseModel):
    """One tender to give money back on: the method and how much of the return it covers."""

    method: str = Field(min_length=1, max_length=31)
    amount: str | float | int


class ReturnRequest(BaseModel):
    """A line-level return of a POS sale (ERPNext's POS return document) AND its refund.

    The money goes back across the tenders the sale actually collected: cash first, then the rest
    in the order they were taken. ``refund`` overrides that with explicit per-method amounts (give
    the notes back even though the card was charged); ``refund_method`` refunds the whole return on
    one method. Send neither to use the shop's policy.
    """

    order_id: UUID
    lines: list[ReturnLine] = Field(min_length=1)
    # None = the shop's pos.return_restock_default (a line can still override it).
    restock: bool | None = None
    # Explicit per-method refund lines. Each must be satisfiable from that method's own collected
    # amount, so every refund still points at a real payment.
    refund: list[RefundLine] | None = None
    # Refund the whole return on this one method. Mutually exclusive with ``refund``.
    refund_method: str | None = Field(default=None, max_length=31)
    # {method: terminal reference} for a card/wallet reversal the cashier already made. Without
    # one, that part of the refund is written `pending` and the response says so in
    # `awaiting_confirmation`: the money is promised, not yet proven.
    refund_references: dict[str, str] | None = None


class ExchangeLine(BaseModel):
    variant_id: UUID
    quantity: StrictInt = Field(ge=1, le=100000)
    reason: str | None = Field(default=None, max_length=63)
    restock: bool | None = None  # as on ReturnLine; only meaningful on the returned side
    # As on ReturnLine: the state the garment came back in decides where it goes (a torn piece in a
    # swap must not go straight back on the rail). None = sellable.
    condition: str | None = Field(default=None, max_length=15)


class ExchangeRequest(BaseModel):
    """The one-transaction exchange: return lines, their replacement sale, and the difference.

    A replacement that costs more needs ``payments`` covering the difference; one that costs less
    is refunded across the original tenders (or per ``refund`` / ``refund_method``); an equal swap
    moves nothing and says so.
    """

    order_id: UUID
    return_lines: list[ExchangeLine] = Field(min_length=1)
    new_lines: list[ExchangeLine] = Field(min_length=1)
    restock: bool | None = None
    # How the customer pays the difference when the replacement costs more.
    payments: list[dict] | None = None
    # How the difference goes back when the replacement costs less.
    refund: list[RefundLine] | None = None
    refund_method: str | None = Field(default=None, max_length=31)
    # As on ReturnRequest: the terminal's reference for a card/wallet reversal of the difference.
    refund_references: dict[str, str] | None = None


def _session_out(pos_session, inflow=None, outflow=None, expected_now=None) -> dict:
    out = {
        "id": str(pos_session.id),
        "register_id": str(pos_session.register_id),
        "profile_id": str(pos_session.profile_id) if pos_session.profile_id else None,
        # A day started without a shift has no shift holder, so the person shown as the cashier is
        # whoever started it; a drawer that does have a holder keeps showing that holder.
        "cashier_user_id": (
            str(pos_session.cashier_user_id or pos_session.opened_by_user_id)
            if (pos_session.cashier_user_id or pos_session.opened_by_user_id)
            else None
        ),
        "opened_by_user_id": (
            str(pos_session.opened_by_user_id) if pos_session.opened_by_user_id else None
        ),
        "status": pos_session.status,
        "opening_float": str(pos_session.opening_float),
        "opened_at": pos_session.opened_at.isoformat(),
    }
    if pos_session.status == "CLOSED":
        out.update(
            {
                # The day is recorded, not counted: the closing balance is derived from the
                # invoices and returns, and there is no counted figure or variance.
                "closing_balance": (
                    None if pos_session.expected_cash is None else str(pos_session.expected_cash)
                ),
                "closed_at": pos_session.closed_at.isoformat() if pos_session.closed_at else None,
            }
        )
        # Only a drawer that was counted has these. A till that does not count keeps exactly the
        # answer it always had, so nothing reads a missing count as a zero.
        if pos_session.counted_cash is not None:
            out.update(
                {
                    "counted_cash": str(pos_session.counted_cash),
                    "variance": str(pos_session.variance),
                    "variance_reason": pos_session.variance_reason,
                    "variance_approved_by_user_id": (
                        str(pos_session.variance_approved_by_user_id)
                        if pos_session.variance_approved_by_user_id
                        else None
                    ),
                    "variance_approved_at": (
                        pos_session.variance_approved_at.isoformat()
                        if pos_session.variance_approved_at
                        else None
                    ),
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
async def create_register(body: CreateRegisterRequest, ctx: PosConfigCtx):
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
async def list_registers(ctx: PosReadCtx):
    return [_register_out(r) for r in await PosService.list_registers(ctx.session, ctx.tenant_id)]


@router.get("/sessions")
async def list_sessions(
    ctx: PosReadCtx,
    status: str | None = None,
    register_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Resume the till: sessions behind this drawer, newest first (default 50, at most 500;
    ``offset`` pages further back)."""
    rows = await PosService.list_sessions(
        ctx.session,
        ctx.tenant_id,
        status=status,
        register_id=register_id,
        limit=limit,
        offset=offset,
    )
    return [_session_out(s) for s in rows]


@router.get("/sessions/{session_id}")
async def get_session(session_id: UUID, ctx: PosReadCtx):
    detail = await PosService.get_session(ctx.session, ctx.tenant_id, session_id)
    return _session_out(
        detail["session"],
        inflow=detail["inflow"],
        outflow=detail["outflow"],
        expected_now=detail["expected_now"],
    )


@router.get("/sessions/{session_id}/return-policy")
async def return_policy(session_id: UUID, ctx: PosReadCtx):
    """The shop's return and exchange choices for this till: the screen's starting point."""
    return await PosService.return_policy(ctx.session, ctx.tenant_id, session_id)


@router.post("/sessions/{session_id}/scan")
async def scan(session_id: UUID, body: ScanRequest, ctx: PosWriteCtx, override: OverrideDep):
    """§179: a code resolves to one variant, priced — the till's entry point."""
    result = await PosService.scan(
        ctx.session,
        ctx.tenant_id,
        session_id,
        identifier_type=body.identifier_type,
        value=body.value,
        actor_user_id=ctx.user.id,
        override=override.active,
    )
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in result.items()}


@router.post("/sessions/{session_id}/quote")
async def quote(session_id: UUID, body: QuoteRequest, ctx: PosWriteCtx, override: OverrideDep):
    """Price a cart without writing anything — what the customer sees."""
    return await PosService.quote(
        ctx.session,
        ctx.tenant_id,
        session_id,
        items=_lines(body.items),
        discount_total=body.discount_total,
        actor_user_id=ctx.user.id,
        override=override.active,
    )


@router.get("/sessions/{session_id}/close-preview")
async def get_close_preview(session_id: UUID, ctx: PosReadCtx):
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
    # How this till may take money (payments recorded, sale on account, methods, references).
    # None until the day has started, because it is read from the day's own till.
    tender: dict | None = None


async def _day_state(ctx, found) -> dict:
    if found is None:
        return {"started": False, "session": None, "tender": None}
    return {
        "started": True,
        "session": _session_out(found),
        "tender": await PosService.tender_rules(ctx.session, ctx.tenant_id, found),
    }


@router.post("/registers/{register_id}/working-session", response_model=DayStateOut)
async def working_session(register_id: UUID, ctx: PosWriteCtx):
    """Has today been started on this register? Read-only: it never opens a day.

    Returns the day's session once an opening balance was entered, otherwise
    ``started: false`` and the screen asks for the balance (``POST .../open-day``).
    """
    found = await PosService.working_session(ctx.session, ctx.tenant_id, register_id)
    return await _day_state(ctx, found)


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
    return await _day_state(ctx, opened)


@router.post("/registers/{register_id}/sales", status_code=201, response_model=RecordSaleOut)
async def record_sale(
    register_id: UUID,
    body: RecordSaleRequest,
    ctx: PosWriteCtx,
    override: OverrideDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)] = None,
):
    """Record a sale: stock comes off the shelf; payment is taken only if the shop turned it on."""
    return await PosService.record_sale(
        ctx.session,
        ctx.tenant_id,
        register_id,
        items=_lines(body.items),
        customer_id=body.customer_id,
        customer_phone=body.customer_phone,
        customer_name=body.customer_name,
        discount_total=body.discount_total,
        note=(body.note or "").strip() or None,
        actor_user_id=ctx.user.id,
        discount_override=override.active,
        payments=[line.model_dump() for line in body.payments] if body.payments else None,
        on_account=body.on_account,
        idempotency_key=idempotency_key,
        prescription=body.prescription.model_dump() if body.prescription else None,
    )


class CloseSessionRequest(BaseModel):
    """The close. ``counted_cash`` is required when the till takes payments and refused when not.

    A shop that takes card, wallet or transfer counts those too: ``counted_methods`` carries what
    was actually in each terminal, and the close stores one reconciliation row per method. The
    server refuses a missing method when the shop asked to settle methods at close.
    """

    model_config = ConfigDict(extra="forbid")

    counted_cash: str | None = Field(default=None, pattern=_MONEY)
    variance_reason: str | None = Field(default=None, max_length=500)
    # {method: amount} as the closer typed it; a method outside the till's vocabulary is refused.
    counted_methods: dict[str, str] | None = None


@router.post("/sessions/{session_id}/close")
async def close_session(
    session_id: UUID,
    ctx: PosWriteCtx,
    override: OverrideDep,
    body: CloseSessionRequest | None = None,
):
    pos_session = await PosService.close_session(
        ctx.session,
        ctx.tenant_id,
        session_id,
        closed_by=ctx.user.id,
        shift_override=override.active,
        counted_cash=body.counted_cash if body is not None else None,
        variance_reason=body.variance_reason if body is not None else None,
        counted_methods=body.counted_methods if body is not None else None,
    )
    return _session_out(pos_session)


@router.get("/sessions/{session_id}/drawer")
async def drawer_summary(session_id: UUID, ctx: PosReadCtx):
    """Expected cash from the drawer ledger and what each payment method collected."""
    return await PosService.drawer_summary(ctx.session, ctx.tenant_id, session_id)


class CashMovementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(pattern="^(pay_in|pay_out|cash_drop)$")
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    notes: str | None = Field(default=None, max_length=255)


class CashMovementOut(BaseModel):
    id: UUID
    session_id: UUID
    direction: str
    reason: str
    amount: Decimal
    notes: str | None = None
    created_at: datetime


class HandoverRequest(BaseModel):
    """The hand-off. A drawer that takes payments is COUNTED before it changes hands.

    Without the count the day's shortage can never be pinned on the shift it happened in: the
    session keeps running and every later figure belongs to whoever holds it last.
    """

    model_config = ConfigDict(extra="forbid")

    new_cashier_id: UUID
    counted_cash: str | None = Field(default=None, pattern=_MONEY)
    variance_reason: str | None = Field(default=None, max_length=500)


@router.post(
    "/sessions/{session_id}/cash-movements",
    response_model=CashMovementOut,
    status_code=201,
)
async def add_cash_movement(
    session_id: UUID, body: CashMovementRequest, ctx: PosWriteCtx, override: OverrideDep
):
    """Record a manual cash movement (pay-in, pay-out, cash drop) for an open session."""
    direction = "in" if body.reason == "pay_in" else "out"
    movement = await PosService.add_cash_movement(
        ctx.session,
        ctx.tenant_id,
        session_id,
        direction=direction,
        reason=body.reason,
        amount=body.amount,
        notes=body.notes,
        actor_user_id=ctx.user.id,
        shift_override=override.active,
    )
    return CashMovementOut(
        id=movement.id,
        session_id=movement.session_id,
        direction=movement.direction,
        reason=movement.reason,
        amount=movement.amount,
        notes=movement.notes,
        created_at=movement.created_at,
    )


@router.get("/sessions/{session_id}/cash-movements", response_model=list[CashMovementOut])
async def list_cash_movements(session_id: UUID, ctx: PosReadCtx):
    """List manual cash movements for a session."""
    rows = await PosService.list_cash_movements(ctx.session, ctx.tenant_id, session_id)
    return [
        CashMovementOut(
            id=r.id,
            session_id=r.session_id,
            direction=r.direction,
            reason=r.reason,
            amount=r.amount,
            notes=r.notes,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/sessions/{session_id}/handover")
async def handover_session(
    session_id: UUID, body: HandoverRequest, ctx: PosWriteCtx, override: OverrideDep
):
    """Transfer the drawer to another cashier without closing the day."""
    pos_session = await PosService.handover_session(
        ctx.session,
        ctx.tenant_id,
        session_id,
        new_cashier_id=body.new_cashier_id,
        actor_user_id=ctx.user.id,
        shift_override=override.active,
        counted_cash=body.counted_cash,
        variance_reason=body.variance_reason,
    )
    return _session_out(pos_session)


@router.get("/receipts/search")
async def search_receipts(
    ctx: PosReadCtx,
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
async def list_receipts(session_id: UUID, ctx: PosReadCtx):
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
async def top_products_report(ctx: PosReadCtx, since: str, until: str, limit: int = 20):
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
async def sales_report(ctx: PosReadCtx, since: str, until: str):
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
    ctx: PosReadCtx,
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
        }
        for r in rows
    ]


@router.get("/reports/cashier-custody")
async def cashier_custody_report(ctx: PosManagerCtx, start: str, end: str):
    """Per cashier over [start, end): shifts, cash counted vs expected, shortages and overages.

    Manager-only (``pos:override``): it names who was short, which a cashier does not read.
    """
    try:
        start_at = datetime.fromisoformat(start)
        end_at = datetime.fromisoformat(end)
    except ValueError:
        raise ValidationError("start and end must be ISO dates or datetimes") from None
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=UTC)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=UTC)
    return await PosService.cashier_custody(ctx.session, ctx.tenant_id, start=start_at, end=end_at)


@router.get("/sessions/{session_id}/items")
async def browse_items(
    session_id: UUID,
    ctx: PosReadCtx,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    """The till's catalog grid: active variants, ladder price, bin stock."""
    return await PosService.browse(
        ctx.session, ctx.tenant_id, session_id, q=q, limit=limit, offset=offset
    )


@router.get("/sessions/{session_id}/report")
async def get_session_report(session_id: UUID, ctx: PosReadCtx):
    """The shift's report — per method, cash trail, sales, returns."""
    return await PosService.session_report(ctx.session, ctx.tenant_id, session_id)


@router.get("/receipts/{receipt_id}")
async def get_receipt(receipt_id: UUID, ctx: PosReadCtx):
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
        "shop": payload["shop"],
    }


class ReceiptEmailRequest(BaseModel):
    # EmailStr, like every other address in the app: a bare '@' check let 'a@b.com,c@d.com' and a
    # header-injection string queue a real send from the merchant's domain.
    email: EmailStr = Field(max_length=254)


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
async def hold_cart(
    session_id: UUID, body: HoldCartRequest, ctx: PosWriteCtx, override: OverrideDep
):
    """Park a basket on the open session; reserve nothing, book nothing."""
    held = await PosService.hold_cart(
        ctx.session,
        ctx.tenant_id,
        session_id,
        items=_lines(body.items),
        customer_id=body.customer_id,
        discount_total=body.discount_total,
        label=body.label,
        held_by=ctx.user.id,
        actor_user_id=ctx.user.id,
        override=override.active,
    )
    return _held_cart_out(held)


@router.get("/sessions/{session_id}/held-carts")
async def list_held_carts(session_id: UUID, ctx: PosReadCtx, override: OverrideDep):
    rows = await PosService.list_held_carts(
        ctx.session, ctx.tenant_id, session_id, actor_user_id=ctx.user.id, override=override.active
    )
    return [_held_cart_out(h) for h in rows]


@router.get("/held-carts/{held_cart_id}")
async def get_held_cart(held_cart_id: UUID, ctx: PosReadCtx, override: OverrideDep):
    return _held_cart_out(
        await PosService.get_held_cart(
            ctx.session,
            ctx.tenant_id,
            held_cart_id,
            actor_user_id=ctx.user.id,
            override=override.active,
        )
    )


@router.delete("/held-carts/{held_cart_id}", status_code=204)
async def release_held_cart(held_cart_id: UUID, ctx: PosWriteCtx, override: OverrideDep):
    await PosService.release_held_cart(
        ctx.session,
        ctx.tenant_id,
        held_cart_id,
        actor_user_id=ctx.user.id,
        override=override.active,
    )


# ------------------------------------------------------------- refunds ----


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
            {
                "variant_id": str(line.variant_id),
                "quantity": line.quantity,
                "reason": line.reason,
                "restock": line.restock,
                "condition": line.condition,
            }
            for line in body.lines
        ],
        restock=body.restock,
        refund=[line.model_dump() for line in body.refund] if body.refund else None,
        refund_method=body.refund_method,
        refund_references=body.refund_references,
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
    """One-transaction exchange: the returned goods, the replacement sale, and the difference.
    A dearer replacement collects it, a cheaper one refunds it, an even swap moves nothing.
    Two receipts, one commit."""
    result = await PosService.exchange(
        ctx.session,
        ctx.tenant_id,
        session_id,
        order_id=body.order_id,
        return_lines=[
            {
                "variant_id": str(line.variant_id),
                "quantity": line.quantity,
                "reason": line.reason,
                "restock": line.restock,
                "condition": line.condition,
            }
            for line in body.return_lines
        ],
        new_lines=[
            {"variant_id": str(line.variant_id), "quantity": line.quantity}
            for line in body.new_lines
        ],
        restock=body.restock,
        payments=body.payments,
        refund=[line.model_dump() for line in body.refund] if body.refund else None,
        refund_method=body.refund_method,
        refund_references=body.refund_references,
        actor_user_id=ctx.user.id,
        shift_override=override.active,
    )
    return {
        **result,
        "return_receipt_id": str(result["return_receipt_id"]),
        "new_receipt_id": str(result["new_receipt_id"]),
    }


class ConfirmRefundRequest(BaseModel):
    """The terminal's own proof that a card/wallet reversal happened."""

    external_reference: str = Field(min_length=1, max_length=64)


@router.get("/refunds/pending")
async def list_pending_refunds(ctx: PosReadCtx) -> list[dict]:
    """The card/wallet reversals still waiting for their terminal reference.

    Read on mount by the cashier screens: the promise outlives the page that made it, so a reload
    must show the cashier what is still owed to the customer.
    """
    return await PosService.list_pending_refunds(ctx.session, ctx.tenant_id)


class RejectRefundRequest(BaseModel):
    """The terminal refused: why, and (optionally) where the money went instead."""

    reason: str = Field(min_length=1, max_length=255)
    replacement_method: str | None = Field(default=None, max_length=31)
    external_reference: str | None = Field(default=None, max_length=64)
    # The open drawer a cash replacement is paid out of; required for money from the till.
    session_id: UUID | None = None


@router.post("/refunds/{refund_id}/reject")
async def reject_refund(
    refund_id: UUID, body: RejectRefundRequest, ctx: PosWriteCtx, override: OverrideDep
):
    """Record a failed card/wallet reversal and release the money it was holding.

    Without this a declined reversal stayed pending forever: counted as reserved, so the sale could
    not be refunded another way, and the customer's money had not come back either. Rejecting frees
    the reservation exactly once; ``replacement_method`` refunds the same amount on another tender
    as a NEW row, so the rejected attempt stays in history.
    """
    return await PosService.reject_refund(
        ctx.session,
        ctx.tenant_id,
        refund_id,
        body.reason,
        replacement_method=body.replacement_method,
        external_reference=body.external_reference,
        actor_user_id=ctx.user.id,
        session_id=body.session_id,
        override=override.active,
    )


@router.post("/refunds/{refund_id}/confirm")
async def confirm_refund(
    refund_id: UUID, body: ConfirmRefundRequest, ctx: PosWriteCtx, override: OverrideDep
):
    """Record the terminal reference for a pending card/wallet refund.

    Until this lands the refund is `pending` and nothing derived has moved: the payment is not
    marked refunded and the customer is not lowered. A reversal that never confirms stays visibly
    outstanding instead of quietly counting as money returned.
    """
    return await PosService.confirm_refund(
        ctx.session,
        ctx.tenant_id,
        refund_id,
        body.external_reference,
        actor_user_id=ctx.user.id,
    )


class VoidSaleRequest(BaseModel):
    """Reverse a confirmed sale. The reason is required and the caller needs a manager override."""

    order_id: UUID
    reason: str = Field(min_length=1, max_length=255)


@router.post("/sessions/{session_id}/voids", status_code=201)
async def void_sale(
    session_id: UUID, body: VoidSaleRequest, ctx: PosWriteCtx, override: OverrideDep
):
    """Reverse a confirmed POS sale: stock back, money back, a POS-VOID- document, an audit trail.

    Nothing is deleted — the original receipt, its payments and its stock movements all stay, and
    the void adds the reversing ones. Needs a manager override and a reason.
    """
    result = await PosService.void_sale(
        ctx.session,
        ctx.tenant_id,
        session_id,
        order_id=body.order_id,
        reason=body.reason,
        actor_user_id=ctx.user.id,
        shift_override=override.active,
    )
    return {
        **result,
        "void_receipt_id": str(result["void_receipt_id"]),
        "original_receipt_id": str(result["original_receipt_id"]),
        "order_id": str(result["order_id"]),
    }


class StockRow(BaseModel):
    variant_id: str
    product_id: str
    product_title: str
    category_id: str | None
    category: str | None
    brand_id: str | None
    season: str | None
    material: str | None
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


@router.get("/stock/count")
async def count_stock(
    ctx: PosStockReadCtx,
    term: Annotated[str | None, Query(max_length=100)] = None,
    category_id: UUID | None = None,
    brand_id: UUID | None = None,
    season: Annotated[str | None, Query(max_length=40)] = None,
    material: Annotated[str | None, Query(max_length=60)] = None,
    status: Annotated[str | None, Query(pattern="^(in|low|out)$")] = None,
):
    """How many variants match the same filters as GET /stock.

    The grid shows "من N" from this, so a page that happens to be full is never mistaken for the
    whole set — the reason a printed sheet or an export could come out short.
    """
    return {
        "total": await StockViewService.count_stock(
            ctx.session,
            ctx.tenant_id,
            term=term,
            category_id=category_id,
            brand_id=brand_id,
            season=season,
            material=material,
            status=status,
        )
    }


@router.get("/stock", response_model=list[StockRow])
async def list_stock(
    ctx: PosStockReadCtx,
    term: Annotated[str | None, Query(max_length=100)] = None,
    category_id: UUID | None = None,
    brand_id: UUID | None = None,
    season: Annotated[str | None, Query(max_length=40)] = None,
    material: Annotated[str | None, Query(max_length=60)] = None,
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
        brand_id=brand_id,
        season=season,
        material=material,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/stock/summary", response_model=StockSummary)
async def stock_summary(ctx: PosStockReadCtx):
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


@router.put("/stock/products/{product_id}/reorder-level")
async def set_product_reorder_level(
    product_id: UUID,
    body: ReorderLevelRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    """Set ONE reorder level for every active size of a model.

    A clothing shop restocks a size run, not a size. Setting eight sizes one by one is how a model
    ends up with no low-stock alert at all.
    """
    variants = await StockViewService.set_reorder_level_for_product(
        ctx.session, ctx.tenant_id, product_id, body.reorder_level
    )
    return {
        "product_id": str(product_id),
        "reorder_level": body.reorder_level,
        "variants": variants,
    }


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

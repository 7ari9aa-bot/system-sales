"""The pricing endpoints. Parsing and permissions only; every rule is in the service."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.modules.identity.deps import TenantContext, require_permission
from app.modules.pricing.service import PricingService

router = APIRouter(prefix="/pricing", tags=["pricing"])

# Prices are a catalogue concern: the codes the roles already carry are the product ones, so
# pricing needs no permission of its own.
ReadCtx = Annotated[TenantContext, Depends(require_permission("products:read"))]
WriteCtx = Annotated[TenantContext, Depends(require_permission("products:write"))]


# ---------------------------------------------------------------- schemas


class PriceListOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    currency: str
    is_default: bool
    priority: int
    status: str
    valid_from: date | None
    valid_to: date | None
    notes: str | None


class PriceListIn(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    code: str = Field(min_length=1, max_length=31)
    currency: str = "EGP"
    priority: int = 0
    is_default: bool = False
    valid_from: date | None = None
    valid_to: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class PriceListItemOut(BaseModel):
    id: uuid.UUID
    price_list_id: uuid.UUID
    variant_id: uuid.UUID
    unit_price: Decimal
    min_quantity: int


class PriceListItemIn(BaseModel):
    variant_id: uuid.UUID
    unit_price: Decimal = Field(ge=0)
    min_quantity: int = Field(default=1, ge=1)


#: Money leaving the API is the same Decimal STRING at the money scale (ADR-001/§47):
#: ``Numeric(14,2)`` in, ``"15.00"`` out, never a float that cannot hold the cent.
MoneyOut = Annotated[
    str,
    Field(
        pattern=r"^-?\d+\.\d{2}$",
        description="An amount as a Decimal STRING at the money scale (ADR-001/§47).",
    ),
]


class DiscountRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None
    kind: str
    value: MoneyOut
    scope: str
    target_id: uuid.UUID | None
    min_subtotal: MoneyOut | None
    max_discount: MoneyOut | None
    requires_code: bool
    priority: int
    status: str
    starts_on: date | None
    ends_on: date | None


#: An amount on the wire. Money is a Decimal STRING at the money scale (ADR-001/§47):
#: a number published as a float loses a cent on the way out and back. The scale is
#: applied here so a client that sends ``15`` or ``"15"`` stores ``15.00``.
MoneyIn = Annotated[
    str,
    Field(
        pattern=r"^\d+(\.\d{1,2})?$",
        description=(
            "An amount as a decimal string at the money scale (ADR-001/§47). "
            'A percentage for kind="percent" is written the same way.'
        ),
    ),
]


class DiscountRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    kind: str
    value: MoneyIn
    scope: str = "order"
    target_id: uuid.UUID | None = None
    code: str | None = Field(default=None, max_length=31)
    min_subtotal: MoneyIn | None = None
    max_discount: MoneyIn | None = None
    requires_code: bool = False
    priority: int = 0
    starts_on: date | None = None
    ends_on: date | None = None

    @field_validator("value", "min_subtotal", "max_discount", mode="before")
    @classmethod
    def _as_money_string(cls, raw: object) -> object:
        """Accept the number a form field produces, publish and store the string."""
        if raw is None or isinstance(raw, str):
            return raw
        if isinstance(raw, bool):
            raise ValueError("money must be a number or a decimal string")
        if isinstance(raw, int | float | Decimal):
            amount = Decimal(str(raw))
            if amount < 0:
                raise ValueError("money cannot be negative")
            return f"{amount:.2f}"
        raise ValueError("money must be a number or a decimal string")


class StatusIn(BaseModel):
    status: str


class QuoteLineIn(BaseModel):
    variant_id: uuid.UUID
    unit_price: Decimal = Field(ge=0)
    quantity: int = Field(default=1, ge=1)
    category_id: uuid.UUID | None = None


class QuoteIn(BaseModel):
    lines: list[QuoteLineIn]
    code: str | None = None
    on_date: date | None = None


def _list_out(row) -> PriceListOut:
    return PriceListOut(
        id=row.id,
        name=row.name,
        code=row.code,
        currency=row.currency,
        is_default=row.is_default,
        priority=row.priority,
        status=row.status,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        notes=row.notes,
    )


def _item_out(row) -> PriceListItemOut:
    return PriceListItemOut(
        id=row.id,
        price_list_id=row.price_list_id,
        variant_id=row.variant_id,
        unit_price=row.unit_price,
        min_quantity=row.min_quantity,
    )


def _rule_out(row) -> DiscountRuleOut:
    return DiscountRuleOut(
        id=row.id,
        name=row.name,
        code=row.code,
        kind=row.kind,
        value=f"{row.value:.2f}",
        scope=row.scope,
        target_id=row.target_id,
        min_subtotal=None if row.min_subtotal is None else f"{row.min_subtotal:.2f}",
        max_discount=None if row.max_discount is None else f"{row.max_discount:.2f}",
        requires_code=row.requires_code,
        priority=row.priority,
        status=row.status,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
    )


# ---------------------------------------------------------------- price lists


@router.get("/price-lists", response_model=list[PriceListOut])
async def list_price_lists(
    ctx: ReadCtx,
) -> list[PriceListOut]:
    rows = await PricingService(ctx.session, ctx.tenant_id).list_price_lists()
    return [_list_out(r) for r in rows]


@router.post("/price-lists", response_model=PriceListOut, status_code=201)
async def create_price_list(
    body: PriceListIn,
    ctx: WriteCtx,
) -> PriceListOut:
    svc = PricingService(ctx.session, ctx.tenant_id)
    row = await svc.create_price_list(**body.model_dump())
    return _list_out(row)


@router.post("/price-lists/{list_id}/archive", response_model=PriceListOut)
async def archive_price_list(
    list_id: uuid.UUID,
    ctx: WriteCtx,
) -> PriceListOut:
    svc = PricingService(ctx.session, ctx.tenant_id)
    row = await svc.archive_price_list(list_id)
    return _list_out(row)


@router.get("/price-lists/{list_id}/items", response_model=list[PriceListItemOut])
async def list_items(
    list_id: uuid.UUID,
    ctx: ReadCtx,
) -> list[PriceListItemOut]:
    rows = await PricingService(ctx.session, ctx.tenant_id).list_items(list_id)
    return [_item_out(r) for r in rows]


@router.put("/price-lists/{list_id}/items", response_model=PriceListItemOut)
async def set_item(
    list_id: uuid.UUID,
    body: PriceListItemIn,
    ctx: WriteCtx,
) -> PriceListItemOut:
    svc = PricingService(ctx.session, ctx.tenant_id)
    row = await svc.set_item(list_id=list_id, **body.model_dump())
    return _item_out(row)


# ---------------------------------------------------------------- offers


@router.get("/discount-rules", response_model=list[DiscountRuleOut])
async def list_discount_rules(
    ctx: ReadCtx,
) -> list[DiscountRuleOut]:
    rows = await PricingService(ctx.session, ctx.tenant_id).list_discount_rules()
    return [_rule_out(r) for r in rows]


@router.post("/discount-rules", response_model=DiscountRuleOut, status_code=201)
async def create_discount_rule(
    body: DiscountRuleIn,
    ctx: WriteCtx,
) -> DiscountRuleOut:
    svc = PricingService(ctx.session, ctx.tenant_id)
    data = body.model_dump()
    for field in ("value", "min_subtotal", "max_discount"):
        if data.get(field) is not None:
            data[field] = Decimal(data[field])
    row = await svc.create_discount_rule(**data)
    return _rule_out(row)


@router.post("/discount-rules/{rule_id}/status", response_model=DiscountRuleOut)
async def set_rule_status(
    rule_id: uuid.UUID,
    body: StatusIn,
    ctx: WriteCtx,
) -> DiscountRuleOut:
    svc = PricingService(ctx.session, ctx.tenant_id)
    row = await svc.set_rule_status(rule_id, body.status)
    return _rule_out(row)


# ---------------------------------------------------------------- resolution


@router.post("/quote")
async def quote(
    body: QuoteIn,
    ctx: ReadCtx,
) -> dict:
    """What this basket costs after the offers allowed to run today."""
    svc = PricingService(ctx.session, ctx.tenant_id)
    result = await svc.quote(
        lines=[ln.model_dump() for ln in body.lines], code=body.code, on_date=body.on_date
    )
    return {
        **result,
        "applied": [{**a, "rule_id": str(a["rule_id"])} for a in result["applied"]],
    }

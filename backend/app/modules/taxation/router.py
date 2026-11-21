"""TAXATION routes: the business profile and tax classes.

Reading needs `settings:read`; changing the legal identity or the tax classes needs
`settings:write` (owner/manager), never the frontline cashier.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.modules.identity.deps import TenantContext, require_permission
from app.modules.taxation.models import BusinessProfile, TaxClass
from app.modules.taxation.service import TaxationService

router = APIRouter(prefix="/taxation", tags=["taxation"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]
WriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]


class ProfileRequest(BaseModel):
    legal_name: str = Field(min_length=1, max_length=255)
    vat_status: str = Field(default="not_registered", pattern="^(registered|not_registered)$")
    tax_registration_number: str | None = Field(default=None, max_length=20)
    trade_name: str | None = Field(default=None, max_length=255)
    commercial_register: str | None = Field(default=None, max_length=31)
    activity_code: str | None = Field(default=None, max_length=15)
    branch_code: str | None = Field(default=None, max_length=15)
    governorate: str | None = Field(default=None, max_length=63)
    city: str | None = Field(default=None, max_length=63)
    street: str | None = Field(default=None, max_length=255)
    building_number: str | None = Field(default=None, max_length=31)
    postal_code: str | None = Field(default=None, max_length=15)
    phone: str | None = Field(default=None, max_length=31)


class ProfileOut(BaseModel):
    legal_name: str
    trade_name: str | None
    vat_status: str
    tax_registration_number: str | None
    commercial_register: str | None
    activity_code: str | None
    branch_code: str
    governorate: str | None
    city: str | None
    street: str | None
    building_number: str | None
    postal_code: str | None
    phone: str | None
    country_code: str


class ProfileResponse(BaseModel):
    profile: ProfileOut | None
    missing_for_e_receipt: list[str]


class TaxClassRequest(BaseModel):
    code: str = Field(min_length=1, max_length=31)
    name: str = Field(min_length=1, max_length=80)
    # A string on purpose: a JSON float would already be wrong on the wire.
    rate: str = Field(min_length=1, max_length=8)
    eta_sub_type: str = Field(default="V009", max_length=15)


class TaxClassOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    rate: Decimal
    eta_tax_type: str
    eta_sub_type: str
    is_default: bool
    is_active: bool


def _profile_out(row: BusinessProfile) -> ProfileOut:
    return ProfileOut(
        legal_name=row.legal_name,
        trade_name=row.trade_name,
        vat_status=row.vat_status,
        tax_registration_number=row.tax_registration_number,
        commercial_register=row.commercial_register,
        activity_code=row.activity_code,
        branch_code=row.branch_code,
        governorate=row.governorate,
        city=row.city,
        street=row.street,
        building_number=row.building_number,
        postal_code=row.postal_code,
        phone=row.phone,
        country_code=row.country_code,
    )


def _class_out(row: TaxClass) -> TaxClassOut:
    return TaxClassOut(
        id=row.id,
        code=row.code,
        name=row.name,
        rate=row.rate,
        eta_tax_type=row.eta_tax_type,
        eta_sub_type=row.eta_sub_type,
        is_default=row.is_default,
        is_active=row.is_active,
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(ctx: ReadCtx) -> ProfileResponse:
    row = await TaxationService.get_profile(ctx.session, ctx.tenant_id)
    return ProfileResponse(
        profile=_profile_out(row) if row else None,
        missing_for_e_receipt=TaxationService.fiscal_readiness(row),
    )


@router.put("/profile", response_model=ProfileResponse)
async def put_profile(body: ProfileRequest, ctx: WriteCtx) -> ProfileResponse:
    fields = body.model_dump(exclude={"legal_name", "vat_status", "tax_registration_number"})
    row = await TaxationService.upsert_profile(
        ctx.session,
        ctx.tenant_id,
        legal_name=body.legal_name,
        vat_status=body.vat_status,
        tax_registration_number=body.tax_registration_number,
        **fields,
    )
    return ProfileResponse(
        profile=_profile_out(row), missing_for_e_receipt=TaxationService.fiscal_readiness(row)
    )


@router.get("/classes", response_model=list[TaxClassOut])
async def list_classes(ctx: ReadCtx) -> list[TaxClassOut]:
    rows = await TaxationService.ensure_default_classes(ctx.session, ctx.tenant_id)
    return [_class_out(r) for r in rows if r.is_active]


@router.post("/classes", response_model=TaxClassOut, status_code=201)
async def create_class(body: TaxClassRequest, ctx: WriteCtx) -> TaxClassOut:
    row = await TaxationService.create_class(
        ctx.session,
        ctx.tenant_id,
        code=body.code,
        name=body.name,
        rate=body.rate,
        eta_sub_type=body.eta_sub_type,
    )
    return _class_out(row)

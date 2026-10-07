"""PRIVACY routes — consent ledger (§32) + data-subject requests (§51).

Consent is a first-class, append-only ledger scoped by channel + purpose:
grants carry their source and proof, and revocation is recorded (never a
delete). Data-subject requests are opened here and — for ``delete`` requests —
executed through the deletion-propagation service (the §172 chain).

Reads require ``customers:read``; writes require ``customers:write`` (the
closest existing codes — no new permission codes are invented).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import NotFoundError, ValidationError
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.privacy.models import Consent, DataSubjectRequest
from app.modules.privacy.service import DataRequestService, DeletionService

router = APIRouter(prefix="/privacy", tags=["privacy"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("customers:read"))]
WriteCtx = Annotated[TenantContext, Depends(require_permission("customers:write"))]

# Query params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` — see the parameter-declaration rule in
# app/modules/analytics/router.py and the full-app gate in
# tests/test_route_parameter_declarations.py.


class ConsentGrant(BaseModel):
    customer_id: uuid.UUID
    channel: str = Field(min_length=1, max_length=31)
    purpose: str = Field(pattern="^(service_messages|marketing|ai_processing|analytics)$")
    source: str | None = Field(default=None, max_length=63)
    proof: dict = Field(default_factory=dict)


class DataRequestCreate(BaseModel):
    customer_id: uuid.UUID
    request_type: str = Field(pattern="^(access|export|delete|rectify)$")


def _consent_dict(consent: Consent) -> dict:
    return {
        "id": str(consent.id),
        "customer_id": str(consent.customer_id),
        "channel": consent.channel,
        "purpose": consent.purpose,
        "status": consent.status,
        "source": consent.source,
        "proof": consent.proof,
        "captured_at": consent.captured_at.isoformat(),
        "revoked_at": consent.revoked_at.isoformat() if consent.revoked_at else None,
    }


def _dsr_dict(request: DataSubjectRequest) -> dict:
    return {
        "id": str(request.id),
        "customer_id": str(request.customer_id),
        "request_type": request.request_type,
        "status": request.status,
        "requested_by_user_id": (
            str(request.requested_by_user_id) if request.requested_by_user_id else None
        ),
        "result_ref": request.result_ref,
        "error": request.error,
        "created_at": request.created_at.isoformat(),
        "completed_at": request.completed_at.isoformat() if request.completed_at else None,
    }


# ------------------------------------------------------------- consents ----


@router.get("/consents")
async def list_consents(
    ctx: ReadCtx,
    customer_id: uuid.UUID | None = None,
    purpose: str | None = None,
    status: Annotated[str | None, Query(pattern="^(granted|revoked|expired)$")] = None,
):
    """List the consent ledger, filtered by customer / purpose / status."""
    stmt = select(Consent).where(Consent.tenant_id == ctx.tenant_id)
    if customer_id is not None:
        stmt = stmt.where(Consent.customer_id == customer_id)
    if purpose is not None:
        stmt = stmt.where(Consent.purpose == purpose)
    if status is not None:
        stmt = stmt.where(Consent.status == status)
    rows = (
        (await ctx.session.execute(stmt.order_by(Consent.captured_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return [_consent_dict(consent) for consent in rows]


@router.post("/consents", status_code=201)
async def grant_consent(ctx: WriteCtx, body: ConsentGrant):
    """Record a grant of consent for one purpose + channel, with source/proof."""
    consent = Consent(
        tenant_id=ctx.tenant_id,
        customer_id=body.customer_id,
        channel=body.channel,
        purpose=body.purpose,
        status="granted",
        source=body.source,
        proof=body.proof,
    )
    ctx.session.add(consent)
    await ctx.session.flush()
    return _consent_dict(consent)


@router.post("/consents/{consent_id}/revoke")
async def revoke_consent(ctx: WriteCtx, consent_id: uuid.UUID):
    """Revoke a consent (recorded, not deleted — the ledger stays append-only)."""
    consent = (
        await ctx.session.execute(
            select(Consent).where(
                Consent.tenant_id == ctx.tenant_id,
                Consent.id == consent_id,
            )
        )
    ).scalar_one_or_none()
    if consent is None:
        raise NotFoundError("consent not found")
    consent.status = "revoked"
    consent.revoked_at = datetime.now(UTC)
    await ctx.session.flush()
    return _consent_dict(consent)


# ------------------------------------------------------ data requests -----


@router.post("/data-requests", status_code=201)
async def open_data_request(ctx: WriteCtx, body: DataRequestCreate):
    """Open an access / export / delete / rectify request (status: pending)."""
    request = await DataRequestService.create(
        ctx.session,
        ctx.tenant_id,
        customer_id=body.customer_id,
        request_type=body.request_type,
        requested_by_user_id=ctx.user.id,
    )
    return _dsr_dict(request)


@router.get("/data-requests")
async def list_data_requests(
    ctx: ReadCtx,
    status: Annotated[
        str | None, Query(pattern="^(pending|in_progress|completed|rejected|failed)$")
    ] = None,
    request_type: Annotated[str | None, Query(pattern="^(access|export|delete|rectify)$")] = None,
):
    """List data-subject requests, filtered by status / type."""
    stmt = select(DataSubjectRequest).where(DataSubjectRequest.tenant_id == ctx.tenant_id)
    if status is not None:
        stmt = stmt.where(DataSubjectRequest.status == status)
    if request_type is not None:
        stmt = stmt.where(DataSubjectRequest.request_type == request_type)
    rows = (
        (await ctx.session.execute(stmt.order_by(DataSubjectRequest.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return [_dsr_dict(request) for request in rows]


@router.get("/data-requests/{request_id}")
async def get_data_request(ctx: ReadCtx, request_id: uuid.UUID):
    """Fetch one data-subject request (its lifecycle status)."""
    request = (
        await ctx.session.execute(
            select(DataSubjectRequest).where(
                DataSubjectRequest.tenant_id == ctx.tenant_id,
                DataSubjectRequest.id == request_id,
            )
        )
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError("data subject request not found")
    return _dsr_dict(request)


@router.post("/data-requests/{request_id}/execute")
async def execute_data_request(ctx: WriteCtx, request_id: uuid.UUID):
    """DESTRUCTIVE — run the §172 deletion-propagation chain for a delete request.

    Only ``delete`` requests can be executed. This tombstones the customer,
    hard-deletes derived AI memories, closes pending data-subject requests and
    writes an audit record + outbox event. It cannot be undone.
    """
    request = (
        await ctx.session.execute(
            select(DataSubjectRequest).where(
                DataSubjectRequest.tenant_id == ctx.tenant_id,
                DataSubjectRequest.id == request_id,
            )
        )
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError("data subject request not found")
    if request.request_type != "delete":
        raise ValidationError("only delete requests can be executed")
    report = await DeletionService.propagate_customer_deletion(
        ctx.session,
        ctx.tenant_id,
        request.customer_id,
        requested_by_user_id=ctx.user.id,
    )
    return {"request_id": str(request.id), "report": report}

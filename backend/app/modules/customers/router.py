"""CUSTOMERS routes — list/search; plus PLATFORM routes for the settings screen
(invitations list, integrations)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import NotFoundError, ValidationError
from app.core.idempotency import (
    IfMatch,
    apply_etag,
    apply_versioned_update,
    parse_if_match,
)
from app.core.pagination import decode_cursor, page_slice
from app.modules.billing.service import EntitlementService
from app.modules.customers.service import CustomerService
from app.modules.customers.timeline import Customer360Service
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.identity.models import Invitation, Role
from app.modules.platform.models import Integration

router = APIRouter(tags=["customers"])
platform_router = APIRouter(tags=["platform"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("customers:write"))]


def _customer_summary(customer, *, permission_codes: set[str] | None = None) -> dict:
    """Serialize a customer — §146: PII fields redacted without pii:read permission."""
    from app.core.field_auth import redact_customer

    raw = {
        "id": str(customer.id),
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "lifetime_value": str(customer.lifetime_value),
        "is_blocked": customer.is_blocked,
    }
    if permission_codes is None:
        return raw
    return redact_customer(raw, permission_codes=permission_codes)


@router.get("/customers")
async def list_customers(
    ctx: TenantCtxDep,
    search: str | None = None,
    tag: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)
    rows = await CustomerService.list_customers(
        ctx.session,
        ctx.tenant_id,
        search=search,
        tag=tag,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    page, next_cursor = page_slice(rows, limit)
    return {
        "items": [
            _customer_summary(c, permission_codes=ctx.permission_codes)
            for c in page
        ],
        "next_cursor": next_cursor,
    }


@router.get("/customers/{customer_id}")
async def get_customer(ctx: TenantCtxDep, customer_id: UUID, response: Response):
    customer = await CustomerService.get(ctx.session, ctx.tenant_id, customer_id)
    tags = await CustomerService.list_tags(ctx.session, ctx.tenant_id, customer_id)
    identities = await CustomerService.list_identities(
        ctx.session, ctx.tenant_id, customer_id
    )
    addresses = await CustomerService.list_addresses(ctx.session, ctx.tenant_id, customer_id)
    notes = await CustomerService.list_notes(ctx.session, ctx.tenant_id, customer_id)
    # G-15: the row's version is the concurrency token. It is exposed in the body
    # AND as a strong ETag so a client can send it back as If-Match on a write.
    apply_etag(response, customer.version)
    return {
        "id": str(customer.id),
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "locale": customer.locale,
        "version": customer.version,
        "lifetime_value": str(customer.lifetime_value),
        "is_blocked": customer.is_blocked,
        "extra": customer.extra or {},
        "deleted_at": customer.deleted_at.isoformat() if customer.deleted_at else None,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
        "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
        "tags": [{"id": str(t.id), "name": t.name, "color": t.color} for t in tags],
        "identities": [
            {"id": str(i.id), "channel": i.channel, "external_id": i.external_id}
            for i in identities
        ],
        "addresses": [
            {
                "id": str(a.id),
                "label": a.label,
                "line1": a.line1,
                "line2": a.line2,
                "city": a.city,
                "region": a.region,
                "postal_code": a.postal_code,
                "country": a.country,
                "is_default": a.is_default,
            }
            for a in addresses
        ],
        "notes": [
            {
                "id": str(n.id),
                "body": n.body,
                "author_user_id": str(n.author_user_id) if n.author_user_id else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notes
        ],
    }


@router.get("/customers/{customer_id}/360")
async def get_customer_360(
    ctx: TenantCtxDep,
    customer_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    timeline_limit: int = Query(default=60, ge=1, le=200),
):
    """Spec W5: one composed record — profile, orders, payments, conversations,
    tasks and a merged timeline, so the record page needs a single round trip."""
    return await Customer360Service.build(
        ctx.session,
        ctx.tenant_id,
        customer_id,
        limit=limit,
        timeline_limit=timeline_limit,
    )


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=31)
    email: str | None = Field(default=None, max_length=320)
    locale: str | None = Field(default=None, max_length=15)
    extra: dict | None = None


@router.patch("/customers/{customer_id}")
async def update_customer(
    customer_id: UUID,
    body: CustomerUpdate,
    ctx: WriteCtx,
    response: Response,
    if_match: IfMatch = None,
):
    fields = body.model_dump(exclude_unset=True)
    if parse_if_match(if_match) is None:
        # No If-Match (or `*`): unconditional, exactly as before. A malformed
        # value still fails here with a 400 rather than being ignored.
        customer = await CustomerService.update_customer(
            ctx.session, ctx.tenant_id, customer_id, **fields
        )
    else:
        # Conditional: the DATABASE decides. ONE UPDATE ... WHERE id AND version
        # is the write, so two writers holding the same valid ETag cannot both
        # win — a Python read-then-write could be clobbered in between. A stale
        # version matches no row and apply_versioned_update raises ConflictError
        # (409), leaving the row untouched.
        customer = await CustomerService.get(ctx.session, ctx.tenant_id, customer_id)
        await apply_versioned_update(ctx.session, customer, if_match, fields)
    # The version AFTER the write, so a client can chain its next edit.
    apply_etag(response, customer.version)
    return _customer_summary(customer, permission_codes=ctx.permission_codes)


@router.post("/customers/{customer_id}/block")
async def block_customer(customer_id: UUID, ctx: WriteCtx):
    customer = await CustomerService.set_blocked(
        ctx.session, ctx.tenant_id, customer_id, blocked=True
    )
    return {"id": str(customer.id), "is_blocked": customer.is_blocked}


@router.post("/customers/{customer_id}/unblock")
async def unblock_customer(customer_id: UUID, ctx: WriteCtx):
    customer = await CustomerService.set_blocked(
        ctx.session, ctx.tenant_id, customer_id, blocked=False
    )
    return {"id": str(customer.id), "is_blocked": customer.is_blocked}


class ArchiveBody(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


@router.post("/customers/{customer_id}/archive")
async def archive_customer(
    customer_id: UUID,
    ctx: WriteCtx,
    body: ArchiveBody | None = None,
):
    customer = await CustomerService.archive(
        ctx.session,
        ctx.tenant_id,
        customer_id,
        deleted_by=ctx.user.id,
        reason=body.reason if body else None,
    )
    return {"id": str(customer.id), "deleted_at": customer.deleted_at.isoformat()}


class MergeBody(BaseModel):
    source_customer_id: UUID
    target_customer_id: UUID


@router.post("/customers/merge")
async def merge_customers(
    body: MergeBody,
    ctx: WriteCtx,
):
    """§27-28: merge two duplicate customers into one canonical record.

    source_customer_id is tombstoned; target_customer_id survives.
    """
    from app.modules.customers.service import IdentityMergeService

    canonical_id = await IdentityMergeService.merge(
        ctx.session,
        ctx.tenant_id,
        canonical_customer_id=body.target_customer_id,
        merged_away_customer_id=body.source_customer_id,
        performed_by_user_id=ctx.user.id,
    )
    customer = await CustomerService.get(ctx.session, ctx.tenant_id, canonical_id)
    return _customer_summary(customer, permission_codes=ctx.permission_codes)


class TagBody(BaseModel):
    name: str = Field(min_length=1, max_length=63)


@router.get("/customers/{customer_id}/tags")
async def list_customer_tags(ctx: TenantCtxDep, customer_id: UUID):
    tags = await CustomerService.list_tags(ctx.session, ctx.tenant_id, customer_id)
    return [{"id": str(t.id), "name": t.name, "color": t.color} for t in tags]


@router.post("/customers/{customer_id}/tags", status_code=201)
async def add_customer_tag(
    customer_id: UUID, body: TagBody, ctx: WriteCtx
):
    name = body.name.strip()
    if not name:
        raise ValidationError("tag name must not be empty")
    tag = await CustomerService.add_tag(ctx.session, ctx.tenant_id, customer_id, name)
    return {"id": str(tag.id), "name": tag.name, "color": tag.color}


@router.delete("/customers/{customer_id}/tags/{tag_name}", status_code=204)
async def remove_customer_tag(
    customer_id: UUID, tag_name: str, ctx: WriteCtx
):
    await CustomerService.remove_tag(ctx.session, ctx.tenant_id, customer_id, tag_name)
    return Response(status_code=204)


class NoteBody(BaseModel):
    body: str = Field(min_length=1)


@router.get("/customers/{customer_id}/notes")
async def list_customer_notes(ctx: TenantCtxDep, customer_id: UUID):
    notes = await CustomerService.list_notes(ctx.session, ctx.tenant_id, customer_id)
    return [
        {
            "id": str(n.id),
            "body": n.body,
            "author_user_id": str(n.author_user_id) if n.author_user_id else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]


@router.post("/customers/{customer_id}/notes", status_code=201)
async def add_customer_note(
    customer_id: UUID, body: NoteBody, ctx: WriteCtx
):
    note = await CustomerService.add_note(
        ctx.session, ctx.tenant_id, customer_id, ctx.user.id, body.body
    )
    return {"id": str(note.id), "body": note.body}


class IntegrationBody(BaseModel):
    provider: str = Field(max_length=63)
    kind: str = "channel"
    config: dict = {}
    credentials: dict = {}
    status: str = "connected"


@platform_router.get("/invitations")
async def list_invitations(
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    rows = (
        await ctx.session.execute(
            select(Invitation, Role.code)
            .outerjoin(Role, Role.id == Invitation.role_id)
            .where(Invitation.tenant_id == ctx.tenant_id)
            .order_by(Invitation.created_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "id": str(invitation.id),
            "email": invitation.email,
            "role_code": role_code,
            "status": invitation.status,
        }
        for invitation, role_code in rows
    ]


@platform_router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    invitation = (
        await ctx.session.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise NotFoundError(f"invitation {invitation_id} not found")
    invitation.status = "revoked"
    return Response(status_code=204)


@platform_router.get("/integrations")
async def list_integrations(ctx: TenantCtxDep):
    rows = (
        (
            await ctx.session.execute(
                select(Integration).where(Integration.tenant_id == ctx.tenant_id).limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [
        {"id": str(i.id), "provider": i.provider, "kind": i.kind, "status": i.status} for i in rows
    ]


@platform_router.post("/integrations", status_code=201)
async def upsert_integration(
    body: IntegrationBody,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Register/refresh a channel integration (WhatsApp/Telegram/webchat keys)."""
    existing = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.tenant_id == ctx.tenant_id,
                Integration.provider == body.provider,
                Integration.kind == body.kind,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.config = body.config
        existing.credentials = body.credentials
        existing.status = body.status
        return {"id": str(existing.id), "status": existing.status}
    # §165: which channels a plan includes is an entitlement. Only the CREATE
    # branch is gated — refreshing an existing integration is not a new channel
    # and must keep working after a downgrade.
    #
    # The plan stores `channels` as an ALLOWLIST of names, so the provider is
    # what must be checked: `ensure(..., "CanCreateChannel")` could only ever ask
    # "may this tenant add any channel at all", and the capability name never
    # matched a plan row anyway.
    await EntitlementService.ensure_channel_allowed(
        ctx.session, ctx.tenant_id, body.provider
    )
    integration = Integration(
        tenant_id=ctx.tenant_id,
        provider=body.provider,
        kind=body.kind,
        config=body.config,
        credentials=body.credentials,
        status=body.status,
    )
    ctx.session.add(integration)
    await ctx.session.flush()
    return {"id": str(integration.id), "status": integration.status}

"""Customer CRUD routes — list, search, 360, contact issues, tags, notes, merge."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.core.idempotency import (
    IfMatch,
    apply_etag,
    apply_versioned_update,
    parse_if_match,
)
from app.core.pagination import decode_cursor, page_slice
from app.modules.customers import schemas
from app.modules.customers.schemas import (
    ArchiveBody,
    ContactIssueResolution,
    CustomerUpdate,
    MergeBody,
    NoteBody,
    TagBody,
)
from app.modules.customers.service import CustomerService
from app.modules.customers.timeline import Customer360Service

from ._deps import (
    ReadCtx,
    WriteCtx,
    _canonicalize_contact_fields,
    _customer_summary,
    _redact_issue_item,
)

router = APIRouter(tags=["customers"])

# Query params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` — see the parameter-declaration rule in
# app/modules/analytics/router.py and the full-app gate in
# tests/test_route_parameter_declarations.py.


@router.get("/customers", response_model=schemas.CustomerList)
async def list_customers(
    ctx: ReadCtx,
    search: str | None = None,
    tag: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
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
        "items": [_customer_summary(c, permission_codes=ctx.permission_codes) for c in page],
        "next_cursor": next_cursor,
    }


@router.get("/customers/contact-data-issues", response_model=schemas.ContactIssueList)
async def list_contact_data_issues(
    ctx: WriteCtx,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
):
    """M12: the rows the contact backfill could not fix on its own.

    Registered BEFORE ``/customers/{customer_id}`` — a literal path under that
    route name would otherwise be swallowed by the UUID parameter (422).
    Gated on ``customers:write``, not a read: this is a work queue for the
    person who can act on it, and it lists raw phone numbers.
    """
    items = await CustomerService.contact_data_quality_report(
        ctx.session, ctx.tenant_id, limit=limit
    )
    return {"items": [_redact_issue_item(i, ctx) for i in items], "count": len(items)}


@router.post("/customers/{customer_id}/contact-issue/resolve", response_model=schemas.ContactIssue)
async def resolve_contact_issue(
    customer_id: UUID,
    body: ContactIssueResolution,
    ctx: WriteCtx,
):
    """Clear ONE M12 quarantine mark an operator has decided, and audit it.

    ``customers:write`` — the same gate as the queue itself. The offered
    resolutions, and why the surface stops there, are documented on
    ``CustomerService.resolve_contact_issue``: confirming a normalization is
    automatable, merging two customers (orders, conversations and ledgers all
    point at one survivor) is not, so a merge request is refused with 400 and
    pointed at ``POST /customers/merge``. The response is the row's REAL
    remaining issue view after the clear — an already-resolved row answers
    409 with the server's actual open issues rather than pretending.
    """
    item = await CustomerService.resolve_contact_issue(
        ctx.session,
        ctx.tenant_id,
        customer_id,
        issue=body.issue,
        resolution=body.resolution,
        phone=body.phone,
        actor_user_id=ctx.user.id,
    )
    return _redact_issue_item(item, ctx)


@router.get("/customers/{customer_id}", response_model=schemas.CustomerDetail)
async def get_customer(ctx: ReadCtx, customer_id: UUID, response: Response):
    customer = await CustomerService.get(ctx.session, ctx.tenant_id, customer_id)
    tags = await CustomerService.list_tags(ctx.session, ctx.tenant_id, customer_id)
    identities = await CustomerService.list_identities(ctx.session, ctx.tenant_id, customer_id)
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
        "is_blocked": bool(customer.is_blocked),
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


@router.get("/customers/{customer_id}/360", response_model=schemas.Customer360)
async def get_customer_360(
    ctx: ReadCtx,
    customer_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    timeline_limit: Annotated[int, Query(ge=1, le=200)] = 60,
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


@router.patch("/customers/{customer_id}", response_model=schemas.CustomerSummary)
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
        # M12: this branch is the one write path that bypasses the service, so
        # the contact fields are canonicalized here before they hit the columns.
        await apply_versioned_update(
            ctx.session, customer, if_match, _canonicalize_contact_fields(fields)
        )
    # The version AFTER the write, so a client can chain its next edit.
    apply_etag(response, customer.version)
    return _customer_summary(customer, permission_codes=ctx.permission_codes)


@router.post("/customers/{customer_id}/block", response_model=schemas.BlockState)
async def block_customer(customer_id: UUID, ctx: WriteCtx):
    customer = await CustomerService.set_blocked(
        ctx.session, ctx.tenant_id, customer_id, blocked=True
    )
    return {"id": str(customer.id), "is_blocked": bool(customer.is_blocked)}


@router.post("/customers/{customer_id}/unblock", response_model=schemas.BlockState)
async def unblock_customer(customer_id: UUID, ctx: WriteCtx):
    customer = await CustomerService.set_blocked(
        ctx.session, ctx.tenant_id, customer_id, blocked=False
    )
    return {"id": str(customer.id), "is_blocked": bool(customer.is_blocked)}


@router.post("/customers/{customer_id}/archive", response_model=schemas.Archived)
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


@router.post("/customers/merge", response_model=schemas.CustomerSummary)
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


@router.get("/customers/{customer_id}/tags", response_model=list[schemas.TagOut])
async def list_customer_tags(ctx: ReadCtx, customer_id: UUID):
    tags = await CustomerService.list_tags(ctx.session, ctx.tenant_id, customer_id)
    return [{"id": str(t.id), "name": t.name, "color": t.color} for t in tags]


@router.post(
    "/customers/{customer_id}/tags",
    status_code=201,
    response_model=schemas.TagOut,
)
async def add_customer_tag(customer_id: UUID, body: TagBody, ctx: WriteCtx):
    from app.modules.errors import ValidationError

    name = body.name.strip()
    if not name:
        raise ValidationError("tag name must not be empty")
    tag = await CustomerService.add_tag(ctx.session, ctx.tenant_id, customer_id, name)
    return {"id": str(tag.id), "name": tag.name, "color": tag.color}


@router.delete(
    "/customers/{customer_id}/tags/{tag_name}",
    status_code=204,
)
async def remove_customer_tag(customer_id: UUID, tag_name: str, ctx: WriteCtx):
    await CustomerService.remove_tag(ctx.session, ctx.tenant_id, customer_id, tag_name)
    return Response(status_code=204)


@router.get("/customers/{customer_id}/notes", response_model=list[schemas.NoteOut])
async def list_customer_notes(ctx: ReadCtx, customer_id: UUID):
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


@router.post(
    "/customers/{customer_id}/notes",
    status_code=201,
    response_model=schemas.NoteCreated,
)
async def add_customer_note(customer_id: UUID, body: NoteBody, ctx: WriteCtx):
    note = await CustomerService.add_note(
        ctx.session, ctx.tenant_id, customer_id, ctx.user.id, body.body
    )
    return {"id": str(note.id), "body": note.body}

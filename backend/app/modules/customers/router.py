"""CUSTOMERS routes — list/search; plus PLATFORM routes for the settings screen
(invitations list, integrations)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.contact_norm import normalize_email, normalize_phone
from app.core.errors import ConflictError, ExternalProviderError, NotFoundError, ValidationError
from app.core.idempotency import (
    IfMatch,
    apply_etag,
    apply_versioned_update,
    parse_if_match,
)
from app.core.pagination import decode_cursor, page_slice
from app.core.secrets import encrypt_credentials_dict
from app.modules.billing.service import EntitlementService
from app.modules.customers import schemas
from app.modules.customers.schemas import (
    ArchiveBody,
    ContactIssueResolution,
    CustomerUpdate,
    IntegrationBody,
    MergeBody,
    NoteBody,
    TagBody,
)
from app.modules.customers.service import CustomerService
from app.modules.customers.timeline import Customer360Service
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.identity.models import Invitation, Role
from app.modules.platform.integration_verifier import (
    configure_telegram_webhook,
    telegram_webhook_secret_configured,
    verify_channel_credentials,
)
from app.modules.platform.models import Integration
from app.modules.platform.service import IntegrationCredentialsService

router = APIRouter(tags=["customers"])
platform_router = APIRouter(tags=["platform"])

# Query params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` — see the parameter-declaration rule in
# app/modules/analytics/router.py and the full-app gate in
# tests/test_route_parameter_declarations.py.

WriteCtx = Annotated[TenantContext, Depends(require_permission("customers:write"))]
# P4 — the seeded matrix (scripts/provision.py ROLE_MATRIX) grants
# ``customers:read`` and ``customers:write`` as separate codes, so a read that
# resolved tenancy only (``TenantCtxDep``) let any member of the tenant pull the
# whole customer book. The five customer reads are gated on the read code now;
# the settings-screen read below is gated on ``settings:read`` for the same
# reason — its three siblings in this file already required ``settings:write``.
ReadCtx = Annotated[TenantContext, Depends(require_permission("customers:read"))]
SettingsReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]

# The contact report renames a phone before it reports it, and §146 redacts by
# FIELD NAME — so the renamed ones have to be listed alongside PII_FIELDS.
_EXTRA_PHONE_FIELDS = frozenset({"legacy_raw", "suspected_phone", "canonical_phone"})


def _customer_summary(customer, *, permission_codes: set[str] | None = None) -> dict:
    """Serialize a customer — §146: PII fields redacted without pii:read permission."""
    from app.core.field_auth import redact_customer

    raw = {
        "id": str(customer.id),
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "lifetime_value": str(customer.lifetime_value),
        "is_blocked": bool(customer.is_blocked),
    }
    if permission_codes is None:
        return raw
    return redact_customer(raw, permission_codes=permission_codes)


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
        "items": [
            _customer_summary(c, permission_codes=ctx.permission_codes)
            for c in page
        ],
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


def _redact_issue_item(item: dict, ctx: TenantContext) -> dict:
    """§146 on a queue item — every phone column, including the ones the
    backfill RENAMED (``legacy_raw``/``suspected_phone``/``canonical_phone``),
    redacted unless the caller holds ``pii:read``. The redaction set is only
    applied when it must be: ``redact_fields`` with an explicit set redacts
    UNCONDITIONALLY, so passing it for a ``pii:read`` caller would hide the
    very values the operator is there to judge."""
    from app.core.field_auth import PII_FIELDS, redact_fields

    if "pii:read" in ctx.permission_codes:
        return dict(item)
    return redact_fields(
        item,
        permission_codes=ctx.permission_codes,
        fields_to_redact=PII_FIELDS | _EXTRA_PHONE_FIELDS,
    )


@router.post(
    "/customers/{customer_id}/contact-issue/resolve", response_model=schemas.ContactIssue
)
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


def _canonicalize_contact_fields(fields: dict) -> dict:
    """M12: the ``If-Match`` branch must store canonical contacts too.

    That branch writes through ``apply_versioned_update`` — plain column values,
    straight into one UPDATE — so it skipped the normalization the service does,
    and a local spelling typed into a drawer still recreated the duplicate M12
    exists to remove. ``phone`` is a uniqueness key, so an unparseable value
    raises here exactly as it does in the service
    (``ContactNormalizationError`` is the project's own 400).

    Only this branch: the service re-reads the RAW typing to match legacy rows
    that still hold it, so canonicalizing before that call would blind it.
    """
    if fields.get("phone") is not None:
        fields["phone"] = normalize_phone(fields["phone"])
    if fields.get("email") is not None:
        fields["email"] = normalize_email(fields["email"])
    return fields


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
async def add_customer_tag(
    customer_id: UUID, body: TagBody, ctx: WriteCtx
):
    name = body.name.strip()
    if not name:
        raise ValidationError("tag name must not be empty")
    tag = await CustomerService.add_tag(ctx.session, ctx.tenant_id, customer_id, name)
    return {"id": str(tag.id), "name": tag.name, "color": tag.color}


@router.delete(
    "/customers/{customer_id}/tags/{tag_name}",
    status_code=204,
)
async def remove_customer_tag(
    customer_id: UUID, tag_name: str, ctx: WriteCtx
):
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
async def add_customer_note(
    customer_id: UUID, body: NoteBody, ctx: WriteCtx
):
    note = await CustomerService.add_note(
        ctx.session, ctx.tenant_id, customer_id, ctx.user.id, body.body
    )
    return {"id": str(note.id), "body": note.body}




# §145: pre-lifecycle status values and the canonical states the migration
# (f8a1c2d3e4b5) rewrites them to. The request body above still defaults to
# the legacy 'connected', so transition decisions must compare through this
# mapping — otherwise every re-registration of a legacy row would look like
# a jump from a state the lifecycle table does not name.
_LEGACY_STATUS_ALIASES = {"connected": "active", "error": "reauth_required"}
_CHANNEL_PROVIDERS = frozenset({"whatsapp", "instagram", "messenger", "telegram", "webchat"})
_CHANNEL_CREDENTIAL_FIELDS = {
    "whatsapp": frozenset({"access_token"}),
    "instagram": frozenset({"api_key"}),
    "messenger": frozenset({"api_key"}),
    "telegram": frozenset({"bot_token"}),
    "webchat": frozenset(),
}
_CHANNEL_CONFIG_FIELDS = {
    "whatsapp": frozenset({"phone_number_id"}),
    "instagram": frozenset({"account_id"}),
    "messenger": frozenset(),
    "telegram": frozenset(),
    "webchat": frozenset(),
}
_SIGNED_WEBHOOK_PROVIDERS = frozenset({"whatsapp", "instagram", "messenger", "telegram"})


def _last_webhook_at(integration: Integration) -> str | None:
    health = integration.webhook_health
    value = health.get("last_webhook_at") if isinstance(health, dict) else None
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else None


def _webhook_status(integration: Integration) -> str:
    if integration.provider == "webchat":
        config = integration.config if isinstance(integration.config, dict) else {}
        connection = config.get("_connection")
        verified = isinstance(connection, dict) and bool(connection.get("verified_at"))
        connected = integration.status in {"active", "connected"}
        return "ready" if verified and connected else "server_setup_required"

    from app.core.config import get_settings

    settings = get_settings()
    public_api_configured = _telegram_webhook_base_url() is not None
    configured = {
        "whatsapp": public_api_configured
        and bool(settings.whatsapp_app_secret and settings.whatsapp_verify_token),
        "messenger": public_api_configured
        and bool(settings.messenger_app_secret and settings.messenger_verify_token),
        "instagram": public_api_configured
        and bool(settings.instagram_app_secret and settings.instagram_verify_token),
        "telegram": public_api_configured and telegram_webhook_secret_configured(),
    }.get(integration.provider, False)
    if not configured:
        return "server_setup_required"
    if integration.provider == "telegram":
        connection = (
            integration.config.get("_connection")
            if isinstance(integration.config, dict)
            else None
        )
        if not isinstance(connection, dict) or not connection.get("webhook_configured_at"):
            return "server_setup_required"
    return "receiving" if _last_webhook_at(integration) else "awaiting_first_event"


def _telegram_webhook_base_url() -> str | None:
    from app.core.config import get_settings

    base = get_settings().api_public_base_url.strip().rstrip("/")
    parsed = urlparse(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    return base


def _telegram_webhook_url(public_key: str) -> str:
    base = _telegram_webhook_base_url()
    if base is None:
        raise ExternalProviderError(
            "Telegram webhook setup requires the server's canonical HTTPS API URL.",
            retryable=False,
        )
    route = f"{base}/api/v1/webhooks/telegram"
    return f"{route}?{urlencode({'tenant_key': public_key})}"


def _provider_webhook_url(provider: str) -> str | None:
    if provider not in _SIGNED_WEBHOOK_PROVIDERS:
        return None
    if provider == "telegram":
        return None
    base = _telegram_webhook_base_url()
    if base is None:
        return None
    return f"{base}/api/v1/webhooks/{provider}"


def _integration_output(integration: Integration) -> dict:
    config = integration.config if isinstance(integration.config, dict) else {}
    connection = config.get("_connection")
    if not isinstance(connection, dict):
        connection = {}
    verified_at = connection.get("verified_at")
    if not isinstance(verified_at, str):
        verified_at = None
    display_name = connection.get("display_name")
    if not isinstance(display_name, str):
        display_name = None
    public_key = (
        config.get("public_key")
        if integration.provider in {"webchat", "telegram"}
        and integration.kind == "channel"
        else None
    )
    webhook_url = (
        _telegram_webhook_url(public_key)
        if integration.provider == "telegram" and public_key and _telegram_webhook_base_url()
        else _provider_webhook_url(integration.provider)
    )
    return {
        "id": str(integration.id),
        "provider": integration.provider,
        "kind": integration.kind,
        "status": integration.status,
        "credentials_verified": bool(verified_at)
        and integration.status in {"active", "connected"},
        "display_name": display_name,
        "verified_at": verified_at,
        "webhook_status": _webhook_status(integration),
        "last_webhook_at": _last_webhook_at(integration),
        "webhook_url": webhook_url,
        "public_key": public_key if integration.provider == "webchat" else None,
    }


def _activate_verified_channel(integration: Integration) -> None:
    """Apply the legal lifecycle path after provider verification succeeds."""
    current = _LEGACY_STATUS_ALIASES.get(integration.status, integration.status)
    if current == "active":
        integration.status = "active"
        return
    if current in {"pending", "reauth_required", "disconnected"}:
        Integration.validate_transition(current, "connecting")
        integration.status = "connecting"
        current = "connecting"
    if current != "active":
        Integration.validate_transition(current, "active")
    integration.status = "active"


def _verification_metadata(
    *, verified_at: str | None, display_name: str | None, failure: str | None = None
) -> dict:
    result = {"verified_at": verified_at, "display_name": display_name}
    if failure:
        result["last_failure"] = failure
    return result


@platform_router.get("/invitations", response_model=list[schemas.PlatformInvitation])
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


@platform_router.delete(
    "/invitations/{invitation_id}",
    status_code=204,
)
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


@platform_router.get("/integrations", response_model=list[schemas.IntegrationOut])
async def list_integrations(ctx: SettingsReadCtx):
    rows = (
        (
            await ctx.session.execute(
                select(Integration).where(Integration.tenant_id == ctx.tenant_id).limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [_integration_output(i) for i in rows]


@platform_router.post(
    "/integrations/connect",
    status_code=201,
    response_model=schemas.IntegrationVerificationOut,
)
async def connect_integration(
    body: schemas.IntegrationConnectBody,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Verify credentials before persisting a channel as active."""
    provider = body.provider
    unexpected = set(body.credentials) - _CHANNEL_CREDENTIAL_FIELDS[provider]
    if unexpected:
        raise ValidationError("Unexpected credential fields for this provider.")
    unexpected_config = set(body.config) - _CHANNEL_CONFIG_FIELDS[provider]
    if unexpected_config:
        raise ValidationError("Unexpected channel configuration fields for this provider.")
    credentials = {key: value.strip() for key, value in body.credentials.items()}

    existing = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.tenant_id == ctx.tenant_id,
                Integration.provider == provider,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == "disabled":
        raise ValidationError("This channel was permanently disabled and cannot be reconnected.")
    if existing is None:
        await EntitlementService.ensure_channel_allowed(ctx.session, ctx.tenant_id, provider)

    verification_config = (
        dict(existing.config)
        if existing and isinstance(existing.config, dict)
        else {}
    )
    verification_config.update(body.config)
    verified = await verify_channel_credentials(provider, credentials, verification_config)
    verified_at = datetime.now(UTC).isoformat()
    integration_config = {
        **verified.identity_config,
        "_connection": _verification_metadata(
            verified_at=verified_at, display_name=verified.display_name
        ),
    }

    if existing is None:
        integration = Integration(
            id=uuid.uuid4(),
            tenant_id=ctx.tenant_id,
            provider=provider,
            kind="channel",
            config=integration_config,
            credentials=encrypt_credentials_dict(credentials),
            status="pending",
        )
        _activate_verified_channel(integration)
        ctx.session.add(integration)
    else:
        _activate_verified_channel(existing)
        existing.config = integration_config
        existing.credentials = encrypt_credentials_dict(credentials)
        integration = existing

    try:
        await ctx.session.flush()
    except IntegrityError:
        # The partial unique index covers provider identity across tenants.
        # Never expose the conflicting tenant or any provider account details.
        raise ConflictError(
            "This provider account is already connected to another workspace."
        ) from None

    if provider == "telegram":
        await configure_telegram_webhook(
            credentials,
            _telegram_webhook_url(integration_config["public_key"]),
        )
        connection_metadata = dict(integration_config["_connection"])
        connection_metadata["webhook_configured_at"] = datetime.now(UTC).isoformat()
        integration_config = {**integration_config, "_connection": connection_metadata}
        integration.config = integration_config
        await ctx.session.flush()

    return {
        "id": str(integration.id),
        "provider": provider,
        "status": integration.status,
        "credentials_verified": True,
        "display_name": verified.display_name,
        "verified_at": verified_at,
        "public_key": integration_config.get("public_key") if provider == "webchat" else None,
    }


@platform_router.post(
    "/integrations/{integration_id}/verify",
    response_model=schemas.IntegrationVerificationOut,
)
async def verify_integration(
    integration_id: UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Recheck a saved connection without returning its encrypted credentials."""
    integration = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.tenant_id == ctx.tenant_id,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("channel integration not found")
    if integration.provider not in _CHANNEL_PROVIDERS:
        raise ValidationError("This channel provider cannot be verified.")
    if integration.status == "disabled":
        raise ValidationError("This channel was permanently disabled.")

    credentials = await IntegrationCredentialsService.decrypt(ctx.session, integration)
    try:
        verified = await verify_channel_credentials(
            integration.provider, credentials, integration.config or {}
        )
    except ValidationError as exc:
        current = _LEGACY_STATUS_ALIASES.get(integration.status, integration.status)
        if current == "active":
            Integration.validate_transition(current, "reauth_required")
            integration.status = "reauth_required"
        config = dict(integration.config or {})
        config["_connection"] = _verification_metadata(
            verified_at=None,
            display_name=(config.get("_connection") or {}).get("display_name"),
            failure="credentials_rejected",
        )
        integration.config = config
        await ctx.session.flush()
        return {
            "id": str(integration.id),
            "provider": integration.provider,
            "status": integration.status,
            "credentials_verified": False,
            "display_name": (config.get("_connection") or {}).get("display_name"),
            "verified_at": None,
            "public_key": config.get("public_key") if integration.provider == "webchat" else None,
            "message": exc.message,
        }

    _activate_verified_channel(integration)
    verified_at = datetime.now(UTC).isoformat()
    integration.config = {
        **verified.identity_config,
        "_connection": _verification_metadata(
            verified_at=verified_at, display_name=verified.display_name
        ),
    }
    try:
        await ctx.session.flush()
    except IntegrityError:
        raise ConflictError(
            "This provider account is already connected to another workspace."
        ) from None
    if integration.provider == "telegram":
        await configure_telegram_webhook(
            credentials,
            _telegram_webhook_url(integration.config["public_key"]),
        )
        connection_metadata = dict(integration.config["_connection"])
        connection_metadata["webhook_configured_at"] = datetime.now(UTC).isoformat()
        integration.config = {
            **integration.config,
            "_connection": connection_metadata,
        }
        await ctx.session.flush()
    return {
        "id": str(integration.id),
        "provider": integration.provider,
        "status": integration.status,
        "credentials_verified": True,
        "display_name": verified.display_name,
        "verified_at": verified_at,
        "public_key": integration.config.get("public_key")
        if integration.provider == "webchat"
        else None,
    }


@platform_router.post(
    "/integrations",
    status_code=201,
    response_model=schemas.IntegrationUpserted,
)
async def upsert_integration(
    body: IntegrationBody,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Register a non-channel integration through the generic lifecycle API."""
    if body.kind == "channel" and body.provider in _CHANNEL_PROVIDERS:
        raise ValidationError("Use POST /integrations/connect to verify channel credentials.")
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
        # §145: a status CHANGE on an existing row must be a legal lifecycle
        # transition — validate_transition was dead code while this wrote
        # status directly. Creation (below) and same-status re-upserts skip
        # the check so the webhook-credential refresh path (idempotent
        # re-register) cannot fail. The check runs BEFORE any field is
        # written so a rejected upsert stages no partial write.
        from_status = _LEGACY_STATUS_ALIASES.get(existing.status, existing.status)
        to_status = _LEGACY_STATUS_ALIASES.get(body.status, body.status)
        if to_status != from_status:
            try:
                Integration.validate_transition(from_status, to_status)
            except ValueError as exc:
                raise ValidationError(
                    str(exc),
                    details={
                        "from_status": existing.status,
                        "to_status": body.status,
                        "allowed": sorted(
                            Integration._LIFECYCLE_TRANSITIONS.get(from_status, set())
                        ),
                    },
                ) from exc
        existing.config = body.config
        # §68: credentials are encrypted at rest BEFORE they touch the row.
        # Merge semantics (§145): an update WITHOUT a credentials payload is
        # the documented idempotent re-register (webhook/config refresh) and
        # must not erase the channel secrets already stored — the default {}
        # would otherwise silently wipe them and break the next outbound send.
        if body.credentials:
            existing.credentials = encrypt_credentials_dict(body.credentials)
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
        # §68: credentials are encrypted at rest BEFORE they touch the row.
        credentials=encrypt_credentials_dict(body.credentials),
        status=body.status,
    )
    ctx.session.add(integration)
    await ctx.session.flush()
    return {"id": str(integration.id), "status": integration.status}

"""The website purchase lifecycle (v1 money story = manual confirmation).

Tenant side: submit a purchase for a template (price snapshotted from the
manifest), record the payment reference, cancel while pending. Platform-admin
side: confirm — which in ONE transaction activates the website from the
template, publishes it, writes the public snapshot and stages the events — or
reject (frees the slug).

Cross-tenant admin access never weakens a tenant policy: the admin route
resolves the purchase's owning tenant through the ``resolve_website_purchase_tenant``
SECURITY DEFINER function, binds that tenant, and every write runs under the
normal tenant GUC. Slug claims are serialized per-slug with a
``pg_advisory_xact_lock`` and checked cross-table through the
``website_slug_taken`` definer — the two RLS tables (websites + purchases)
cannot answer the question with one per-tenant SELECT.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.core.errors import NotFoundError, ValidationError
from app.core.events.writer import add_outbox_event
from app.modules.identity.deps import TenantContext
from app.modules.website import models as ws
from app.modules.website.errors import (
    PurchaseStateError,
    SlugUnavailableError,
    TemplateNotFoundError,
    WebsiteDomainError,
)
from app.modules.website.services.publishing_service import publish as publish_website
from app.modules.website.slugs import slugify, validate_slug
from app.modules.website.templates import TemplateManifest, catalog

# The price is what the tenant pays US for the website service — it is our own
# list price (EGP), not money the tenant trades in, so it does not ride the
# §47 tenant-currency rule that governs commerce amounts.
PLATFORM_CURRENCY = "EGP"


def _now() -> datetime:
    return datetime.now(UTC)


async def _live_website(session: AsyncSession, tenant_id: uuid.UUID) -> ws.Website | None:
    return (
        await session.execute(
            sa.select(ws.Website)
            .where(ws.Website.tenant_id == tenant_id, ws.Website.status != "deleted")
            .order_by(ws.Website.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _open_purchase(session: AsyncSession, tenant_id: uuid.UUID) -> ws.WebsitePurchase | None:
    return (
        await session.execute(
            sa.select(ws.WebsitePurchase)
            .where(
                ws.WebsitePurchase.tenant_id == tenant_id,
                ws.WebsitePurchase.status.in_(sorted(ws.WEBSITE_PURCHASE_OPEN_STATUSES)),
            )
            .order_by(ws.WebsitePurchase.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def create(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    template_id: str,
    site_name: str,
    slug: str | None = None,
    payment_reference: str | None = None,
) -> ws.WebsitePurchase:
    manifest = catalog.get(template_id)  # TemplateNotFoundError -> 404

    if await _live_website(session, ctx.tenant_id) is not None:
        raise PurchaseStateError("this workspace already has a website")
    if await _open_purchase(session, ctx.tenant_id) is not None:
        raise PurchaseStateError("there is already an open website purchase")

    name = (site_name or "").strip()
    if not name:
        raise ValidationError("site name is required")

    desired = (slug or "").strip().lower() or slugify(name)
    if not desired:
        # A module error, not the generic one: the dashboard keys its Arabic
        # message (ask for an explicit address) off this code.
        raise WebsiteDomainError(
            "site address is required — the site name has no latin characters to slugify"
        )
    validate_slug(desired)

    # Race-safe claim: serialize on the slug, then ask the SECURITY DEFINER
    # whether either RLS table already holds it (cross-tenant by definition).
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"website-slug:{desired}"},
    )
    taken = (
        await session.execute(text("SELECT public.website_slug_taken(:slug)"), {"slug": desired})
    ).scalar()
    if taken:
        raise SlugUnavailableError(details={"slug": desired})

    reference = (payment_reference or "").strip()[:200] or None
    purchase = ws.WebsitePurchase(
        tenant_id=ctx.tenant_id,
        template_id=manifest.id,
        status="pending_payment",
        price=manifest.price,
        currency=PLATFORM_CURRENCY,
        site_name=name,
        slug=desired,
        payment_reference=reference,
    )
    session.add(purchase)
    await session.flush()
    await add_outbox_event(
        session,
        aggregate_type="website",
        aggregate_id=purchase.id,
        event_type="website.purchase.created",
        tenant_id=ctx.tenant_id,
        payload={
            "purchase_id": str(purchase.id),
            "template_id": manifest.id,
            "slug": desired,
            "price": f"{manifest.price:.2f}",
            "currency": PLATFORM_CURRENCY,
        },
    )
    return purchase


async def set_payment_reference(
    session: AsyncSession, ctx: TenantContext, *, reference: str
) -> ws.WebsitePurchase:
    purchase = await _open_purchase(session, ctx.tenant_id)
    if purchase is None:
        raise PurchaseStateError("there is no open website purchase to reference")
    value = (reference or "").strip()
    if not value:
        raise ValidationError("payment reference is required")
    purchase.payment_reference = value[:200]
    await session.flush()
    return purchase


async def cancel(session: AsyncSession, ctx: TenantContext) -> ws.WebsitePurchase:
    purchase = await _open_purchase(session, ctx.tenant_id)
    if purchase is None:
        raise PurchaseStateError("there is no open website purchase to cancel")
    purchase.status = "cancelled"
    await session.flush()
    return purchase


async def _admin_purchase_tenant(session: AsyncSession, purchase_id: uuid.UUID) -> uuid.UUID:
    """The owning tenant of a PENDING purchase, via the SECURITY DEFINER —
    the admin session has no tenant GUC, and the policy stays strict."""
    tenant_id = (
        await session.execute(
            text("SELECT public.resolve_website_purchase_tenant(:pid)"),
            {"pid": str(purchase_id)},
        )
    ).scalar()
    if tenant_id is None:
        raise NotFoundError("no pending website purchase with this id")
    return tenant_id


async def _load_pending_purchase(
    session: AsyncSession, purchase_id: uuid.UUID, tenant_id: uuid.UUID
) -> ws.WebsitePurchase:
    purchase = (
        await session.execute(
            sa.select(ws.WebsitePurchase).where(
                ws.WebsitePurchase.id == purchase_id, ws.WebsitePurchase.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if purchase is None or purchase.status != "pending_payment":
        raise PurchaseStateError("purchase is not pending payment")
    return purchase


async def _activate_website(
    session: AsyncSession, purchase: ws.WebsitePurchase, manifest: TemplateManifest
) -> ws.Website:
    """Create the website (template content) and publish its initial version."""
    website = ws.Website(
        tenant_id=purchase.tenant_id,
        name=purchase.site_name,
        status="draft",
        slug=purchase.slug,
        template_id=purchase.template_id,
        theme_tokens=dict(manifest.theme_tokens),
        navigation=[],
    )
    session.add(website)
    await session.flush()

    version = ws.WebsiteVersion(
        tenant_id=purchase.tenant_id,
        website_id=website.id,
        label=f"Initial — {manifest.name}",
        status="draft",
    )
    session.add(version)
    await session.flush()

    for page_preset in manifest.pages:
        page = ws.WebsitePage(
            tenant_id=purchase.tenant_id,
            version_id=version.id,
            title=page_preset.title,
            slug=page_preset.slug,
            meta_description=None,
        )
        session.add(page)
        await session.flush()
        for order, preset_section in enumerate(page_preset.sections):
            session.add(
                ws.WebsitePageSection(
                    tenant_id=purchase.tenant_id,
                    page_id=page.id,
                    section_type=preset_section.type,
                    props=dict(preset_section.props),
                    sort_order=order,
                )
            )
    await session.flush()

    await publish_website(
        session,
        tenant_id=purchase.tenant_id,
        website_id=website.id,
        version_id=version.id,
    )
    return website


async def confirm(
    session: AsyncSession, *, purchase_id: uuid.UUID, confirmed_by_user_id: uuid.UUID
) -> dict:
    tenant_id = await _admin_purchase_tenant(session, purchase_id)
    await bind_tenant(session, tenant_id)
    purchase = await _load_pending_purchase(session, purchase_id, tenant_id)

    # The template must still exist: a manifest removed between purchase and
    # confirmation fails loudly instead of activating a site nobody can render.
    try:
        manifest = catalog.get(purchase.template_id)
    except TemplateNotFoundError:
        raise
    website = await _activate_website(session, purchase, manifest)

    purchase.status = "activated"
    purchase.website_id = website.id
    purchase.confirmed_by_user_id = confirmed_by_user_id
    purchase.confirmed_at = _now()
    await session.flush()

    await add_outbox_event(
        session,
        aggregate_type="website",
        aggregate_id=purchase.id,
        event_type="website.purchase.confirmed",
        tenant_id=tenant_id,
        payload={
            "purchase_id": str(purchase.id),
            "website_id": str(website.id),
            "slug": website.slug,
            "template_id": purchase.template_id,
        },
    )
    return {
        "purchase_id": str(purchase.id),
        "website_id": str(website.id),
        "slug": website.slug,
        "status": purchase.status,
    }


async def reject(
    session: AsyncSession,
    *,
    purchase_id: uuid.UUID,
    confirmed_by_user_id: uuid.UUID,
    reason: str | None = None,
) -> dict:
    tenant_id = await _admin_purchase_tenant(session, purchase_id)
    await bind_tenant(session, tenant_id)
    purchase = await _load_pending_purchase(session, purchase_id, tenant_id)
    purchase.status = "rejected"
    purchase.confirmed_by_user_id = confirmed_by_user_id
    purchase.confirmed_at = _now()
    await session.flush()
    return {
        "purchase_id": str(purchase.id),
        "status": purchase.status,
        "reason": (reason or "").strip()[:200] or None,
    }

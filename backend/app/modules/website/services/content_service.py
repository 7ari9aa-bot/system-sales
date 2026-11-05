"""Merchant-side website content management.

v1 editing model, deliberately small but honest:

- IDENTITY (name, theme tokens) is website-level and NOT versioned: the
  change lands on the websites row AND the public snapshot row in the same
  transaction, so a recolor is live immediately.
- CONTENT (section props) is versioned: editing a section of the live version
  clones it into a draft (one draft at a time) and edits there; editing a
  draft edits in place. Going live is always an explicit publish.

The editor schema is derived from the section registry, so the dashboard's
generic form can never drift from what the server validates.
"""

from __future__ import annotations

import re
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.identity.deps import TenantContext
from app.modules.website import models as ws
from app.modules.website.errors import PurchaseStateError
from app.modules.website.sections import registry as section_registry
from app.modules.website.services.publishing_service import load_tree

_THEME_KEY_RE = re.compile(r"^[a-z0-9-]{1,40}$")
_THEME_VALUE_MAX = 120


async def _require_live_website(session: AsyncSession, tenant_id: uuid.UUID) -> ws.Website:
    website = (
        await session.execute(
            sa.select(ws.Website)
            .where(ws.Website.tenant_id == tenant_id, ws.Website.status != "deleted")
            .order_by(ws.Website.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if website is None:
        raise PurchaseStateError("this workspace has no website yet")
    return website


def _version_tree(
    version: ws.WebsiteVersion,
    pages: list[ws.WebsitePage],
    sections_by_page: dict[uuid.UUID, list[ws.WebsitePageSection]],
) -> dict:
    return {
        "version": {
            "id": str(version.id),
            "label": version.label,
            "status": version.status,
            "published_at": version.published_at.isoformat() if version.published_at else None,
        },
        "pages": [
            {
                "id": str(page.id),
                "title": page.title,
                "slug": page.slug,
                "meta_description": page.meta_description,
                "sections": [
                    {
                        "id": str(section.id),
                        "type": section.section_type,
                        "props": section.props or {},
                        "sort_order": section.sort_order,
                    }
                    for section in sections_by_page.get(page.id, [])
                ],
            }
            for page in pages
        ],
    }


def _live_url(slug: str) -> str:
    """The merchant-facing link to the published site. Subdomain mode (when
    WEBSITES_SERVED_DOMAIN is set) wins — that is the customer-facing shape;
    otherwise the path mode the backend serves today (proxied by the dev
    server and, in path deployments, by the edge)."""
    from app.core.config import get_settings

    served = (get_settings().websites_served_domain or "").strip()
    if served:
        return f"https://{slug}.{served}"
    return f"/sites/{slug}"


async def overview(session: AsyncSession, ctx: TenantContext) -> dict:
    purchase = (
        await session.execute(
            sa.select(ws.WebsitePurchase)
            .where(
                ws.WebsitePurchase.tenant_id == ctx.tenant_id,
                ws.WebsitePurchase.status.in_(["pending_payment", "paid"]),
            )
            .order_by(ws.WebsitePurchase.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    website = (
        await session.execute(
            sa.select(ws.Website)
            .where(ws.Website.tenant_id == ctx.tenant_id, ws.Website.status != "deleted")
            .order_by(ws.Website.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if website is not None:
        return {
            "state": "active",
            "website": {
                "id": str(website.id),
                "name": website.name,
                "slug": website.slug,
                "status": website.status,
                "template_id": website.template_id,
                "theme_tokens": website.theme_tokens or {},
                "published": website.published_version_id is not None,
                "live_url": _live_url(website.slug),
                "aggregate_version": website.aggregate_version,
            },
            "pending_purchase": None,
        }
    if purchase is not None:
        return {
            "state": "pending",
            "website": None,
            "pending_purchase": {
                "id": str(purchase.id),
                "template_id": purchase.template_id,
                "status": purchase.status,
                "site_name": purchase.site_name,
                "slug": purchase.slug,
                "price": f"{purchase.price:.2f}",
                "currency": purchase.currency,
                "payment_reference": purchase.payment_reference,
            },
        }
    return {"state": "none", "website": None, "pending_purchase": None}


async def get_content(session: AsyncSession, ctx: TenantContext) -> dict:
    website = await _require_live_website(session, ctx.tenant_id)

    published_tree = None
    if website.published_version_id is not None:
        version = (
            await session.execute(
                sa.select(ws.WebsiteVersion).where(
                    ws.WebsiteVersion.id == website.published_version_id
                )
            )
        ).scalar_one_or_none()
        if version is not None:
            pages, sections = await load_tree(session, version.id)
            published_tree = _version_tree(version, pages, sections)

    draft_version = (
        await session.execute(
            sa.select(ws.WebsiteVersion)
            .where(ws.WebsiteVersion.website_id == website.id, ws.WebsiteVersion.status == "draft")
            .order_by(ws.WebsiteVersion.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    draft_tree = None
    if draft_version is not None:
        pages, sections = await load_tree(session, draft_version.id)
        draft_tree = _version_tree(draft_version, pages, sections)

    return {
        "website": {
            "id": str(website.id),
            "name": website.name,
            "slug": website.slug,
            "status": website.status,
            "template_id": website.template_id,
            "theme_tokens": website.theme_tokens or {},
            "live_url": f"/sites/{website.slug}",
        },
        "published": published_tree,
        "draft": draft_tree,
    }


def _validate_theme_tokens(theme_tokens: dict) -> dict:
    if not isinstance(theme_tokens, dict):
        raise ValidationError("theme tokens must be an object")
    cleaned: dict[str, str] = {}
    for key, value in theme_tokens.items():
        if not isinstance(key, str) or not _THEME_KEY_RE.match(key):
            raise ValidationError(f"invalid theme token name: {key!r}")
        if not isinstance(value, str) or len(value) > _THEME_VALUE_MAX:
            raise ValidationError(f"invalid theme token value for {key!r}")
        cleaned[key] = value
    return cleaned


async def update_identity(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    name: str | None = None,
    theme_tokens: dict | None = None,
) -> dict:
    website = await _require_live_website(session, ctx.tenant_id)
    if name is not None:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValidationError("site name cannot be empty")
        website.name = cleaned_name[:200]
    if theme_tokens is not None:
        website.theme_tokens = _validate_theme_tokens(theme_tokens)

    # Identity renders immediately: refresh the public snapshot in the SAME
    # transaction (no republish needed — identity is not versioned content).
    snapshot = (
        await session.execute(
            sa.select(ws.WebsitePublishedSite).where(
                ws.WebsitePublishedSite.website_id == website.id
            )
        )
    ).scalar_one_or_none()
    if snapshot is not None:
        snapshot.name = website.name
        snapshot.theme_tokens = dict(website.theme_tokens or {})
        if snapshot.projection:
            snapshot.projection = {**snapshot.projection, "name": website.name}
    await session.flush()
    return {
        "website": {
            "id": str(website.id),
            "name": website.name,
            "slug": website.slug,
            "theme_tokens": website.theme_tokens or {},
        }
    }


async def _clone_published_into_draft(
    session: AsyncSession, website: ws.Website
) -> ws.WebsiteVersion:
    """Clone the live version (pages + sections) into the tenant's new draft."""
    source = (
        await session.execute(
            sa.select(ws.WebsiteVersion).where(ws.WebsiteVersion.id == website.published_version_id)
        )
    ).scalar_one_or_none()
    if source is None:
        raise NotFoundError("published version not found")
    draft = ws.WebsiteVersion(
        tenant_id=website.tenant_id,
        website_id=website.id,
        label="Draft — content edits",
        status="draft",
    )
    session.add(draft)
    await session.flush()
    pages, sections_by_page = await load_tree(session, source.id)
    for page in pages:
        new_page = ws.WebsitePage(
            tenant_id=website.tenant_id,
            version_id=draft.id,
            title=page.title,
            slug=page.slug,
            meta_description=page.meta_description,
        )
        session.add(new_page)
        await session.flush()
        for section in sections_by_page.get(page.id, []):
            session.add(
                ws.WebsitePageSection(
                    tenant_id=website.tenant_id,
                    page_id=new_page.id,
                    section_type=section.section_type,
                    props=dict(section.props or {}),
                    sort_order=section.sort_order,
                )
            )
    await session.flush()
    return draft


async def update_section(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    section_id: uuid.UUID,
    props: dict,
) -> dict:
    website = await _require_live_website(session, ctx.tenant_id)
    section = (
        await session.execute(
            sa.select(ws.WebsitePageSection).where(ws.WebsitePageSection.id == section_id)
        )
    ).scalar_one_or_none()
    if section is None:
        raise NotFoundError("section not found")
    page = (
        await session.execute(sa.select(ws.WebsitePage).where(ws.WebsitePage.id == section.page_id))
    ).scalar_one_or_none()
    if page is None:
        raise NotFoundError("page not found")
    version = (
        await session.execute(
            sa.select(ws.WebsiteVersion).where(ws.WebsiteVersion.id == page.version_id)
        )
    ).scalar_one_or_none()
    if version is None or version.website_id != website.id:
        # RLS already hides other tenants' rows; this catches our own
        # archived/foreign-version sections.
        raise NotFoundError("section is not part of this website")

    validated = section_registry.validate(section.section_type, props or {})
    new_props = validated.model_dump()

    if version.status == "draft":
        section.props = new_props
        section.version = (section.version or 1) + 1
        await session.flush()
        return {"version_id": str(version.id), "section_id": str(section.id), "cloned": False}

    if website.published_version_id != version.id:
        raise NotFoundError("section is not on the live version")
    draft = await _clone_published_into_draft(session, website)
    pages, sections_by_page = await load_tree(session, draft.id)
    target_page = next((p for p in pages if p.slug == page.slug), None)
    if target_page is None:
        raise NotFoundError("page not found in the new draft")
    target_section = next(
        (
            s
            for s in sections_by_page.get(target_page.id, [])
            if s.section_type == section.section_type and s.sort_order == section.sort_order
        ),
        None,
    )
    if target_section is None:
        raise NotFoundError("section not found in the new draft")
    target_section.props = new_props
    await session.flush()
    return {"version_id": str(draft.id), "section_id": str(target_section.id), "cloned": True}


async def versions(session: AsyncSession, ctx: TenantContext) -> list[dict]:
    website = await _require_live_website(session, ctx.tenant_id)
    rows = (
        await session.execute(
            sa.select(ws.WebsiteVersion)
            .where(ws.WebsiteVersion.website_id == website.id)
            .order_by(ws.WebsiteVersion.created_at.desc())
        )
    ).scalars()
    return [
        {
            "id": str(row.id),
            "label": row.label,
            "status": row.status,
            "published_at": row.published_at.isoformat() if row.published_at else None,
        }
        for row in rows
    ]


def editor_schema() -> list[dict]:
    """Per-section editable-field metadata for the dashboard's generic form."""
    return [{"type": spec.type, "fields": spec.field_schema()} for spec in section_registry.specs()]

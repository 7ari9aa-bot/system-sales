"""Versioning, publish and rollback — the presentation state machine.

Contract (pinned from the website-builder spec, now on real ORM + RLS):

- A version goes draft -> published; a publish or rollback archives every
  OTHER published version. Rollback targets are published/archived versions,
  and rolling back to the already-live version is a 409.
- Publish VALIDATES the whole version BEFORE any mutation: a failed publish
  must never break the live site (fail-closed).
- Publishing writes the public snapshot row (``website_published_sites``) in
  the SAME transaction as the publish, so Postgres stays the only truth and
  the public renderer reads one consistent row.
- Every transition stages its outbox event in that same transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.events.writer import add_outbox_event
from app.modules.website.errors import (
    NoDraftError,
    PublishValidationFailed,
    RollbackNotAllowed,
)
from app.modules.website.models import (
    Website,
    WebsitePage,
    WebsitePageSection,
    WebsitePublishedSite,
    WebsiteVersion,
)
from app.modules.website.sections import InvalidSection
from app.modules.website.sections import registry as section_registry


def _now() -> datetime:
    return datetime.now(UTC)


async def load_website(
    session: AsyncSession, tenant_id: uuid.UUID, website_id: uuid.UUID
) -> Website:
    website = (
        await session.execute(
            sa.select(Website).where(Website.id == website_id, Website.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if website is None:
        raise NotFoundError("website not found")
    return website


async def _load_version(
    session: AsyncSession, *, website_id: uuid.UUID, version_id: uuid.UUID
) -> WebsiteVersion:
    version = (
        await session.execute(
            sa.select(WebsiteVersion).where(
                WebsiteVersion.id == version_id, WebsiteVersion.website_id == website_id
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError("version not found")
    return version


async def load_tree(
    session: AsyncSession, version_id: uuid.UUID
) -> tuple[list[WebsitePage], dict[uuid.UUID, list[WebsitePageSection]]]:
    """The version's pages (in creation order) with their sections in render order."""
    pages = list(
        (
            await session.execute(
                sa.select(WebsitePage)
                .where(WebsitePage.version_id == version_id)
                .order_by(WebsitePage.created_at, WebsitePage.id)
            )
        ).scalars()
    )
    sections: dict[uuid.UUID, list[WebsitePageSection]] = {}
    if pages:
        rows = (
            await session.execute(
                sa.select(WebsitePageSection)
                .where(WebsitePageSection.page_id.in_([p.id for p in pages]))
                .order_by(WebsitePageSection.sort_order, WebsitePageSection.created_at)
            )
        ).scalars()
        for row in rows:
            sections.setdefault(row.page_id, []).append(row)
    return pages, sections


def build_projection(
    website: Website,
    version: WebsiteVersion,
    pages: list[WebsitePage],
    sections_by_page: dict[uuid.UUID, list[WebsitePageSection]],
) -> dict:
    """The validated, normalized projection stored on the public snapshot.

    Every section's props are re-validated through the registry and stored as
    ``model_dump()`` output — the public surface never sees raw editor input.
    Draft content never reaches here: callers pass the PUBLISHED version only.
    """
    projected_pages: list[dict] = []
    for page in pages:
        projected_sections: list[dict] = []
        for section in sections_by_page.get(page.id, []):
            validated = section_registry.validate(section.section_type, section.props or {})
            projected_sections.append(
                {"type": section.section_type, "props": validated.model_dump()}
            )
        projected_pages.append(
            {
                "id": str(page.id),
                "title": page.title,
                "slug": page.slug,
                "meta_description": page.meta_description,
                "sections": projected_sections,
            }
        )
    return {
        "website_id": str(website.id),
        "tenant_id": str(website.tenant_id),
        "version_id": str(version.id),
        "name": website.name,
        "default_locale": website.default_locale,
        "pages": projected_pages,
    }


async def validate_version(session: AsyncSession, version: WebsiteVersion) -> list[str]:
    """Full content validation; returns human-readable errors (empty = valid).

    Pure read — safe to call before any mutation, which is exactly the point:
    publish refuses BEFORE touching the live version.
    """
    errors: list[str] = []
    pages, sections_by_page = await load_tree(session, version.id)
    if not pages:
        errors.append("a version needs at least one page")
        return errors
    seen_slugs: set[str] = set()
    for page in pages:
        if not page.title:
            errors.append(f"page {page.slug!r} has no title")
        if not page.slug:
            errors.append(f"page {page.title!r} has no slug")
        elif page.slug in seen_slugs:
            errors.append(f"duplicate page slug: {page.slug!r}")
        else:
            seen_slugs.add(page.slug)
        for section in sections_by_page.get(page.id, []):
            try:
                section_registry.validate(section.section_type, section.props or {})
            except InvalidSection as exc:
                errors.append(f"page {page.slug!r}: {exc.message}")
    return errors


async def _upsert_snapshot(
    session: AsyncSession,
    website: Website,
    projection: dict,
    *,
    published_at: datetime,
) -> None:
    row = (
        await session.execute(
            sa.select(WebsitePublishedSite).where(WebsitePublishedSite.website_id == website.id)
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            WebsitePublishedSite(
                slug=website.slug,
                website_id=website.id,
                template_id=website.template_id,
                name=website.name,
                site_category=website.site_category,
                whatsapp_number=website.whatsapp_number,
                social_links=list(website.social_links or []),
                logo_url=website.logo_url,
                meta_description=website.meta_description,
                default_locale=website.default_locale,
                theme_tokens=dict(website.theme_tokens or {}),
                navigation=list(website.navigation or []),
                projection=projection,
                is_active=True,
                published_at=published_at,
            )
        )
    else:
        row.slug = website.slug
        row.template_id = website.template_id
        row.name = website.name
        row.site_category = website.site_category
        row.whatsapp_number = website.whatsapp_number
        row.social_links = list(website.social_links or [])
        row.logo_url = website.logo_url
        row.meta_description = website.meta_description
        row.default_locale = website.default_locale
        row.theme_tokens = dict(website.theme_tokens or {})
        row.navigation = list(website.navigation or [])
        row.projection = projection
        row.is_active = True
        row.published_at = published_at


async def publish(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> dict:
    """Publish a version: validate first (fail-closed), then flip statuses,
    move the published pointer, write the public snapshot and stage the event
    — all in the caller's transaction."""
    website = await load_website(session, tenant_id, website_id)
    if version_id is None:
        version = (
            await session.execute(
                sa.select(WebsiteVersion)
                .where(
                    WebsiteVersion.website_id == website_id,
                    WebsiteVersion.status == "draft",
                )
                .order_by(WebsiteVersion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if version is None:
            raise NoDraftError()
    else:
        version = await _load_version(session, website_id=website_id, version_id=version_id)

    errors = await validate_version(session, version)
    if errors:
        raise PublishValidationFailed(errors)

    pages, sections_by_page = await load_tree(session, version.id)
    projection = build_projection(website, version, pages, sections_by_page)

    await session.execute(
        sa.update(WebsiteVersion)
        .where(
            WebsiteVersion.website_id == website_id,
            WebsiteVersion.status == "published",
            WebsiteVersion.id != version.id,
        )
        .values(status="archived")
    )
    version.status = "published"
    version.published_at = _now()
    website.published_version_id = version.id
    website.status = "published"
    website.aggregate_version = (website.aggregate_version or 1) + 1

    await _upsert_snapshot(session, website, projection, published_at=version.published_at)

    await add_outbox_event(
        session,
        aggregate_type="website",
        aggregate_id=website.id,
        event_type="website.published",
        tenant_id=tenant_id,
        payload={
            "website_id": str(website.id),
            "version_id": str(version.id),
            "slug": website.slug,
        },
        aggregate_version=website.aggregate_version,
    )
    return {
        "website_id": str(website.id),
        "version_id": str(version.id),
        "slug": website.slug,
        "aggregate_version": website.aggregate_version,
    }


async def rollback(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    version_id: uuid.UUID,
) -> dict:
    website = await load_website(session, tenant_id, website_id)
    target = await _load_version(session, website_id=website_id, version_id=version_id)
    if target.status not in ("published", "archived"):
        raise RollbackNotAllowed("only a published or archived version can be restored")
    if website.published_version_id == target.id:
        raise RollbackNotAllowed("this version is already the live one")

    errors = await validate_version(session, target)
    if errors:
        raise PublishValidationFailed(errors)

    pages, sections_by_page = await load_tree(session, target.id)
    projection = build_projection(website, target, pages, sections_by_page)

    await session.execute(
        sa.update(WebsiteVersion)
        .where(
            WebsiteVersion.website_id == website_id,
            WebsiteVersion.status == "published",
            WebsiteVersion.id != target.id,
        )
        .values(status="archived")
    )
    target.status = "published"
    target.published_at = _now()
    website.published_version_id = target.id
    website.status = "published"
    website.aggregate_version = (website.aggregate_version or 1) + 1

    await _upsert_snapshot(session, website, projection, published_at=target.published_at)

    await add_outbox_event(
        session,
        aggregate_type="website",
        aggregate_id=website.id,
        event_type="website.rolled_back",
        tenant_id=tenant_id,
        payload={
            "website_id": str(website.id),
            "version_id": str(target.id),
            "slug": website.slug,
        },
        aggregate_version=website.aggregate_version,
    )
    return {
        "website_id": str(website.id),
        "version_id": str(target.id),
        "slug": website.slug,
        "aggregate_version": website.aggregate_version,
    }

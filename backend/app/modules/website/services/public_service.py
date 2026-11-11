"""The public site service — the read side of the unauthenticated surface.

Everything the public renderer needs lives on the ``website_published_sites``
row (no tenant GUC required). Live products are the ONE piece of business
truth the public page needs, fetched through the boundary-safe pattern: the
snapshot's server-stamped ``tenant_id`` is bound with ``bind_tenant`` and the
query runs under RLS against ``products`` via ``Base.metadata`` (no cross-
module import — the same trick the AI customer tools use).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa

from app.core.db import Base, bind_tenant
from app.modules.website.models import WebsitePublishedSite
from app.modules.website.rendering import RenderContext, render_website

# V1 collection semantics: a product grid shows the tenant's active products
# (the template's collection_id is a display label). One bounded query per
# request, shared by every grid on the page.
_MAX_PRODUCTS = 100


async def load_snapshot(
    session,
    *,  # noqa: ANN001 - session type comes from the router's DbSession
    slug: str | None = None,
    hostname: str | None = None,
) -> WebsitePublishedSite | None:
    stmt = sa.select(WebsitePublishedSite).where(WebsitePublishedSite.is_active.is_(True))
    if hostname is not None:
        stmt = stmt.where(WebsitePublishedSite.hostname == hostname.lower())
    else:
        stmt = stmt.where(WebsitePublishedSite.slug == (slug or "").lower())
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


def _resolve_site_image_url(value: str, site: WebsitePublishedSite) -> str:
    """An uploaded ``s3://`` key as a browser-readable URL, or "".

    The bucket is private — the avatar and product-image flows store keys and
    sign them at read time, never persisting an expiring URL. The key must sit
    inside the snapshot's own tenant prefix; anything else renders as "".
    """
    from app.core.storage import get_storage

    storage = get_storage()
    if not storage.configured:
        return ""
    tenant_raw = (site.projection or {}).get("tenant_id")
    if not tenant_raw:
        return ""
    key = value[len("s3://") :]
    prefix = f"site-images/{tenant_raw}/"
    filename = key[len(prefix) :] if key.startswith(prefix) else ""
    if not filename or "/" in filename:
        return ""
    try:
        return storage.signed_url(key, expires_in=7 * 24 * 60 * 60)
    except (RuntimeError, ValueError):
        return ""


async def _site_identity(site: WebsitePublishedSite) -> dict:
    """The merchant's own identity for the renderer's brand override.

    Uploaded images are stored as ``s3://`` keys; they resolve to a read URL
    here so the renderer's URL allowlist never sees the private scheme.
    """
    logo = (site.logo_url or "").strip()
    if logo.startswith("s3://"):
        logo = _resolve_site_image_url(logo, site)
    whatsapp_raw = (site.whatsapp_number or "").strip()
    whatsapp = ""
    if whatsapp_raw:
        digits = "".join(ch for ch in whatsapp_raw if ch.isdigit())
        if digits:
            whatsapp = f"https://wa.me/{digits}"
    return {
        "name": site.name,
        "logo_url": logo,
        "whatsapp": whatsapp,
        "whatsapp_number": whatsapp_raw,
        "social_links": list(site.social_links or []),
        "site_category": site.site_category or "",
    }


def _collections_in(projection: dict) -> list[str]:
    out: list[str] = []
    for page in projection.get("pages", []):
        for section in page.get("sections", []):
            if section.get("type") == "product_grid":
                collection = str((section.get("props") or {}).get("collection_id") or "")
                if collection and collection not in out:
                    out.append(collection)
    return out


async def _load_products(session, tenant_id: uuid.UUID, limit: int) -> list[dict]:  # noqa: ANN001
    # Function-scope import on purpose: it registers the catalog tables in the
    # shared ``Base.metadata`` (main.py imports every module, so production
    # always has them; tests import narrowly). This is the boundary-safe read
    # the module rules require — never a module-scope cross-module import.
    from app.modules.catalog import models as _catalog_models  # noqa: F401

    products = Base.metadata.tables["products"]
    variants = Base.metadata.tables["product_variants"]
    rows = (
        await session.execute(
            sa.select(products.c.title, sa.func.min(variants.c.price).label("price"))
            .select_from(products.outerjoin(variants, variants.c.product_id == products.c.id))
            .where(products.c.status == "active")
            .group_by(products.c.id, products.c.title, products.c.created_at)
            .order_by(products.c.created_at.desc())
            .limit(max(1, min(limit, _MAX_PRODUCTS)))
        )
    ).all()
    out: list[dict] = []
    for title, price in rows:
        price_str = None
        if price is not None:
            price_str = f"{Decimal(price):,.2f} ج.م"
        out.append({"title": title, "price": price_str})
    return out


async def render_html(session, site: WebsitePublishedSite) -> str:  # noqa: ANN001
    snapshot = {
        "name": site.name,
        "default_locale": site.default_locale,
        "template_id": site.template_id,
        "theme_tokens": site.theme_tokens or {},
        "navigation": site.navigation or [],
        "projection": site.projection or {},
        "identity": await _site_identity(site),
    }
    ctx = RenderContext()
    collections = _collections_in(site.projection or {})
    tenant_raw = (site.projection or {}).get("tenant_id")
    if collections and tenant_raw:
        try:
            tenant_id = uuid.UUID(str(tenant_raw))
        except ValueError:
            tenant_id = None
        if tenant_id is not None:
            # Bind the snapshot's server-stamped tenant so the product read is
            # RLS-honest; the binding lives only inside this transaction.
            await bind_tenant(session, tenant_id)
            products = await _load_products(session, tenant_id, _MAX_PRODUCTS)
            ctx.products_by_collection = {c: products for c in collections}
    return render_website(snapshot, ctx)

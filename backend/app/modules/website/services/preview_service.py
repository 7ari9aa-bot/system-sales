"""The template preview walk — a complete demo site per template.

``GET /sites/preview/<template-id>[/<page-slug>]`` renders the template's
seed content as a walkable multi-page site: home, products, stores, faq and
the rest, with themed demo products in the grids and real page-to-page
navigation. NOTHING touches the database: the projection is built from the
fail-closed template manifest on every request, so a preview can never drift
from its template and needs no storage, no publish, no purchase.

Anchor rewriting: the seeded content links pages with ``#page-<slug>``
anchors (the published site is one document). On the preview walk every
known anchor is rewritten to ``/sites/preview/<id>/<slug>`` so the visitor
actually navigates. The ribbon marks the page as a demo.
"""

from __future__ import annotations

from typing import Any

from app.modules.website.rendering import RenderContext, render_website
from app.modules.website.templates import TemplateManifest, catalog

GENERIC_DEMO_PRODUCTS: tuple[dict, ...] = (
    {"title": "منتج تجريبي ١", "price": "150.00 ج.م"},
    {"title": "منتج تجريبي ٢", "price": "240.00 ج.م"},
    {"title": "منتج تجريبي ٣", "price": "320.00 ج.م"},
    {"title": "منتج تجريبي ٤", "price": "480.00 ج.م"},
    {"title": "منتج تجريبي ٥", "price": "95.00 ج.م"},
    {"title": "منتج تجريبي ٦", "price": "610.00 ج.م"},
)

_RIBBON_CSS = (
    "<style>.preview-ribbon{position:fixed;bottom:12px;inset-inline-start:12px;"
    "background:#111;color:#fff;padding:8px 14px;border-radius:999px;font-size:12px;"
    "font-weight:700;z-index:60;opacity:.93;font-family:system-ui,sans-serif}</style>"
)


def _demo_products(manifest: TemplateManifest) -> list[dict]:
    products = manifest.demo_products or GENERIC_DEMO_PRODUCTS
    return [dict(p) for p in products]


def _rewrite_anchors(value: Any, slug_to_url: dict[str, str]) -> Any:
    """Deep-rewrite ``#page-<slug>`` anchors into preview walk URLs."""
    if isinstance(value, str):
        return slug_to_url.get(value, value)
    if isinstance(value, dict):
        return {k: _rewrite_anchors(v, slug_to_url) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_anchors(v, slug_to_url) for v in value]
    return value


def render_template_preview(template_id: str, page_slug: str | None = None) -> str | None:
    """The full demo-site HTML for a template, or None when the template (or
    the requested page slug) does not exist."""
    try:
        manifest = catalog.get(template_id)
    except Exception:  # noqa: BLE001 - unknown template is a plain 404 upstream
        return None

    pages = [
        {
            "title": page.title,
            "slug": page.slug,
            "sections": [
                {"type": section.type, "props": dict(section.props)} for section in page.sections
            ],
        }
        for page in manifest.pages
    ]
    if page_slug is not None and page_slug not in {p["slug"] for p in pages}:
        return None

    prefix = f"/sites/preview/{template_id}"
    slug_to_url = {f"#page-{p['slug']}": f"{prefix}/{p['slug']}" for p in pages}

    demo_name = manifest.name_ar
    snapshot = {
        "name": demo_name,
        "default_locale": "ar",
        "template_id": manifest.id,
        "theme_tokens": dict(manifest.theme_tokens),
        "navigation": [],
        "projection": {
            "pages": [
                {**p, "sections": [_rewrite_anchors(s, slug_to_url) for s in p["sections"]]}
                for p in pages
            ]
        },
    }

    ctx = RenderContext()
    collections: set[str] = set()
    for page in pages:
        for section in page["sections"]:
            if section["type"] == "product_grid":
                collections.add(str((section["props"] or {}).get("collection_id") or ""))
    products = _demo_products(manifest)
    ctx.products_by_collection = {c: products for c in collections if c}

    banner = (
        f"{_RIBBON_CSS}"
        f'<div class="preview-ribbon">معاينة تجريبية — التصميم: {manifest.name_ar}</div>'
    )
    return render_website(
        snapshot,
        ctx,
        page_slug=page_slug,
        page_url_prefix=prefix,
        banner_html=banner,
    )

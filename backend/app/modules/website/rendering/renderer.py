"""Public site runtime renderer (presentation layer).

Renders a published snapshot into a full HTML document. The section registry
owns the props; the renderer owns the markup. Rules pinned from the spec and
hardened here:

- EVERY interpolation is HTML-escaped, including attribute contexts.
- URLs go through a scheme allowlist (http/https/tel/mailto, relative ``/``
  and ``#`` anchors) — a ``javascript:`` href renders as an inert ``#`` anchor
  instead of surviving the escape as live script.
- Unknown section types render as empty (never raise) — a template updated
  ahead of its renderer must not take a live site down.
- The document is Arabic-first RTL (``dir``/``lang`` from the snapshot's
  locale).

Business truth (products) arrives via ``RenderContext.products_by_collection``
built by the caller from a boundary-safe metadata-table read — the renderer
itself never queries commerce tables.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape
from typing import Any

# (props, ctx) -> html fragment
SectionRenderer = Callable[[dict, "RenderContext"], str]


@dataclass(slots=True)
class RenderContext:
    products_by_collection: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _e(value: Any) -> str:
    return escape(str(value)) if value not in (None, "") else ""


# The allowlist, checked case-insensitively on the lowercased value.
_ALLOWED_PREFIXES = ("http://", "https://", "mailto:", "tel:")


def _safe_url(raw: Any) -> str:
    """Allowlist for every rendered href/src — the escape alone would happily
    keep a ``javascript:`` payload alive as a clickable XSS. Anything that is
    not an allowed absolute scheme, or a relative path/anchor, renders as an
    inert ``#`` anchor."""
    value = str(raw or "").strip()
    if not value:
        return ""
    if value.lower().startswith(_ALLOWED_PREFIXES):
        return escape(value, quote=True)
    if value.startswith("#") or value.startswith("/"):
        return escape(value, quote=True)
    return "#"


def _render_hero(props: dict, _ctx: RenderContext) -> str:
    heading = _e(props.get("heading"))
    sub = _e(props.get("subheading"))
    sub_html = f"<p>{sub}</p>" if sub else ""
    cta = ""
    if props.get("cta_label") and props.get("cta_url"):
        url = _safe_url(props.get("cta_url"))
        if url and url != "#":
            cta = f'<a href="{url}">{_e(props.get("cta_label"))}</a>'
    return f'<section class="hero"><h1>{heading}</h1>{sub_html}{cta}</section>'


def _render_rich_text(props: dict, _ctx: RenderContext) -> str:
    return f'<section class="rich-text">{_e(props.get("content"))}</section>'


def _render_image_text(props: dict, _ctx: RenderContext) -> str:
    side = "right" if props.get("image_side") == "right" else "left"
    image = _safe_url(props.get("image"))
    heading = _e(props.get("heading"))
    text = _e(props.get("text"))
    img = f'<img src="{image}" alt="">' if image and image != "#" else ""
    return (
        f'<section class="image-text image-text--{side}">'
        f"{img}<div><h2>{heading}</h2><p>{text}</p></div></section>"
    )


def _render_product_grid(props: dict, ctx: RenderContext) -> str:
    collection = str(props.get("collection_id") or "")
    title = _e(props.get("title"))
    title_html = f"<h2>{title}</h2>" if title else ""
    products = ctx.products_by_collection.get(collection, [])
    cards = "".join(
        f'<div class="product-card"><div class="ph"></div>'
        f'<div class="name">{_e(p.get("title"))}</div>'
        f'<div class="price">{_e(p.get("price"))}</div></div>'
        for p in products
    )
    return (
        f'<section class="product-grid" data-collection="{_e(collection)}">'
        f'{title_html}<div class="cards">{cards}</div></section>'
    )


def _render_collection_grid(props: dict, _ctx: RenderContext) -> str:
    ids = ",".join(_e(c) for c in props.get("collection_ids", []))
    return f'<section class="collection-grid" data-collections="{ids}"></section>'


def _render_testimonial(props: dict, _ctx: RenderContext) -> str:
    quote = _e(props.get("quote"))
    author = _e(props.get("author"))
    role = _e(props.get("role"))
    cite = f"<cite>{author}, {role}</cite>" if role else f"<cite>{author}</cite>"
    return f'<section class="testimonial"><blockquote>{quote}</blockquote>{cite}</section>'


def _render_faq(props: dict, _ctx: RenderContext) -> str:
    items_html = ""
    for item in props.get("items", []):
        q = _e(item.get("q"))
        a = _e(item.get("a"))
        items_html += f"<details><summary>{q}</summary><p>{a}</p></details>"
    return f'<section class="faq">{items_html}</section>'


def _render_cta(props: dict, _ctx: RenderContext) -> str:
    heading = _e(props.get("heading"))
    sub = _e(props.get("subheading"))
    sub_html = f"<p>{sub}</p>" if sub else ""
    label = _e(props.get("button_label"))
    url = _safe_url(props.get("button_url"))
    link = f'<a href="{url}">{label}</a>' if url and url != "#" else ""
    return f'<section class="cta"><h2>{heading}</h2>{sub_html}{link}</section>'


def _render_newsletter(props: dict, _ctx: RenderContext) -> str:
    heading = _e(props.get("heading"))
    sub = _e(props.get("subheading"))
    sub_html = f"<p>{sub}</p>" if sub else ""
    return f'<section class="newsletter"><h2>{heading}</h2>{sub_html}</section>'


def _render_footer(props: dict, _ctx: RenderContext) -> str:
    return f'<footer class="site-footer">{_e(props.get("text"))}</footer>'


def _section_head(props: dict) -> str:
    """The shared eyebrow + heading block for list sections."""
    head = ""
    if props.get("eyebrow"):
        head += f'<p class="eyebrow">{_e(props.get("eyebrow"))}</p>'
    if props.get("heading"):
        head += f"<h2>{_e(props.get('heading'))}</h2>"
    return head


def _render_features(props: dict, _ctx: RenderContext) -> str:
    head = _section_head(props)
    cards = "".join(
        f'<div class="feature-card feature-card--{index % 3}">'
        f'<span class="feature-badge" aria-hidden="true"></span>'
        f"<div><h3>{_e(item.get('title'))}</h3><p>{_e(item.get('text'))}</p></div></div>"
        for index, item in enumerate(props.get("items", []))
    )
    return f'<section class="features">{head}<div class="feature-grid">{cards}</div></section>'


def _render_steps(props: dict, _ctx: RenderContext) -> str:
    head = _section_head(props)
    text = _e(props.get("text"))
    text_html = f"<p class='steps-text'>{text}</p>" if text else ""
    items = "".join(
        f'<li class="step-card"><span class="step-num">{index + 1}</span>'
        f"<div><h3>{_e(item.get('title'))}</h3><p>{_e(item.get('text'))}</p></div></li>"
        for index, item in enumerate(props.get("items", []))
    )
    return f'<section class="steps">{head}{text_html}<ol class="steps-list">{items}</ol></section>'


def _render_branches(props: dict, _ctx: RenderContext) -> str:
    head = _section_head(props)
    cards = ""
    for item in props.get("items", []):
        phone = item.get("phone")
        phone_html = (
            f'<a class="branch-phone" href="{_safe_url(f"tel:{phone}")}">{_e(phone)}</a>'
            if phone
            else ""
        )
        hours = _e(item.get("hours"))
        hours_html = f"<p class='branch-hours'>{hours}</p>" if hours else ""
        cards += (
            f'<div class="branch-card"><h3>{_e(item.get("name"))}</h3>'
            f"<p>{_e(item.get('address'))}</p>{phone_html}{hours_html}</div>"
        )
    return f'<section class="branches">{head}<div class="branch-grid">{cards}</div></section>'


class RendererRegistry:
    """Per-template renderer set. A template may override any section's markup
    (its CSS alone usually suffices — the reference templates override none);
    missing entries fall back to the base registry."""

    def __init__(self) -> None:
        self._renderers: dict[str, SectionRenderer] = {}

    def register(self, section_type: str, renderer: SectionRenderer) -> None:
        self._renderers[section_type] = renderer

    def render(self, section_type: str, props: dict, ctx: RenderContext) -> str:
        renderer = self._renderers.get(section_type) or _BASE_RENDERERS.get(section_type)
        if renderer is None:
            return ""
        return renderer(props, ctx)


_BASE_RENDERERS: dict[str, SectionRenderer] = {
    "hero": _render_hero,
    "rich_text": _render_rich_text,
    "image_text": _render_image_text,
    "product_grid": _render_product_grid,
    "collection_grid": _render_collection_grid,
    "testimonial": _render_testimonial,
    "faq": _render_faq,
    "cta": _render_cta,
    "newsletter": _render_newsletter,
    "footer": _render_footer,
    "features": _render_features,
    "steps": _render_steps,
    "branches": _render_branches,
}

_base_registry = RendererRegistry()

# Per-template overrides live here; a template id without an entry just uses
# the base registry. (The merchant templates will plug in here or via CSS.)
_TEMPLATE_REGISTRIES: dict[str, RendererRegistry] = {}


def _registry_for(template_id: str) -> RendererRegistry:
    return _TEMPLATE_REGISTRIES.get(template_id, _base_registry)


def render_style(theme_tokens: dict) -> str:
    if not theme_tokens:
        return ""
    variables = ";".join(f"--{_e(k)}:{_e(v)}" for k, v in theme_tokens.items())
    return f"<style>:root{{{variables}}}</style>"


def render_navigation(items: list[dict]) -> str:
    if not items:
        return ""
    links = "".join(
        f'<a href="{_safe_url(item.get("url"))}">{_e(item.get("label"))}</a>' for item in items
    )
    return f"<nav>{links}</nav>"


def _render_page(page: dict, reg: RendererRegistry, ctx: RenderContext) -> str:
    sections = "\n".join(
        reg.render(section.get("type", ""), section.get("props") or {}, ctx)
        for section in page.get("sections", [])
    )
    slug = str(page.get("slug") or "")
    # The home page's hero carries the document's h1; other pages get a header.
    header = "" if slug == "home" else f'<h2 class="page-title">{_e(page.get("title"))}</h2>'
    return f'<section class="site-page" id="page-{escape(slug)}">{header}{sections}</section>'


def render_website(snapshot: dict, ctx: RenderContext | None = None) -> str:
    """Render the published snapshot into a full HTML document.

    ``snapshot`` is the ``website_published_sites`` row as a dict: name,
    default_locale, template_id, theme_tokens, navigation and the projection
    (pages of validated sections).
    """
    ctx = ctx or RenderContext()
    template_id = str(snapshot.get("template_id") or "")
    reg = _registry_for(template_id)
    css = ""
    manifest = _manifest_for(template_id)
    if manifest is not None:
        css = manifest.css
    locale = str(snapshot.get("default_locale") or "ar")
    direction = "rtl" if locale.startswith("ar") else "ltr"

    name = _e(snapshot.get("name"))
    pages = snapshot.get("projection", {}).get("pages", [])
    nav_items = snapshot.get("navigation") or [
        {"label": p.get("title"), "url": f"#page-{p.get('slug')}"} for p in pages
    ]
    style = render_style(snapshot.get("theme_tokens") or {})
    nav = render_navigation(nav_items)
    body = "\n".join(_render_page(p, reg, ctx) for p in pages)
    return (
        "<!doctype html>"
        f'<html dir="{direction}" lang="{escape(locale)}">'
        f'<head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{name}</title>{style}"
        f"<style>{css}</style></head>"
        f'<body class="site-body"><header class="site-nav">'
        f'<span class="brand">{name}</span>{nav}</header>'
        f"<main>{body}</main></body></html>"
    )


def _manifest_for(template_id: str):
    """The template's CSS; a missing template (uninstalled after publish) must
    degrade to the base renderers with no CSS, never 500 a live site."""
    from app.modules.website.templates import catalog

    try:
        return catalog.get(template_id)
    except Exception:  # noqa: BLE001 - any catalog failure degrades, never raises
        return None

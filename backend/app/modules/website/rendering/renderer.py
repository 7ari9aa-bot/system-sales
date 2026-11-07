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


def _render_hero_paper(props: dict, _ctx: RenderContext) -> str:
    """Warm-paper hero: a paper card with dashed eyebrow pill, highlighted
    heading (the text after the last newline gets the marker underline), two
    CTAs, a note pill, a tilted photo frame, and the sage ticker strip."""
    eyebrow = _e(props.get("eyebrow"))
    # The seeded heading carries a newline; the trailing line is highlighted.
    parts = str(props.get("heading") or "").split("\n")
    heading_html = "<br />".join(
        _e(part) if index < len(parts) - 1 else f'<span class="story-mark">{_e(part)}</span>'
        for index, part in enumerate(parts)
    )
    sub = _e(props.get("subheading"))
    ctas = ""
    if props.get("cta_label") and props.get("cta_url"):
        url = _safe_url(props.get("cta_url"))
        if url and url != "#":
            ctas += (
                f'<a class="story-btn story-btn-1" href="{url}">{_e(props.get("cta_label"))}</a>'
            )
    if props.get("secondary_label") and props.get("secondary_url"):
        url = _safe_url(props.get("secondary_url"))
        if url and url != "#":
            label = _e(props.get("secondary_label"))
            ctas += f'<a class="story-btn story-btn-2" href="{url}">{label}</a>'
    note = _e(props.get("note"))
    note_html = f'<div class="story-note">{note}</div>' if note else ""
    image_html = '<div class="story-frame story-frame-empty" aria-hidden="true"></div>'
    if props.get("image"):
        url = _safe_url(props.get("image"))
        if url and url != "#":
            image_html = f'<div class="story-frame"><img src="{url}" alt=""></div>'
    ticker_items = props.get("ticker") or []
    ticker = ""
    if ticker_items:
        spans = "".join(
            f'<span class="story-tick">{_e(phrase)}<i aria-hidden="true">✳</i></span>'
            for phrase in ticker_items
        )
        ticker = (
            '<section class="story-ticker" aria-hidden="true">'
            f'<div class="story-ticker-row">{spans}{spans}</div></section>'
        )
    return (
        f'<section class="hero-paper">'
        f'<div class="story-paper story-paper-green">'
        f'<div class="hero-paper-grid">'
        f"<div>{f'<p class="eyebrow">{eyebrow}</p>' if eyebrow else ''}"
        f"<h1>{heading_html}</h1>"
        f"{f'<p class="hero-sub">{sub}</p>' if sub else ''}"
        f'<div class="hero-ctas">{ctas}</div>{note_html}</div>'
        f"<div>{image_html}</div>"
        f"</div></div>{ticker}</section>"
    )


def _render_features_paper(props: dict, _ctx: RenderContext) -> str:
    """Warm-paper features: items WITH hrefs render as chapter link cards
    (numbered, ink border, terracotta shadow); items without render as
    numbered promise cards on the sage band."""
    head = _section_head(props)
    items = props.get("items", [])
    if any(item.get("href") for item in items):
        cards = "".join(
            f'<a class="story-chap" href="{_safe_url(item.get("href"))}">'
            f'<span class="story-chap-img" aria-hidden="true"></span>'
            f'<span class="story-chap-body"><span class="story-chap-title">'
            f"{_e(item.get('title'))}</span>"
            f'<span class="story-chap-note">{_e(item.get("text"))}</span></span></a>'
            for item in items
        )
        return f'<section class="features">{head}<div class="chap-grid">{cards}</div></section>'
    cards = "".join(
        f'<div class="story-promise"><span class="story-pn">{index + 1:02d}</span>'
        f"<h3>{_e(item.get('title'))}</h3><p>{_e(item.get('text'))}</p></div>"
        for index, item in enumerate(items)
    )
    return f'<section class="features">{head}<div class="promise-grid">{cards}</div></section>'


def _render_steps_paper(props: dict, _ctx: RenderContext) -> str:
    head = _section_head(props)
    items = "".join(
        f'<li class="story-step"><span class="story-ghost">{index + 1:02d}</span>'
        f"<h3>{_e(item.get('title'))}</h3><p>{_e(item.get('text'))}</p></li>"
        for index, item in enumerate(props.get("items", []))
    )
    return (
        f'<section class="steps"><div class="story-paper story-paper-yellow">'
        f'{head}<ol class="step-grid">{items}</ol></div></section>'
    )


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


def _render_hero_poster(props: dict, _ctx: RenderContext) -> str:
    """Street-poster hero: the brick block with the ink-highlighted headline,
    two poster buttons, the gift pill, the rotated ink frame, the black stats
    strip, and the ink ticker."""
    eyebrow = _e(props.get("eyebrow"))
    parts = str(props.get("heading") or "").split("\n")
    heading_html = "<br />".join(
        _e(part) if index < len(parts) - 1 else f"<span>{_e(part)}</span>"
        for index, part in enumerate(parts)
    )
    sub = _e(props.get("subheading"))
    ctas = ""
    if props.get("cta_label") and props.get("cta_url"):
        url = _safe_url(props.get("cta_url"))
        if url and url != "#":
            ctas += f'<a class="b b1" href="{url}">{_e(props.get("cta_label"))}</a>'
    if props.get("secondary_label") and props.get("secondary_url"):
        url = _safe_url(props.get("secondary_url"))
        if url and url != "#":
            label = _e(props.get("secondary_label"))
            ctas += f'<a class="b b2" href="{url}">{label}</a>'
    note = _e(props.get("note"))
    note_html = f'<div class="gift">★ {note}</div>' if note else ""
    image_html = '<div class="fr-img fr-img-empty"></div>'
    if props.get("image"):
        url = _safe_url(props.get("image"))
        if url and url != "#":
            image_html = f'<img class="fr-img" src="{url}" alt="">'
    stats = props.get("stats") or []
    stats_html = ""
    if stats:
        cells = "".join(
            f'<div class="st"><b>{_e(st.get("value"))}</b><span>{_e(st.get("label"))}</span></div>'
            for st in stats
        )
        stats_html = f'<dl class="stats">{cells}</dl>'
    ticker_items = props.get("ticker") or []
    ticker = ""
    if ticker_items:
        spans = "".join(
            f'<span>{_e(phrase)}<i aria-hidden="true">✳</i></span>' for phrase in ticker_items
        )
        ticker = (
            '<section class="tick" aria-hidden="true">'
            f'<div class="tk"><div class="tg">{spans}</div><div class="tg">{spans}</div></div>'
            "</section>"
        )
    return (
        '<section class="poster-hero">'
        '<section class="blk"><div class="hero"><div>'
        f"{f'<span class="eb">{eyebrow}</span>' if eyebrow else ''}"
        f"<h1>{heading_html}</h1>"
        f"{f'<p class="lead">{sub}</p>' if sub else ''}"
        f'<div class="btns">{ctas}</div>{note_html}'
        f"</div><div><div class="
        rf">{image_html}</div></div>"
        f"</div></section>{stats_html}{ticker}</section>"
    )


def _render_features_poster(props: dict, _ctx: RenderContext) -> str:
    """Poster features: href items become the giant-number ROWS; href-less
    items become the numbered columns on the olive promise block."""
    head = _section_head_poster(props)
    items = props.get("items", [])
    if any(item.get("href") for item in items):
        rows = "".join(
            f'<a class="row" href="{_safe_url(item.get("href"))}">'
            f'<span class="n">{index + 1:02d}</span>'
            f"<h3>{_e(item.get('title'))}<small>{_e(item.get('text'))}</small></h3>"
            f'<span class="row-img" aria-hidden="true"></span></a>'
            for index, item in enumerate(items)
        )
        return f'<section class="poster-sec">{head}<div class="rows">{rows}</div></section>'
    cols = "".join(
        f'<div class="col"><span class="pn">{index + 1:02d}</span>'
        f"<h3>{_e(item.get('title'))}</h3><p>{_e(item.get('text'))}</p></div>"
        for index, item in enumerate(items)
    )
    return f'<section class="poster-pro">{head}<div class="cols">{cols}</div></section>'


def _render_steps_poster(props: dict, _ctx: RenderContext) -> str:
    head = _section_head_poster(props)
    items = "".join(
        f'<li class="sp"><span class="big">{index + 1:02d}</span>'
        f"<h3>{_e(item.get('title'))}</h3><p>{_e(item.get('text'))}</p></li>"
        for index, item in enumerate(props.get("items", []))
    )
    return f'<section class="poster-path">{head}<ol class="psteps">{items}</ol></section>'


def _section_head_poster(props: dict) -> str:
    """The poster head: eyebrow chip + oversized heading, with the trailing
    line rendered on an ink block when the heading carries a newline."""
    head = ""
    if props.get("eyebrow"):
        head += f'<span class="eb2">{_e(props.get("eyebrow"))}</span>'
    if props.get("heading"):
        parts = str(props.get("heading")).split("\n")
        heading_html = "<br />".join(
            _e(part) if index < len(parts) - 1 else f"<em>{_e(part)}</em>"
            for index, part in enumerate(parts)
        )
        head += f"<h2>{heading_html}</h2>"
    if props.get("text"):
        head += f'<p class="sh-lead">{_e(props.get("text"))}</p>'
    return head


def _register_poster_overrides() -> None:
    """The street-poster template renders hero, features and steps with
    poster markup; everything else rides the base renderers + CSS."""
    registry = RendererRegistry()
    registry.register("hero", _render_hero_poster)
    registry.register("features", _render_features_poster)
    registry.register("steps", _render_steps_poster)
    _TEMPLATE_REGISTRIES["street-poster"] = registry


_register_poster_overrides()


def _register_funny_baby_verbatim() -> None:
    """Funny Baby renders 1:1 from the merchant's source markup: a custom
    shell (their header/footer/whatsapp) plus a section dispatch to their
    exact components."""
    registry = RendererRegistry()

    def dispatch(kind, props, ctx):
        from app.modules.website.templates import funny_baby_verbatim as vb

        return vb.render_section_funny_baby(kind, props, ctx)

    def shell(**kwargs):
        from app.modules.website.templates import funny_baby_verbatim as vb

        return vb.render_shell_funny_baby(**kwargs)

    registry.dispatch_fn = dispatch
    registry.shell_fn = shell
    _TEMPLATE_REGISTRIES["funny-baby"] = registry


_register_funny_baby_verbatim()


def _register_warm_paper_verbatim() -> None:
    """Warm-paper renders 1:1 from the v3 source: their story-paper chrome
    and components via the verbatim module."""
    registry = RendererRegistry()

    def dispatch(kind, props, ctx):
        from app.modules.website.templates import warm_paper_verbatim as wp

        return wp.render_section_warm_paper(kind, props, ctx)

    def shell(**kwargs):
        from app.modules.website.templates import warm_paper_verbatim as wp

        return wp.render_shell_warm_paper(**kwargs)

    registry.dispatch_fn = dispatch
    registry.shell_fn = shell
    _TEMPLATE_REGISTRIES["warm-paper"] = registry


_register_warm_paper_verbatim()


def _register_street_poster_verbatim() -> None:
    """Street-poster renders 1:1 from the v4 source: their poster blocks via
    the verbatim module."""
    registry = RendererRegistry()

    def dispatch(kind, props, ctx):
        from app.modules.website.templates import street_poster_verbatim as sp

        return sp.render_section_street_poster(kind, props, ctx)

    def shell(**kwargs):
        from app.modules.website.templates import street_poster_verbatim as sp

        return sp.render_shell_street_poster(**kwargs)

    registry.dispatch_fn = dispatch
    registry.shell_fn = shell
    _TEMPLATE_REGISTRIES["street-poster"] = registry


_register_street_poster_verbatim()


def _register_paper_overrides() -> None:
    """The street-poster template renders its hero, feature rows and path
    steps with bespoke poster markup; everything else is CSS-only on the
    base renderers. (Warm-paper is now verbatim — see above.)"""
    registry = RendererRegistry()
    registry.register("hero", _render_hero_paper)
    registry.register("features", _render_features_paper)
    registry.register("steps", _render_steps_paper)
    _TEMPLATE_REGISTRIES["street-poster"] = registry


_register_paper_overrides()


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


def render_website(
    snapshot: dict,
    ctx: RenderContext | None = None,
    *,
    page_slug: str | None = None,
    page_url_prefix: str | None = None,
    banner_html: str | None = None,
) -> str:
    """Render the published snapshot into a full HTML document.

    ``snapshot`` is the ``website_published_sites`` row as a dict: name,
    default_locale, template_id, theme_tokens, navigation and the projection
    (pages of validated sections).

    ``page_slug`` renders ONE page of the projection instead of the whole
    document (the preview-walk mode); with ``page_url_prefix`` set, the
    auto-navigation links become real per-page URLs
    (``{prefix}/{page-slug}``) instead of same-document anchors, so a visitor
    clicks through the site like a real multi-page website. ``banner_html``
    (preview mode only) is injected right after ``<body>``.
    """
    ctx = ctx or RenderContext()
    template_id = str(snapshot.get("template_id") or "")
    reg = _registry_for(template_id)
    dispatch_fn = getattr(reg, "dispatch_fn", None)
    shell_fn = getattr(reg, "shell_fn", None)
    css = ""
    manifest = _manifest_for(template_id)
    if manifest is not None:
        css = manifest.css
    locale = str(snapshot.get("default_locale") or "ar")
    direction = "rtl" if locale.startswith("ar") else "ltr"

    name = _e(snapshot.get("name"))
    pages = snapshot.get("projection", {}).get("pages", [])

    def _page_url(slug: Any) -> str:
        if page_url_prefix:
            return f"{page_url_prefix}/{slug}"
        return f"#page-{slug}"

    nav_items = snapshot.get("navigation") or [
        {"label": p.get("title"), "url": _page_url(p.get("slug"))} for p in pages
    ]
    style = render_style(snapshot.get("theme_tokens") or {})
    nav = render_navigation(nav_items)

    def _page_html(p):
        if dispatch_fn is not None:
            return "\n".join(
                dispatch_fn(s.get("type", ""), s.get("props") or {}, ctx)
                for s in p.get("sections", [])
            )
        return _render_page(p, reg, ctx)

    if page_slug is not None:
        rendered = [p for p in pages if str(p.get("slug") or "") == page_slug]
        body = "\n".join(_page_html(p) for p in rendered)
    else:
        body = "\n".join(_page_html(p) for p in pages)

    title = name
    if page_slug is not None and rendered:
        title = f"{rendered[0].get('title')} — {name}"

    if shell_fn is not None:
        return shell_fn(
            body=body,
            title=title,
            page_slug=page_slug,
            page_url_prefix=page_url_prefix,
            banner_html=banner_html,
            site_slug=snapshot.get("slug"),
        )
    return (
        "<!doctype html>"
        f'<html dir="{direction}" lang="{escape(locale)}">'
        f'<head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title>{style}"
        f"<style>{css}</style></head>"
        f'<body class="site-body">{banner_html or ""}'
        f'<header class="site-nav">'
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

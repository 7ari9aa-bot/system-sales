"""The website template catalog.

A template is a MANIFEST: identity (ar/en names + descriptions), a default
price (snapshotted onto the purchase), theme tokens, page presets (pages of
declarative sections) and the template's CSS. Selecting one seeds the
merchant's website content — everything stays editable afterwards.

Registration is FAIL-CLOSED: every preset section is validated against the
section registry at import time, so a template with a typo in its props breaks
the boot (like the AI agent registry), never a live site.

Adding a template = a new module under ``templates/`` that builds a
``TemplateManifest`` and hands it to ``register_all`` in ``reference/__init__``
(or its own package) — no core change. The 20 merchant templates will arrive
as exactly such folders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.modules.website.errors import TemplateNotFoundError
from app.modules.website.sections import registry as section_registry


@dataclass(frozen=True)
class TemplateSection:
    type: str
    props: dict


@dataclass(frozen=True)
class TemplatePage:
    title: str
    slug: str
    sections: tuple[TemplateSection, ...] = ()


@dataclass(frozen=True)
class TemplateManifest:
    id: str
    name: str
    name_ar: str
    description: str
    description_ar: str
    price: Decimal
    css: str = ""
    theme_tokens: dict = field(default_factory=dict)
    pages: tuple[TemplatePage, ...] = ()
    # Frontend asset path for the gallery card (bundled by the web app).
    preview_image: str = ""
    # Sample products shown on the template's live preview walk
    # (/sites/preview/<id>): themed demo items so the product grids read
    # like a real store before the merchant buys. Empty = the generic set.
    demo_products: tuple[dict, ...] = ()


class WebsiteTemplateCatalog:
    def __init__(self) -> None:
        self._templates: dict[str, TemplateManifest] = {}

    def register(self, manifest: TemplateManifest) -> None:
        if manifest.id in self._templates:
            raise ValueError(f"template already registered: {manifest.id!r}")
        if not manifest.pages:
            raise ValueError(f"template {manifest.id!r} has no page presets")
        for page in manifest.pages:
            if not page.title or not page.slug:
                raise ValueError(f"template {manifest.id!r} has a page preset without title/slug")
            for section in page.sections:
                # Fail-closed at import: bad template props break the boot,
                # never a live site (same contract as the AI agent registry).
                section_registry.validate(section.type, section.props)
        self._templates[manifest.id] = manifest

    def get(self, template_id: str) -> TemplateManifest:
        try:
            return self._templates[template_id]
        except KeyError:
            raise TemplateNotFoundError(template_id) from None

    def has(self, template_id: str) -> bool:
        return template_id in self._templates

    def list(self) -> tuple[TemplateManifest, ...]:
        return tuple(self._templates.values())


catalog = WebsiteTemplateCatalog()

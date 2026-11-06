"""Declarative section system (ported from the website-builder spec).

Sections are declarative components — NOT raw HTML. A section is described by
a ``SectionSpec`` (type, version, a pydantic props model) and the renderer
decides how to display it. New sections register without touching the website
core; publish-time validation runs every section's props through its schema,
so the stored props are always the normalized form the renderer can trust.

Product/collection sections hold REFERENCES to business truth
(``collection_id``), never a copy — the public renderer fetches live products
through the boundary-safe metadata-table read at request time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, get_args, get_origin

from pydantic import BaseModel, Field, ValidationError

from app.modules.website.errors import InvalidSection


class SectionProps(BaseModel):
    """Base model for all section props."""

    model_config = {"extra": "forbid"}


class HeroProps(SectionProps):
    heading: str
    subheading: str | None = None
    image: str | None = None
    cta_label: str | None = None
    cta_url: str | None = None
    # Additive v2 fields: the base renderer ignores them; richer templates
    # (warm-paper) use the eyebrow pill, the secondary CTA, the note pill
    # and the ticker strip.
    eyebrow: str | None = None
    secondary_label: str | None = None
    secondary_url: str | None = None
    note: str | None = None
    ticker: list[str] | None = None
    # Poster-style stats strip under the hero ({"value": "S – XXL",
    # "label": "المقاسات"}); a list of dicts, so it stays out of the v1
    # editor and is seeded by the template.
    stats: list[dict[str, str]] | None = None


class RichTextProps(SectionProps):
    content: str


class ImageTextProps(SectionProps):
    # Optional: the renderer degrades to a text-only block when absent.
    image: str | None = None
    heading: str
    text: str
    image_side: str = Field(default="left", pattern="^(left|right)$")


class ProductGridProps(SectionProps):
    collection_id: str  # business reference — NOT a copy of product truth
    title: str | None = None
    limit: int = Field(default=12, ge=1, le=100)
    columns: int = Field(default=4, ge=1, le=6)


class CollectionGridProps(SectionProps):
    collection_ids: list[str] = Field(min_length=1)
    columns: int = Field(default=3, ge=1, le=6)


class TestimonialProps(SectionProps):
    quote: str
    author: str
    role: str | None = None


class FaqItemProps(BaseModel):
    model_config = {"extra": "forbid"}

    q: str
    a: str


class FaqProps(SectionProps):
    items: list[FaqItemProps] = Field(min_length=1)


class CtaProps(SectionProps):
    heading: str
    subheading: str | None = None
    button_label: str
    button_url: str


class NewsletterProps(SectionProps):
    heading: str = "Stay in touch"
    subheading: str | None = None


class FooterProps(SectionProps):
    text: str | None = None


class FeatureItemProps(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    text: str
    # Optional link target (page anchor or allowlisted URL): when present the
    # item renders as a link card (warm-paper chapters), else as a plain card.
    href: str | None = None


class FeaturesProps(SectionProps):
    """A strip of feature/promise cards (the funny-baby PromiseStrip shape)."""

    eyebrow: str | None = None
    heading: str | None = None
    text: str | None = None
    items: list[FeatureItemProps] = Field(min_length=1, max_length=6)


class StepsProps(SectionProps):
    """A numbered how-it-works block: sticky intro + numbered step cards."""

    eyebrow: str | None = None
    heading: str | None = None
    text: str | None = None
    items: list[FeatureItemProps] = Field(min_length=1, max_length=8)


class BranchItemProps(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    address: str
    phone: str | None = None
    hours: str | None = None


class BranchesProps(SectionProps):
    """Store-branch cards. V1 the branches are editor-managed props; binding
    them to live tenant data is a later slice."""

    eyebrow: str | None = None
    heading: str | None = None
    items: list[BranchItemProps] = Field(min_length=1, max_length=12)


@dataclass(frozen=True)
class SectionSpec:
    type: str
    version: int
    props_model: type[SectionProps]

    def validate(self, props: dict) -> SectionProps:
        try:
            return self.props_model.model_validate(props)
        except ValidationError as exc:
            raise InvalidSection(self.type, str(exc)) from exc

    def field_schema(self) -> list[dict[str, Any]]:
        """Field metadata for the dashboard's generic content editor.

        Scalars (str/int) and ONE-LEVEL lists of flat sub-models (faq q/a,
        feature cards, branch cards) are editable; anything deeper (lists of
        scalars, nested dicts) stays out of the v1 editor.
        """
        fields: list[dict[str, Any]] = []
        for name, info in self.props_model.model_fields.items():
            base = _unwrap_optional(info.annotation)
            if get_origin(base) is list:
                list_schema = _list_field_schema(base)
                if list_schema is not None:
                    fields.append(
                        {
                            "name": name,
                            "type": "list",
                            "required": info.is_required(),
                            **list_schema,
                        }
                    )
                continue
            if base is str:
                kind = "string"
            elif base is int:
                kind = "number"
            else:
                continue
            fields.append({"name": name, "type": kind, "required": info.is_required()})
        return fields


def _unwrap_optional(annotation: Any) -> Any:
    args = get_args(annotation)
    if args and type(None) in args:
        return next(a for a in args if a is not type(None))
    return annotation


def _list_field_schema(list_annotation: Any) -> dict[str, Any] | None:
    """The item-field metadata for a ``list[SubModel]`` annotation, or None
    when the list's items are not flat, editor-friendly sub-models."""
    args = get_args(list_annotation)
    if not args or not (isinstance(args[0], type) and issubclass(args[0], BaseModel)):
        return None
    item_fields: list[dict[str, Any]] = []
    for fname, finfo in args[0].model_fields.items():
        fbase = _unwrap_optional(finfo.annotation)
        if fbase is str:
            kind = "string"
        elif fbase is int:
            kind = "number"
        else:
            return None  # a nested structure inside the item — not v1-editable
        item_fields.append({"name": fname, "type": kind, "required": finfo.is_required()})
    return {"item_fields": item_fields}


class SectionRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, SectionSpec] = {}

    def register(self, spec: SectionSpec) -> None:
        self._specs[spec.type] = spec

    def get(self, section_type: str) -> SectionSpec:
        try:
            return self._specs[section_type]
        except KeyError:
            raise InvalidSection(section_type, f"unknown section type: {section_type}") from None

    def has(self, section_type: str) -> bool:
        return section_type in self._specs

    def specs(self) -> tuple[SectionSpec, ...]:
        return tuple(self._specs.values())

    def validate(self, section_type: str, props: dict) -> SectionProps:
        return self.get(section_type).validate(props)

    def types(self) -> tuple[str, ...]:
        return tuple(self._specs)


def build_default_registry() -> SectionRegistry:
    reg = SectionRegistry()
    for spec in (
        SectionSpec("hero", 1, HeroProps),
        SectionSpec("rich_text", 1, RichTextProps),
        SectionSpec("image_text", 1, ImageTextProps),
        SectionSpec("product_grid", 1, ProductGridProps),
        SectionSpec("collection_grid", 1, CollectionGridProps),
        SectionSpec("testimonial", 1, TestimonialProps),
        SectionSpec("faq", 1, FaqProps),
        SectionSpec("cta", 1, CtaProps),
        SectionSpec("newsletter", 1, NewsletterProps),
        SectionSpec("footer", 1, FooterProps),
        SectionSpec("features", 1, FeaturesProps),
        SectionSpec("steps", 1, StepsProps),
        SectionSpec("branches", 1, BranchesProps),
    ):
        reg.register(spec)
    return reg


registry = build_default_registry()

"""The in-house website builder: purchase lifecycle, publish invariants,
the public read model, and tenant isolation on the new tables.

The behaviors pinned here are the ones a regression would hurt real merchants:

1. **Purchase state machine** — one open purchase / one live website per
   tenant, the price snapshotted from the template manifest (a manifest price
   change must never rewrite a submitted purchase), slug rules enforced
   (reserved names, cross-tenant claims, freed by rejection).
2. **Activation = confirmation** — admin confirmation creates the website
   from the template AND publishes it AND writes the public snapshot AND
   stages the events, all in one transaction.
3. **A failed publish never breaks the live site** — the spec's core
   invariant, re-proven on the ORM: validation refuses BEFORE any mutation
   and the snapshot keeps serving the old version.
4. **The public surface serves only published snapshots** — draft edits never
   leak, and the renderer escapes hostile markup and URLs.
5. **Tenancy twice** — application-layer filters AND real RLS row hiding
   (skipped loudly when the connected role bypasses RLS).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.core.events.schemas import build_envelope
from app.modules.identity.deps import AuthedUser, TenantContext
from app.modules.identity.models import Tenant
from app.modules.website import models as ws
from app.modules.website.errors import (
    NoDraftError,
    PublishValidationFailed,
    PurchaseStateError,
    RollbackNotAllowed,
    SlugReservedError,
    SlugUnavailableError,
    WebsiteDomainError,
)
from app.modules.website.rendering import RenderContext, render_website
from app.modules.website.services import content_service, public_service, purchase_service
from app.modules.website.services.publishing_service import publish, rollback
from app.modules.website.slugs import validate_slug
from app.modules.website.templates import catalog


def _ctx(db: AsyncSession, tenant_ctx) -> TenantContext:
    return TenantContext(
        session=db,
        user=AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes=set(),
    )


async def _foreign_tenant(db: AsyncSession) -> uuid.UUID:
    """A second tenant, bound as the current RLS subject on return."""
    other = Tenant(slug=f"wb-{uuid.uuid4().hex[:10]}", name="Website Stranger")
    db.add(other)
    await db.flush()
    return other.id


async def _rls_is_bypassed(db: AsyncSession) -> bool:
    probe = await db.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"))
    return bool(probe.scalar())


async def _outbox_types(db: AsyncSession, aggregate_id: uuid.UUID) -> set[str]:
    rows = await db.execute(
        text("SELECT payload->>'event_type' FROM outbox_events WHERE aggregate_id = :id"),
        {"id": aggregate_id},
    )
    return {r[0] for r in rows}


async def _create_purchase(db: AsyncSession, tenant_ctx, *, slug: str | None = None):
    return await purchase_service.create(
        db,
        _ctx(db, tenant_ctx),
        template_id="general-commerce",
        site_name="متجر التجارب",
        slug=slug or f"shop-{uuid.uuid4().hex[:8]}",
    )


# ------------------------------------------------------------ purchase ----


async def test_a_purchase_snapshots_the_manifest_price(db: AsyncSession, tenant_ctx) -> None:
    purchase = await _create_purchase(db, tenant_ctx)
    manifest = catalog.get("general-commerce")
    assert purchase.status == "pending_payment"
    assert purchase.price == manifest.price == Decimal("1500.00")
    assert purchase.currency == "EGP"
    # A later manifest price change must never rewrite a submitted purchase.
    assert "website.purchase.created" in await _outbox_types(db, purchase.id)


async def test_a_second_open_purchase_is_refused(db: AsyncSession, tenant_ctx) -> None:
    await _create_purchase(db, tenant_ctx)
    with pytest.raises(PurchaseStateError):
        await _create_purchase(db, tenant_ctx, slug="another-shop")


async def test_an_existing_website_blocks_a_new_purchase(db: AsyncSession, tenant_ctx) -> None:
    db.add(
        ws.Website(
            tenant_id=tenant_ctx.tenant_id,
            name="Already Here",
            slug=f"existing-{uuid.uuid4().hex[:8]}",
            template_id="general-commerce",
        )
    )
    await db.flush()
    with pytest.raises(PurchaseStateError):
        await _create_purchase(db, tenant_ctx)


async def test_reserved_and_malformed_slugs_are_refused(db: AsyncSession, tenant_ctx) -> None:
    with pytest.raises(SlugReservedError):
        await _create_purchase(db, tenant_ctx, slug="api")
    with pytest.raises(WebsiteDomainError):
        await _create_purchase(db, tenant_ctx, slug="ab")


async def test_an_arabic_only_name_needs_an_explicit_slug(db: AsyncSession, tenant_ctx) -> None:
    with pytest.raises(WebsiteDomainError):
        await purchase_service.create(
            db,
            _ctx(db, tenant_ctx),
            template_id="general-commerce",
            site_name="متجري الجميل",
        )


async def test_a_taken_slug_is_refused_and_freed_by_rejection(db: AsyncSession, tenant_ctx) -> None:
    purchase = await _create_purchase(db, tenant_ctx, slug="claimed-shop")
    other_id = await _foreign_tenant(db)
    await bind_tenant(db, other_id)

    other_ctx = TenantContext(
        session=db,
        user=AuthedUser(id=uuid.uuid4(), tenant_id=other_id, role_code="owner"),
        tenant_id=other_id,
        role_code="owner",
        permission_codes=set(),
    )
    with pytest.raises(SlugUnavailableError):
        await purchase_service.create(
            db,
            other_ctx,
            template_id="restaurant",
            site_name="Stranger Shop",
            slug=purchase.slug,
        )

    # Rejection frees the slug: the stranger can claim it now. (reject()
    # re-binds the session to the PURCHASE's tenant — that is how the admin
    # path works — so the stranger binds their own tenant back first.)
    await purchase_service.reject(
        db, purchase_id=purchase.id, confirmed_by_user_id=tenant_ctx.user.id
    )
    await bind_tenant(db, other_id)
    reclaimed = await purchase_service.create(
        db, other_ctx, template_id="restaurant", site_name="Stranger Shop", slug=purchase.slug
    )
    assert reclaimed.slug == purchase.slug


# ------------------------------------------------ confirmation/activation ----


async def test_confirm_activates_and_publishes_in_one_transaction(
    db: AsyncSession, tenant_ctx
) -> None:
    purchase = await _create_purchase(db, tenant_ctx, slug="activated-shop")
    result = await purchase_service.confirm(
        db, purchase_id=purchase.id, confirmed_by_user_id=tenant_ctx.user.id
    )
    website = (
        await db.execute(select(ws.Website).where(ws.Website.id == uuid.UUID(result["website_id"])))
    ).scalar_one()
    assert website.status == "published"
    assert website.slug == "activated-shop"

    version = (
        await db.execute(
            select(ws.WebsiteVersion).where(ws.WebsiteVersion.id == website.published_version_id)
        )
    ).scalar_one()
    assert version.status == "published"
    pages = (
        (await db.execute(select(ws.WebsitePage).where(ws.WebsitePage.version_id == version.id)))
        .scalars()
        .all()
    )
    assert len(pages) >= 1
    sections = (
        (
            await db.execute(
                select(ws.WebsitePageSection).where(ws.WebsitePageSection.page_id == pages[0].id)
            )
        )
        .scalars()
        .all()
    )
    assert len(sections) >= 1

    snapshot = (
        await db.execute(
            select(ws.WebsitePublishedSite).where(ws.WebsitePublishedSite.website_id == website.id)
        )
    ).scalar_one()
    assert snapshot.is_active is True
    assert snapshot.projection["pages"][0]["sections"][0]["props"]  # normalized, non-empty

    events = await _outbox_types(db, purchase.id)
    assert {"website.purchase.created", "website.purchase.confirmed"} <= events
    assert "website.published" in await _outbox_types(db, website.id)

    # A second confirm attempt is refused (the purchase is no longer pending).
    with pytest.raises(PurchaseStateError):
        await purchase_service.confirm(
            db, purchase_id=purchase.id, confirmed_by_user_id=tenant_ctx.user.id
        )


# ------------------------------------------------------- publish invariants ----


async def _activated_website(db: AsyncSession, tenant_ctx) -> tuple[ws.Website, TenantContext]:
    purchase = await _create_purchase(db, tenant_ctx, slug=f"shop-{uuid.uuid4().hex[:8]}")
    await purchase_service.confirm(
        db, purchase_id=purchase.id, confirmed_by_user_id=tenant_ctx.user.id
    )
    website = (
        await db.execute(
            select(ws.Website).where(
                ws.Website.tenant_id == tenant_ctx.tenant_id, ws.Website.status != "deleted"
            )
        )
    ).scalar_one()
    return website, _ctx(db, tenant_ctx)


async def _snapshot(db: AsyncSession, website_id: uuid.UUID) -> ws.WebsitePublishedSite:
    return (
        await db.execute(
            select(ws.WebsitePublishedSite).where(ws.WebsitePublishedSite.website_id == website_id)
        )
    ).scalar_one()


async def test_a_failed_publish_keeps_the_previous_version_live(
    db: AsyncSession, tenant_ctx
) -> None:
    website, ctx = await _activated_website(db, tenant_ctx)
    published_before = website.published_version_id
    snapshot_before = (await _snapshot(db, website.id)).projection

    content = await content_service.get_content(db, ctx)
    hero = next(
        section
        for page in content["published"]["pages"]
        for section in page["sections"]
        if section["type"] == "hero"
    )
    edited = await content_service.update_section(
        db, ctx, section_id=uuid.UUID(hero["id"]), props={"heading": "عنوان جديد"}
    )
    assert edited["cloned"] is True

    # Corrupt the DRAFT section only: the live version and snapshot must not move.
    draft_section = (
        await db.execute(
            select(ws.WebsitePageSection).where(
                ws.WebsitePageSection.id == uuid.UUID(edited["section_id"])
            )
        )
    ).scalar_one()
    draft_section.props = {"heading": None, "bogus_field": "x"}
    await db.flush()

    with pytest.raises(PublishValidationFailed):
        await publish(db, tenant_id=ctx.tenant_id, website_id=website.id)

    website = (await db.execute(select(ws.Website).where(ws.Website.id == website.id))).scalar_one()
    assert website.published_version_id == published_before
    assert (await _snapshot(db, website.id)).projection == snapshot_before


async def test_publishing_with_no_draft_is_a_structured_no(db: AsyncSession, tenant_ctx) -> None:
    website, ctx = await _activated_website(db, tenant_ctx)
    with pytest.raises(NoDraftError):
        await publish(db, tenant_id=ctx.tenant_id, website_id=website.id)


async def test_rollback_repoints_and_refreshes_the_snapshot(db: AsyncSession, tenant_ctx) -> None:
    website, ctx = await _activated_website(db, tenant_ctx)
    v1 = website.published_version_id

    content = await content_service.get_content(db, ctx)
    hero = next(
        section
        for page in content["published"]["pages"]
        for section in page["sections"]
        if section["type"] == "hero"
    )
    await content_service.update_section(
        db, ctx, section_id=uuid.UUID(hero["id"]), props={"heading": "الإصدار الثاني"}
    )
    await publish(db, tenant_id=ctx.tenant_id, website_id=website.id)
    website = (await db.execute(select(ws.Website).where(ws.Website.id == website.id))).scalar_one()
    v2 = website.published_version_id
    assert v2 != v1
    assert (await _snapshot(db, website.id)).projection["version_id"] == str(v2)

    await rollback(db, tenant_id=ctx.tenant_id, website_id=website.id, version_id=v1)
    assert (await _snapshot(db, website.id)).projection["version_id"] == str(v1)

    with pytest.raises(RollbackNotAllowed):
        await rollback(db, tenant_id=ctx.tenant_id, website_id=website.id, version_id=v1)


# ---------------------------------------------------------- content edits ----


async def test_identity_edits_reach_the_public_snapshot_immediately(
    db: AsyncSession, tenant_ctx
) -> None:
    website, ctx = await _activated_website(db, tenant_ctx)
    await content_service.update_identity(
        db, ctx, name="الاسم الجديد", theme_tokens={"primary": "#123456"}
    )
    snapshot = await _snapshot(db, website.id)
    assert snapshot.name == "الاسم الجديد"
    assert snapshot.theme_tokens["primary"] == "#123456"
    assert snapshot.projection["name"] == "الاسم الجديد"


async def test_a_draft_edit_never_touches_the_public_snapshot(db: AsyncSession, tenant_ctx) -> None:
    website, ctx = await _activated_website(db, tenant_ctx)
    content = await content_service.get_content(db, ctx)
    hero = next(
        section
        for page in content["published"]["pages"]
        for section in page["sections"]
        if section["type"] == "hero"
    )
    before = (await _snapshot(db, website.id)).projection
    await content_service.update_section(
        db, ctx, section_id=uuid.UUID(hero["id"]), props={"heading": "مسودة"}
    )
    assert (await _snapshot(db, website.id)).projection == before


def test_the_editor_schema_comes_from_the_registry() -> None:
    schema = {s["type"]: s for s in content_service.editor_schema()}
    hero_fields = {f["name"]: f for f in schema["hero"]["fields"]}
    assert hero_fields["heading"]["required"] is True
    assert hero_fields["subheading"]["required"] is False
    # Scalars stay scalar; flat sub-model lists now expose their item fields.
    faq = next(f for f in schema["faq"]["fields"] if f["name"] == "items")
    assert faq["type"] == "list"
    assert {f["name"] for f in faq["item_fields"]} == {"q", "a"}
    # A list of scalars (collection_ids) never reaches the editor.
    product_fields = {f["name"] for f in schema["product_grid"]["fields"]}
    assert "collection_ids" not in product_fields
    assert all(
        f["type"] in {"string", "number", "list"} for s in schema.values() for f in s["fields"]
    )


# ------------------------------------------------------------ public side ----


async def test_the_public_surface_serves_only_published_snapshots(
    db: AsyncSession, tenant_ctx
) -> None:
    website, _ = await _activated_website(db, tenant_ctx)
    site = await public_service.load_snapshot(db, slug=website.slug)
    assert site is not None and site.is_active is True
    assert await public_service.load_snapshot(db, slug="no-such-shop") is None

    html = await public_service.render_html(db, site)
    assert html.startswith("<!doctype html>")
    assert 'dir="rtl"' in html


async def test_the_renderer_escapes_and_blocks_hostile_urls() -> None:
    snapshot = {
        "name": "متجر <script>alert(1)</script>",
        "default_locale": "ar",
        "template_id": "general-commerce",
        "theme_tokens": {"primary": "#0f172a"},
        "navigation": [],
        "projection": {
            "pages": [
                {
                    "id": "1",
                    "title": "x",
                    "slug": "home",
                    "sections": [
                        {
                            "type": "hero",
                            "props": {
                                "heading": "<script>alert(1)</script>",
                                "cta_label": "اضغط",
                                "cta_url": "javascript:alert(1)",
                            },
                        },
                        {"type": "totally_unknown", "props": {"x": 1}},
                    ],
                }
            ]
        },
    }
    html = render_website(snapshot, RenderContext())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    # javascript: never survives: the cta renders with NO anchor at all
    # (inert by omission — the only other anchors are the #page-* nav ones),
    # and the unknown section renders empty.
    assert "javascript:" not in html
    assert 'href="#"' not in html
    assert "totally_unknown" not in html


async def test_public_product_grid_renders_without_products(db: AsyncSession, tenant_ctx) -> None:
    """A store with an empty catalog renders a live (empty) grid — never 500s."""
    website, _ = await _activated_website(db, tenant_ctx)
    site = await public_service.load_snapshot(db, slug=website.slug)
    html = await public_service.render_html(db, site)
    assert "product-grid" in html


# ----------------------------------------------------------- isolation ----


async def test_rls_hides_website_rows_from_a_stranger(db: AsyncSession, tenant_ctx) -> None:
    website, _ = await _activated_website(db, tenant_ctx)
    other_id = await _foreign_tenant(db)
    await bind_tenant(db, other_id)
    assert (
        await db.execute(select(ws.Website).where(ws.Website.id == website.id))
    ).scalar_one_or_none() is None
    assert (
        await db.execute(
            select(ws.WebsitePurchase).where(ws.WebsitePurchase.tenant_id == website.tenant_id)
        )
    ).scalars().all() == []


async def test_the_admin_definers_expose_only_their_minimal_surface(
    db: AsyncSession, tenant_ctx
) -> None:
    purchase = await _create_purchase(db, tenant_ctx, slug="admin-probe")

    taken = (
        await db.execute(text("SELECT public.website_slug_taken(:s)"), {"s": purchase.slug})
    ).scalar()
    assert taken is True

    # The queue reads cross-tenant WITHOUT any tenant binding.
    unbound_rows = (
        await db.execute(text("SELECT tenant_id, slug FROM public.admin_website_purchases()"))
    ).all()
    assert (purchase.tenant_id, purchase.slug) in unbound_rows

    tenant_id = (
        await db.execute(
            text("SELECT public.resolve_website_purchase_tenant(:pid)"), {"pid": str(purchase.id)}
        )
    ).scalar()
    assert tenant_id == purchase.tenant_id

    # After confirmation the purchase leaves the pending set; the resolver
    # still names its owner — telling "already activated" (409) from "no such
    # purchase" (404) is the SERVICE's job once the tenant is bound.
    await purchase_service.confirm(
        db, purchase_id=purchase.id, confirmed_by_user_id=tenant_ctx.user.id
    )
    assert (
        await db.execute(
            text("SELECT public.resolve_website_purchase_tenant(:pid)"), {"pid": str(purchase.id)}
        )
    ).scalar() == purchase.tenant_id


# ------------------------------------------------------------- events ----


def test_the_website_events_are_registered_envelope_types() -> None:
    for event_type in (
        "website.purchase.created",
        "website.purchase.confirmed",
        "website.published",
        "website.rolled_back",
    ):
        envelope = build_envelope(
            event_type,
            tenant_id=uuid.uuid4(),
            aggregate_type="website",
            aggregate_id=uuid.uuid4(),
        )
        assert envelope.type == event_type


# --------------------------------------------------------------- slugs ----


def test_slug_rules() -> None:
    validate_slug("my-shop-1")
    for bad in ("ab", "-leading", "trailing-", "Has-Caps", "under_score", "api", "a" * 81):
        with pytest.raises(WebsiteDomainError):
            validate_slug(bad)


# ------------------------------------------------------- funny-baby design ----


def test_the_funny_baby_design_is_registered() -> None:
    """Design-1 (ported from the Funny Baby Base44 app) is in the catalog:
    10 pages covering the source app's public surface, seeded with the real
    Arabic copy, and every section validates against the registry (import-time
    fail-closed already proved it — this pins the shape)."""
    manifest = catalog.get("funny-baby")
    assert {p.slug for p in manifest.pages} == {
        "home",
        "products",
        "offers",
        "stores",
        "faq",
        "track-order",
        "shipping",
        "exchange-return",
        "privacy",
        "terms",
    }
    home_types = [s.type for p in manifest.pages if p.slug == "home" for s in p.sections]
    assert home_types == ["hero", "features", "product_grid", "image_text", "steps", "cta"]
    assert len(catalog.list()) >= 3


def test_the_new_list_sections_validate_and_render() -> None:
    from app.modules.website.sections import registry as section_registry

    # Features / steps / branches validate their flat item models...
    validated = section_registry.validate(
        "features",
        {"items": [{"title": "وعد", "text": "نص الوعد"}]},
    )
    assert validated.model_dump()["items"][0]["title"] == "وعد"
    with pytest.raises(Exception):  # noqa: B017 - InvalidSection via registry
        section_registry.validate("branches", {"items": [{"name": "فرع"}]})  # address missing

    # ...and render through the BASE renderers (general-commerce has no
    # template overrides, so the shared components do the work).
    snapshot = {
        "name": "متجر عام",
        "default_locale": "ar",
        "template_id": "general-commerce",
        "theme_tokens": {"primary": "#0f172a", "background": "#ffffff"},
        "navigation": [],
        "projection": {
            "pages": [
                {
                    "id": "1",
                    "title": "الرئيسية",
                    "slug": "home",
                    "sections": [
                        {
                            "type": "features",
                            "props": {
                                "eyebrow": "وعودنا ليك",
                                "items": [{"title": "توصيل", "text": "لكل المحافظات"}],
                            },
                        },
                        {
                            "type": "steps",
                            "props": {
                                "heading": "٣ خطوات",
                                "items": [{"title": "اختار", "text": "المقاس"}],
                            },
                        },
                        {
                            "type": "branches",
                            "props": {
                                "items": [
                                    {
                                        "name": "المعادي",
                                        "address": "شارع ٩",
                                        "phone": "01000000001",
                                        "hours": "١١ ص – ١٠ م",
                                    }
                                ],
                            },
                        },
                    ],
                }
            ]
        },
    }
    html = render_website(snapshot, RenderContext())
    assert "feature-card" in html and "step-card" in html and "branch-card" in html
    assert "وعودنا ليك" in html and "المعادي" in html
    # The branch phone renders as a tel: link (allowlisted scheme).
    assert 'href="tel:01000000001"' in html


def test_funny_baby_renders_their_verbatim_list_components() -> None:
    """Funny-baby's features/steps/branches now render the Base44 app's
    exact components — not the base approximation classes."""
    snapshot = {
        "name": "فاني بيبي",
        "default_locale": "ar",
        "template_id": "funny-baby",
        "theme_tokens": {"primary": "#f3513f", "background": "#fffdf5"},
        "navigation": [],
        "projection": {
            "pages": [
                {
                    "id": "1",
                    "title": "الرئيسية",
                    "slug": "home",
                    "sections": [
                        {"type": "features", "props": {}},
                        {"type": "steps", "props": {}},
                        {"type": "branches", "props": {}},
                    ],
                }
            ]
        },
    }
    html = render_website(snapshot, RenderContext())
    # Their PromiseStrip cards, their HomeSteps numbered cards, their
    # BranchCard actions — the verbatim module's own markers.
    assert "مقاس مكتوب بالسنتيمتر" in html
    assert "اعمل حسابك في دقيقة" in html
    assert "الاتجاهات" in html
    assert "feature-card" not in html and "step-card" not in html


# ------------------------------------------------------- warm-paper design ----


def test_the_warm_paper_design_is_registered() -> None:
    """Design-2 (the men's-wear paper restyle) is in the catalog."""
    manifest = catalog.get("warm-paper")
    assert {p.slug for p in manifest.pages} == {
        "home",
        "products",
        "offers",
        "stores",
        "faq",
        "track-order",
        "shipping",
        "exchange-return",
        "privacy",
        "terms",
    }
    home_types = [s.type for p in manifest.pages if p.slug == "home" for s in p.sections]
    assert home_types == ["hero", "chapters", "product_grid", "manifesto", "steps", "cta"]
    assert len(catalog.list()) >= 4


def test_the_warm_paper_overrides_render_the_paper_identity() -> None:
    """The hero renders the paper card + ticker + BOTH CTAs; feature items
    WITH hrefs render as chapter link cards, items WITHOUT as promise cards;
    steps render inside the yellow paper card."""
    snapshot = {
        "name": "ورق دافئ",
        "default_locale": "ar",
        "template_id": "warm-paper",
        "theme_tokens": {"primary": "#d98974", "background": "#fff8ef"},
        "navigation": [],
        "projection": {
            "pages": [
                {
                    "id": "1",
                    "title": "الرئيسية",
                    "slug": "home",
                    "sections": [
                        {
                            "type": "hero",
                            "props": {
                                "eyebrow": "مجموعة الموسم ٢٠٢٦",
                                "heading": "ستايل هادي\nيفرق في إطلالتك",
                                "cta_label": "ابدأ التسوق",
                                "cta_url": "#page-products",
                                "secondary_label": "زيارة الفروع",
                                "secondary_url": "#page-stores",
                                "note": "تغليف هدايا مجاني",
                                "ticker": ["توصيل لكل المحافظات", "استبدال ١٤ يوم"],
                            },
                        },
                        {
                            "type": "features",
                            "props": {
                                "items": [
                                    {
                                        "title": "الكتالوج",
                                        "text": "كل المنتجات",
                                        "href": "#page-products",
                                    },
                                    {
                                        "title": "العروض",
                                        "text": "أكواد الخصم",
                                        "href": "#page-offers",
                                    },
                                ],
                            },
                        },
                        {
                            "type": "features",
                            "props": {
                                "items": [{"title": "مقاس بالسنتيمتر", "text": "على كل قطعة"}],
                            },
                        },
                        {
                            "type": "steps",
                            "props": {"items": [{"title": "اختار", "text": "بدقة"}]},
                        },
                    ],
                }
            ]
        },
    }
    html = render_website(snapshot, RenderContext())
    assert "hero-paper" in html and "story-paper-green" in html
    assert "story-mark" in html and "إطلالتك" in html
    assert html.count("story-btn") >= 2  # both CTAs rendered
    assert "story-ticker" in html and "توصيل لكل المحافظات" in html
    # chapters: link cards with the allowlisted anchors
    assert 'href="#page-products"' in html and "story-chap" in html
    # promises: numbered cards, NOT link cards
    assert "story-promise" in html and "story-pn" in html
    # steps inside the yellow paper card
    assert "story-paper-yellow" in html and "story-step" in html


# ---------------------------------------------------- street-poster design ----


def test_the_street_poster_design_is_registered() -> None:
    """Design-3 (the printed street-poster restyle) is in the catalog."""
    manifest = catalog.get("street-poster")
    assert {p.slug for p in manifest.pages} == {
        "home",
        "products",
        "offers",
        "stores",
        "faq",
        "track-order",
        "shipping",
        "exchange-return",
        "privacy",
        "terms",
    }
    home_types = [s.type for p in manifest.pages if p.slug == "home" for s in p.sections]
    assert home_types == ["hero", "features", "product_grid", "features", "steps", "cta"]
    # The hero carries the poster stats strip.
    hero_props = manifest.pages[0].sections[0].props
    assert hero_props["stats"][0]["value"] == "S – XXL"
    assert len(catalog.list()) >= 5


def test_the_preview_walk_renders_the_full_demo_site() -> None:
    """«معاينة حية»: every template walks as a complete demo site with NO
    database — home renders themed demo products, the ribbon marks it a
    demo, and the seeded #page- anchors become real per-page URLs."""
    from app.modules.website.services import preview_service

    html = preview_service.render_template_preview("funny-baby")
    assert html is not None
    assert "preview-ribbon" in html  # the demo marker
    assert "بودي سوت قطن" in html  # themed demo products, not generic ones
    assert 'href="/sites/preview/funny-baby/faq"' in html  # nav links per page
    assert 'href="/sites/preview/funny-baby/products"' in html  # their hero CTA rewritten
    # VERBATIM fidelity: their exact markup, images and chrome
    assert "media.base44.com" in html  # their real images hotlinked
    assert "موسم جديد" in html and "ملابس تلعب وتنام" in html  # their hero copy
    assert "sticky top-0 z-50" in html  # their header chrome
    assert "bg-[#25D366]" in html  # their floating whatsapp button


def test_the_preview_walk_serves_single_pages() -> None:
    from app.modules.website.services import preview_service

    page = preview_service.render_template_preview("funny-baby", page_slug="faq")
    assert page is not None
    assert "الأسئلة الشائعة" in page
    assert "ملابس تلعب وتنام" not in page  # the HOME hero never leaks into a sub-page
    # navigation still points at the sibling pages
    assert '/sites/preview/funny-baby/offers"' in page
    stores = preview_service.render_template_preview("funny-baby", page_slug="stores")
    assert stores is not None and "الاتجاهات" in stores  # their branch-card actions
    assert "ملابس تلعب وتنام" not in stores


def test_the_preview_walk_fails_closed_on_unknowns() -> None:
    from app.modules.website.services import preview_service

    assert preview_service.render_template_preview("no-such-template") is None
    assert preview_service.render_template_preview("funny-baby", page_slug="nope") is None
    # a template without demo products falls back to the generic set
    html = preview_service.render_template_preview("general-commerce")
    assert html is not None and "منتج تجريبي ١" in html


# ------------------------------------------------- merchant identity ----


async def _activated_funny_baby(db: AsyncSession, tenant_ctx) -> tuple[ws.Website, TenantContext]:
    purchase = await purchase_service.create(
        db,
        _ctx(db, tenant_ctx),
        template_id="funny-baby",
        site_name="محل مصطفى",
        slug=f"shop-{uuid.uuid4().hex[:8]}",
        # The merchant's WhatsApp rides the PURCHASE so the seeded CTA
        # sections are personalized at activation (_personalize_props);
        # identity edits later only reach the snapshot, not seed props.
        whatsapp_number="+201234567890",
    )
    await purchase_service.confirm(
        db, purchase_id=purchase.id, confirmed_by_user_id=tenant_ctx.user.id
    )
    website = (
        await db.execute(
            select(ws.Website).where(
                ws.Website.tenant_id == tenant_ctx.tenant_id, ws.Website.status != "deleted"
            )
        )
    ).scalar_one()
    return website, _ctx(db, tenant_ctx)


async def test_merchant_identity_overrides_the_verbatim_brand(db: AsyncSession, tenant_ctx) -> None:
    """The published site renders the merchant's OWN whatsapp/socials; the
    template's placeholder constants disappear from the live page."""
    website, ctx = await _activated_funny_baby(db, tenant_ctx)
    await content_service.update_identity(
        db,
        ctx,
        whatsapp_number="+201234567890",
        social_links=[
            {"platform": "tiktok", "handle": "@mostafa", "href": "https://tiktok.com/@mostafa"}
        ],
        logo_url="https://cdn.example.com/logo.png",
        site_category="ملابس أطفال",
        description="أهلاً بكم",
    )
    html = await public_service.render_html(db, await _snapshot(db, website.id))
    assert "wa.me/201234567890" in html
    assert "tiktok.com/@mostafa" in html
    assert "201000000000" not in html  # the template's placeholder never leaks
    assert "facebook.com/funnybaby.eg" not in html  # nor their socials


def test_the_preview_walk_keeps_the_template_defaults() -> None:
    """A preview has no merchant identity — the template's own constants win."""
    from app.modules.website.services import preview_service

    page = preview_service.render_template_preview("funny-baby")
    assert page is not None
    assert "wa.me/201000000000" in page


async def test_identity_settings_persist_and_refresh_the_snapshot(
    db: AsyncSession, tenant_ctx
) -> None:
    website, ctx = await _activated_website(db, tenant_ctx)
    result = await content_service.update_identity(
        db,
        ctx,
        whatsapp_number="201098765432",
        social_links=[
            {
                "platform": "instagram",
                "handle": "mostafa.shop",
                "href": "https://instagram.com/mostafa.shop",
            }
        ],
        logo_url="https://cdn.example.com/logo.png",
        site_category="إكسسوارات",
        description="أفضل الأسعار",
    )
    stored = result["website"]
    assert stored["whatsapp_number"] == "201098765432"
    assert stored["social_links"][0]["platform"] == "instagram"
    assert stored["logo_url"] == "https://cdn.example.com/logo.png"
    assert stored["site_category"] == "إكسسوارات"
    assert stored["description"] == "أفضل الأسعار"

    snapshot = await _snapshot(db, website.id)
    assert snapshot.whatsapp_number == "201098765432"
    assert snapshot.social_links[0]["href"] == "https://instagram.com/mostafa.shop"
    assert snapshot.logo_url == "https://cdn.example.com/logo.png"
    assert snapshot.site_category == "إكسسوارات"


async def test_identity_settings_validate_hostile_input(db: AsyncSession, tenant_ctx) -> None:
    from app.core.errors import ValidationError

    _, ctx = await _activated_website(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await content_service.update_identity(
            db, ctx, social_links=[{"platform": "nope", "href": "https://x.com/a"}]
        )
    with pytest.raises(ValidationError):
        await content_service.update_identity(
            db, ctx, social_links=[{"platform": "tiktok", "href": "javascript:alert(1)"}]
        )
    with pytest.raises(ValidationError):
        await content_service.update_identity(db, ctx, logo_url="javascript:alert(1)")
    with pytest.raises(ValidationError):
        await content_service.update_identity(db, ctx, whatsapp_number="+123")


async def test_site_image_upload_fails_closed_without_storage(
    db: AsyncSession, tenant_ctx, monkeypatch
) -> None:
    """No object storage configured → a structured 503, never a silent URL."""
    from starlette.requests import Request as StarletteRequest

    from app.core.errors import StorageUnavailableError
    from app.modules.website import router as website_router

    class _NoStorage:
        configured = False

    monkeypatch.setattr(website_router, "get_storage", lambda: _NoStorage())
    request = StarletteRequest(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": "/api/v1/website/images/upload",
            "query_string": b"",
            "headers": [(b"content-type", b"image/png")],
        }
    )
    with pytest.raises(StorageUnavailableError):
        await website_router.upload_site_image(request, _ctx(db, tenant_ctx))

"""Catalog and vision tools.

search_catalog, get_product_details, get_product_photos and find_product_by_image.

Split out of the former single-file ``customer/tools.py``; the code is unchanged.
"""

from __future__ import annotations

import operator
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import reduce
from typing import Literal

from pydantic import Field
from sqlalchemy import case, func, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError
from app.core.sql import LIKE_ESCAPE, like_pattern
from app.core.storage import get_storage
from app.modules.ai.agents.customer.tools._shared import (
    _money,
    _StrictArgs,
    sellable_product_statuses,
)
from app.modules.ai.agents.customer.vision.schemas import ImageKind
from app.modules.ai.models import IncomingStock

#: "قليل" is the top of the low-stock band. A constant, like the vision
#: thresholds — the model never derives scarcity itself.
LOW_STOCK_THRESHOLD = 5


#: Western digits ON PURPOSE: grounding folds Arabic-Indic digits in the
#: REPLY, but matches FACT strings verbatim — an Arabic-Indic label would
#: never ground the numeral the model writes.
_ARABIC_MONTHS = {
    1: "يناير",
    2: "فبراير",
    3: "مارس",
    4: "أبريل",
    5: "مايو",
    6: "يونيو",
    7: "يوليو",
    8: "أغسطس",
    9: "سبتمبر",
    10: "أكتوبر",
    11: "نوفمبر",
    12: "ديسمبر",
}


def _restock_label(expected_on: date, confidence: str) -> str:
    """The ready-to-say restock phrase (ISO dates are NOT quotable facts).

    The fact ledger excludes ISO date strings, so a raw ``2026-10-25`` would
    leave the model's "25 أكتوبر" ungrounded and the reply blocked. The tool
    phrases the date itself, with the certainty baked in: confirmed rows say
    so, expected rows get the hedge. The model only repeats it.
    """
    label = f"{expected_on.day} {_ARABIC_MONTHS[expected_on.month]} {expected_on.year}"
    if confidence == "confirmed":
        return f"مؤكد: {label}"
    return f"متوقع حوالي {label}"


async def _selling_warehouse_ids(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[uuid.UUID] | None:
    """The shelves the cashier actually sells from, or None when no till exists.

    The POS reads ONE warehouse per profile (``PosProfile.warehouse_id``). The
    agent must quote the same shelves, otherwise a second warehouse (back
    store, returns) makes it say "متوفر" for goods the till cannot sell. A shop
    with no active POS profile yet keeps the old behaviour (all warehouses).
    """
    # A parameter-bound read of the till's table, not an import of pos.models:
    # `ai -> pos` would close a module cycle (tests/test_module_boundaries.py).
    result = await session.execute(
        text(
            "SELECT DISTINCT warehouse_id FROM pos_profiles "
            "WHERE tenant_id = :tenant_id AND is_active"
        ),
        {"tenant_id": tenant_id},
    )
    return list(result.scalars()) or None


async def _unit_prices(
    session: AsyncSession, tenant_id: uuid.UUID, variants: list
) -> dict[uuid.UUID, Decimal]:
    """Price for ONE unit, exactly as the cashier prices it (tier ladder, qty 1)."""
    from app.core.tenancy import resolve_tenant_currency
    from app.modules.catalog.service import CatalogService

    if not variants:
        return {}
    currency = await resolve_tenant_currency(session, tenant_id)
    ladders = await CatalogService.price_tiers_for_many(
        session, tenant_id, [v.id for v in variants], currency=currency
    )
    return {
        v.id: CatalogService.tiered_unit_price(v.price, ladders.get(v.id, []), 1) for v in variants
    }


async def _availability_map(
    session: AsyncSession, tenant_id: uuid.UUID, variant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict]:
    """Stock status + restock phrase per variant, computed SERVER-SIDE.

    Status vocabulary: متوفر / قليل / خلص / هيتجدد. The model phrases what
    this returns; it never sees or derives the raw quantity. The restock
    label rides the earliest OPEN incoming_stock row, certainty included.
    """
    out: dict[uuid.UUID, dict] = {}
    if not variant_ids:
        return out

    from app.modules.inventory.models import InventoryBalance

    selling = await _selling_warehouse_ids(session, tenant_id)
    balance_conditions = [
        InventoryBalance.tenant_id == tenant_id,
        InventoryBalance.variant_id.in_(variant_ids),
    ]
    if selling is not None:
        balance_conditions.append(InventoryBalance.warehouse_id.in_(selling))
    balance_rows = (
        await session.execute(
            select(
                InventoryBalance.variant_id,
                func.coalesce(
                    func.sum(InventoryBalance.on_hand - InventoryBalance.reserved),
                    0,
                ),
                func.max(InventoryBalance.updated_at),
            )
            .where(*balance_conditions)
            .group_by(InventoryBalance.variant_id)
        )
    ).all()
    available = {row[0]: (int(row[1]), row[2]) for row in balance_rows}

    restock_rows = (
        await session.execute(
            select(IncomingStock)
            .where(
                IncomingStock.tenant_id == tenant_id,
                IncomingStock.variant_id.in_(variant_ids),
                IncomingStock.status == "open",
            )
            .order_by(IncomingStock.expected_on.asc())
        )
    ).scalars()
    earliest: dict[uuid.UUID, IncomingStock] = {}
    for row in restock_rows:
        earliest.setdefault(row.variant_id, row)

    for variant_id in variant_ids:
        qty, updated_at = available.get(variant_id, (0, None))
        restock = earliest.get(variant_id)
        if qty > LOW_STOCK_THRESHOLD:
            status = "متوفر"
        elif qty > 0:
            status = "قليل"
        elif restock is not None:
            status = "هيتجدد"
        else:
            status = "خلص"
        # The restock label only matters when the shelf is empty — attaching
        # it to an in-stock variant invites the model to promise an incoming
        # shipment for something the customer can buy today.
        out[variant_id] = {
            "status": status,
            "restock_label": _restock_label(restock.expected_on, restock.confidence)
            if restock is not None and status in ("خلص", "هيتجدد")
            else None,
            # The model can only say "after 7 days" if 7 is a fact — a raw
            # integer here is what makes the arithmetic quotable.
            "restock_in_days": (restock.expected_on - datetime.now(UTC).date()).days
            if restock is not None
            else None,
            "updated_at": updated_at.isoformat() if updated_at is not None else None,
        }
    return out


class SearchCatalogArgs(_StrictArgs):
    query: str = Field(min_length=1, max_length=255)
    attributes: dict[str, str | int | float | bool] | None = None
    option_values: dict[str, str | int | float | bool] | None = None
    limit: int = Field(default=5, ge=1, le=20)


async def _search_catalog(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    query: str,
    attributes: dict[str, object] | None = None,
    option_values: dict[str, object] | None = None,
    limit: int = 5,
) -> dict:
    """Search + price + availability in ONE call (consolidation by design).

    The three old reads (search, price, stock) were always called together;
    one round trip is cheaper and removes the model's tool-choice burden.
    """
    from app.modules.catalog.models import Product, ProductVariant

    # OR per word, not AND across the phrase: "تيشرت أسود مقاس اكس" must
    # still surface the تيشرت even when مقاس اكس matches nothing — the model
    # decides ask-vs-show from total_matches, not from an empty result.
    #
    # Each word gets normalization arms on the LIKE side: the raw form, the
    # form with a leading ال stripped ("الأسود" -> "أسود" — customers write
    # the definite article, catalogs usually don't), and the TAIL with the
    # first two characters dropped ("%حمر%" matches "أحمر" and "احمر" — the
    # hamza only touches the first letter). Words of four characters or more
    # ALSO get a trigram arm (pg_trgm): the near-match is what bridges a
    # mid-word spelling insertion — "تيشرت" finds "تيشيرت" — which prefix
    # and substring arms structurally cannot.
    #
    # Rows are RANKED by how many of the customer's words they matched, so a
    # black-t-shirt ask never opens with chinos that merely share the color.
    def _word_arms(word: str) -> list[str]:
        arms = [word]
        if len(word) >= 4:
            # Drop the first character: the hamza sits there ("احمر" -> "%حمر%"
            # matches "أحمر" and "احمر" alike).
            arms.append(word[1:])
        if len(word) >= 5:
            # Drop two: the definite article ("الأسود" -> "%أسود%").
            arms.append(word[2:])
        return list(dict.fromkeys(arms))

    words = [w for w in query.split() if w][:6] or [query]

    def _word_expr(word: str):
        arms = [
            Product.search_ts.op("@@")(func.plainto_tsquery(literal_column("'simple'"), word)),
            Product.title.ilike(like_pattern(word), escape=LIKE_ESCAPE),
            ProductVariant.title.ilike(like_pattern(word), escape=LIKE_ESCAPE),
            ProductVariant.sku.ilike(like_pattern(word), escape=LIKE_ESCAPE),
        ]
        for pattern in _word_arms(word):
            arms += [
                Product.title.ilike(like_pattern(pattern), escape=LIKE_ESCAPE),
                ProductVariant.title.ilike(like_pattern(pattern), escape=LIKE_ESCAPE),
            ]
        if len(word) >= 4:
            # pg_trgm near-match — the migration installs the extension and
            # the GIN trgm indexes; the threshold is loosened to 0.2 because
            # Arabic trigram overlap on a one-letter insertion lands ~0.29.
            arms += [Product.title.op("%")(word), ProductVariant.title.op("%")(word)]
            # Title-LEVEL trigram dilutes as titles grow (a short query word
            # against a long title scores ~0.28, under every threshold). The
            # WORD-to-word comparison is where the signal lives: تيشرت vs
            # تيشيرت scores 0.44 token-to-token on the live catalog — so an
            # EXISTS over the title's own words carries the real match.
            # Unindexed by construction (per-row word split) — fine at
            # catalog scale, revisited if catalogs grow orders of magnitude.
            for col in ("products.title", "product_variants.title"):
                # The column names are OUR constants, never user input; the
                # word rides as a bound parameter. The bindparam name is
                # UNIQUE per (word, column): shared names across arms let a
                # later arm's value leak into an earlier one's text().
                param = f"trgm_{abs(hash(word)) % 99999}_{col.split('.')[0]}"
                arms.append(
                    text(
                        f"EXISTS (SELECT 1 FROM unnest(regexp_split_to_array("
                        f"{col}, '[[:space:]]+')) AS t(w) WHERE w % :{param})"
                    ).bindparams(**{param: word})
                )
        return or_(*arms)

    word_exprs = [_word_expr(word) for word in words]
    conditions = [
        ProductVariant.tenant_id == tenant_id,
        ProductVariant.is_active.is_(True),
        Product.status.in_(sellable_product_statuses()),
        or_(*word_exprs),
    ]
    if attributes:
        conditions.append(Product.attributes.contains(attributes))
    if option_values:
        conditions.append(ProductVariant.option_values.contains(option_values))

    # The threshold is transaction-local: the % operator above reads it, and
    # the default 0.3 would miss the very insertions this arm exists for.
    await session.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.2"))

    # total_matches counts PRODUCTS — "how many things match" is a product
    # question; counting variants inflated it with size/color duplicates.
    total_matches = (
        await session.execute(
            select(func.count(func.distinct(Product.id)))
            .select_from(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(*conditions)
        )
    ).scalar_one()

    # Rank: most of the customer's words matched first, then alphabetical.
    match_score = reduce(operator.add, (case((expr, 1), else_=0) for expr in word_exprs))
    rows = (
        await session.execute(
            select(ProductVariant, Product.title)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(*conditions)
            .order_by(match_score.desc(), Product.title.asc(), ProductVariant.id.asc())
            .limit(limit)
        )
    ).all()
    availability = await _availability_map(session, tenant_id, [variant.id for variant, _ in rows])
    prices = await _unit_prices(session, tenant_id, [variant for variant, _ in rows])
    result = {
        "total_matches": int(total_matches),
        "results": [
            {
                "variant_id": str(variant.id),
                "product_id": str(variant.product_id),
                "title": variant.title or product_title,
                "sku": variant.sku,
                "price": _money(prices[variant.id]),
                "availability": availability.get(variant.id),
            }
            for variant, product_title in rows
        ],
    }
    if not rows:
        result["hint"] = "مفيش مطابق — جرب كلمة واحدة بس، أو تهجئة مختلفة للكلمة، أو شيل الفلاتر."
    return result


class GetProductDetailsArgs(_StrictArgs):
    product_id: uuid.UUID


async def _get_product_details(
    session: AsyncSession, tenant_id: uuid.UUID, *, product_id: uuid.UUID
) -> dict:
    """Material, attributes and EVERY variant with price and availability."""
    from app.modules.catalog.models import Product, ProductVariant

    product = (
        await session.execute(
            select(Product).where(
                Product.tenant_id == tenant_id,
                Product.id == product_id,
                Product.status.in_(sellable_product_statuses()),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError(f"product {product_id} not found")

    variants = (
        await session.execute(
            select(ProductVariant)
            .where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.product_id == product_id,
            )
            .order_by(ProductVariant.id.asc())
        )
    ).scalars()
    variant_rows = list(variants.all())
    active = [v for v in variant_rows if v.is_active]
    availability = await _availability_map(session, tenant_id, [v.id for v in active])
    prices = await _unit_prices(session, tenant_id, variant_rows)
    return {
        "product_id": str(product.id),
        "title": product.title,
        "description": product.description,
        "attributes": product.attributes or {},
        "variants": [
            {
                "variant_id": str(variant.id),
                "title": variant.title or product.title,
                "sku": variant.sku,
                "price": _money(prices[variant.id]),
                "is_active": variant.is_active,
                "option_values": variant.option_values or {},
                "availability": availability.get(variant.id),
            }
            for variant in variant_rows
        ],
    }


class GetProductPhotosArgs(_StrictArgs):
    product_id: uuid.UUID
    selection: Literal["primary", "all"] = "primary"


async def _get_product_photos(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    product_id: uuid.UUID,
    selection: Literal["primary", "all"] = "primary",
) -> dict:
    """Gallery image ids only — the server mints and attaches the URLs."""
    from app.modules.catalog.models import Product, ProductImage

    product_exists = (
        await session.execute(
            select(Product.id).where(
                Product.tenant_id == tenant_id,
                Product.id == product_id,
                Product.status.in_(sellable_product_statuses()),
            )
        )
    ).scalar_one_or_none()
    if product_exists is None:
        raise NotFoundError(f"product {product_id} not found")

    stmt = (
        select(ProductImage.id, ProductImage.alt, ProductImage.position)
        .where(
            ProductImage.tenant_id == tenant_id,
            ProductImage.product_id == product_id,
        )
        .order_by(ProductImage.position.asc(), ProductImage.id.asc())
    )
    if selection == "primary":
        stmt = stmt.limit(1)
    rows = (await session.execute(stmt)).all()
    return {
        "media": [
            {"image_id": str(image_id), "alt": alt, "position": position}
            for image_id, alt, position in rows
        ]
    }


class FindProductByImageArgs(_StrictArgs):
    image_kind: ImageKind
    hints: str | None = Field(default=None, max_length=500)


async def _find_product_by_image(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    image_kind: ImageKind,
    hints: str | None = None,
    context: dict | None = None,
) -> dict:
    from app.modules.ai.agents.customer.vision.classifier import classify
    from app.modules.ai.agents.customer.vision.pipeline import run_vision_match

    # The server-side pre-classification (when the coordinator ran it) is the
    # AUTHORITY on what this photo is: the model cannot re-propose "product"
    # for a photo the server classified as something else, and sensitive kinds
    # are refused outright (§12.5 — deterministic, not model-dependent).
    server_kind = (context or {}).get("image_kind_classified")
    if server_kind is not None and server_kind != ImageKind.PRODUCT.value:
        if server_kind in ("payment_proof", "complaint"):
            raise DomainError(f"image requires handover: {server_kind}_requires_human")
        raise DomainError(
            f"the photo was classified server-side as {server_kind} — it is not a product photo"
        )

    allowed, handoff_reason = classify(image_kind)
    if not allowed:
        raise DomainError(f"image requires handover: {handoff_reason}")
    image_url = (context or {}).get("customer_image")
    if not image_url:
        raise DomainError("no customer image in this turn")

    # The coordinator's pipeline result is reused when present: the paid
    # embedding+rerank runs ONCE per photo, not again per tool call.
    precomputed = (context or {}).get("vision_match")
    if precomputed is not None:
        return {
            "confidence": precomputed.confidence.value,
            "candidates": precomputed.candidates,
            "reason": precomputed.reason,
        }

    result = await run_vision_match(session, tenant_id, image_url=image_url, text_hint=hints)
    return {
        "confidence": result.confidence.value,
        "candidates": result.candidates,
        "reason": result.reason,
    }


async def media_payload_for_ids(
    session: AsyncSession, tenant_id: uuid.UUID, image_ids: list[str]
) -> list[dict]:
    from app.modules.catalog.models import ProductImage

    if not image_ids:
        return []
    rows = (
        await session.execute(
            select(ProductImage.id, ProductImage.url, ProductImage.alt)
            .where(
                ProductImage.tenant_id == tenant_id,
                ProductImage.id.in_([uuid.UUID(str(i)) for i in image_ids]),
            )
            .order_by(ProductImage.position.asc(), ProductImage.id.asc())
        )
    ).all()
    return [
        {
            "image_id": str(image_id),
            "image_url": get_storage().resolve_product_image_url(url, tenant_id=tenant_id),
            "alt": alt,
        }
        for image_id, url, alt in rows
    ]

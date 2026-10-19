"""Customer Agent tool implementations and specs.

The scope cut (2026-10-18): the customer agent is LANGUAGE-ONLY — it answers
from store data and hands over; it never sells, never mutates records. Seven
tools, every one read-only except the escalation:

- Catalog: search_catalog, get_product_details, get_product_photos
- Vision: find_product_by_image
- Store: get_store_info, search_knowledge
- Escalation: handover_to_human

Descriptions follow the platform guidance (Anthropic's tool-design notes,
OpenAI's function-calling guide): state what the tool does, when to use it,
when NOT to use it, and what it returns. The server binds customer and
conversation from its own context — the model never passes them.
"""

from __future__ import annotations

import operator
import uuid
from datetime import UTC, date, datetime
from functools import reduce
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import case, func, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError, ValidationError
from app.core.sql import LIKE_ESCAPE, like_pattern
from app.core.storage import get_storage
from app.modules.ai.agents.customer.vision.schemas import ImageKind
from app.modules.ai.models import IncomingStock
from app.modules.ai.tools import ToolSpec, register_tool


def sellable_product_statuses() -> frozenset[str]:
    """The checkout gate's sellable vocabulary, for in-module readers.

    ONE lazy import site: the catalog's tables are read as parameter-bound
    read models, and the vision verifier plus every tool here read the
    vocabulary through this function so they can never drift from checkout.
    """
    from app.modules.orders.service import SELLABLE_PRODUCT_STATUSES

    return SELLABLE_PRODUCT_STATUSES


def _parse_bound_id(raw: object) -> uuid.UUID | None:
    """Parse a server-side id from the context; malformed is a tool error."""
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise DomainError("bound id is not a valid uuid") from exc


def _money(value) -> str | None:
    """Money is Decimal(Numeric(14,2)) — serialized exactly, never as float."""
    return None if value is None else str(value)


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
            .where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.variant_id.in_(variant_ids),
            )
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


# ------------------------------------------------------------- catalog tools --


class SearchCatalogArgs(BaseModel):
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
            Product.search_ts.op("@@")(
                func.plainto_tsquery(literal_column("'simple'"), word)
            ),
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
    match_score = reduce(
        operator.add, (case((expr, 1), else_=0) for expr in word_exprs)
    )
    rows = (
        await session.execute(
            select(ProductVariant, Product.title)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(*conditions)
            .order_by(match_score.desc(), Product.title.asc(), ProductVariant.id.asc())
            .limit(limit)
        )
    ).all()
    availability = await _availability_map(
        session, tenant_id, [variant.id for variant, _ in rows]
    )
    result = {
        "total_matches": int(total_matches),
        "results": [
            {
                "variant_id": str(variant.id),
                "product_id": str(variant.product_id),
                "title": variant.title or product_title,
                "sku": variant.sku,
                "price": _money(variant.price),
                "availability": availability.get(variant.id),
            }
            for variant, product_title in rows
        ]
    }
    if not rows:
        result["hint"] = (
            "مفيش مطابق — جرب كلمة واحدة بس، أو تهجئة مختلفة للكلمة، أو شيل "
            "الفلاتر."
        )
    return result


class GetProductDetailsArgs(BaseModel):
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
                "price": _money(variant.price),
                "is_active": variant.is_active,
                "option_values": variant.option_values or {},
                "availability": availability.get(variant.id),
            }
            for variant in variant_rows
        ],
    }


class GetProductPhotosArgs(BaseModel):
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


# ------------------------------------------------------------- store tools --


class GetStoreInfoArgs(BaseModel):
    """No arguments — the store's published info is one deterministic pull."""


async def _get_store_info(session: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """The store's own published facts: hours, branches, shipping, payment,
    returns, how to order.

    Backed by the tenant's customer-facing knowledge items read directly —
    no embedding call, fully deterministic. The merchant owns the content;
    behavior lives in prompts, facts live HERE.
    """
    from app.modules.ai.models import KnowledgeItem

    rows = (
        await session.execute(
            select(KnowledgeItem.title, KnowledgeItem.content)
            .where(
                KnowledgeItem.tenant_id == tenant_id,
                KnowledgeItem.visibility == "customer_facing",
            )
            .order_by(KnowledgeItem.created_at.asc())
            .limit(30)
        )
    ).all()
    # Token ceiling: content is merchant-authored Text with no upper bound,
    # so the pull stops at the budget instead of flooding the model's context
    # (a tool response cap, per the tool-design guidance).
    _BUDGET = 6000
    items: list[dict] = []
    spent = 0
    for title, content in rows:
        cost = len(title) + len(content)
        if spent + cost > _BUDGET and items:
            break
        items.append({"title": title, "content": content})
        spent += cost
    return {"items": items}


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=3, ge=1, le=10)


async def _search_knowledge(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    query: str,
    limit: int = 3,
) -> dict:
    from app.modules.ai import knowledge

    try:
        hits = await knowledge.search_knowledge(
            session, tenant_id, query, limit=limit, visibility="customer_facing"
        )
    except ValidationError as exc:
        raise DomainError(f"knowledge search unavailable: {exc}") from exc
    return {
        "results": [
            {
                "title": item.title,
                "content": item.content,
                "source_type": item.source_type,
            }
            for item, _distance in hits
        ]
    }


# ------------------------------------------------------------- escalation --


class HandoverToHumanArgs(BaseModel):
    reason: Literal[
        "complex_problem", "missing_data", "customer_request",
        "complaint", "purchase_intent",
    ]
    summary: str = Field(min_length=1, max_length=1000)


async def _handover_to_human(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    reason: str,
    summary: str,
    context: dict | None = None,
) -> dict:
    """The MODEL's escalation decision, executed server-side.

    The conversation id comes from the server-bound context, never from the
    model. The write goes through the one handover writer (row + conversation
    status + outbox event + notification, idempotent), so a model that calls
    this twice, or a retried run, converges on one open handover. The summary
    is the model's own account — what it tried and what is missing — which is
    exactly what the staff member opening the conversation needs.
    """
    conversation_id = _parse_bound_id((context or {}).get("conversation_id"))
    if conversation_id is None:
        raise DomainError("no conversation bound to this tool call")

    from app.modules.ai.handover import request_human_takeover

    await request_human_takeover(
        session,
        tenant_id,
        conversation_id=conversation_id,
        reason=reason,
        note=summary,
    )
    # Data only — NO instructions here. Trained models treat instructions in
    # tool results with skepticism and may ignore them (Anthropic's untrusted-
    # content guidance); the farewell behavior lives in the system prompt.
    return {
        "status": "handover_recorded",
        "reason": reason,
    }


# ---------------------------------------------------------------- vision --


class FindProductByImageArgs(BaseModel):
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
            raise DomainError(
                f"image requires handover: {server_kind}_requires_human"
            )
        raise DomainError(
            f"the photo was classified server-side as {server_kind} — "
            "it is not a product photo"
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


CUSTOMER_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_catalog",
        description=(
            "Search the store catalog. Use it when the customer mentions a "
            "product, a type, or specs (color, material, size) — pass their "
            "words as `query` and the specs you understood as `attributes` "
            "(product properties) and `option_values` (variant options like "
            "size). Words match with OR: one matching word is enough, and "
            "`total_matches` tells you how much is out there — many matches "
            "means show the best ones, zero means say nothing matched and "
            "retry once with a single word or a different spelling (تيشرت / "
            "تيشيرت) before telling the customer it is not found. Returns "
            "each variant with product_id, exact price and an availability "
            "status (متوفر / قليل / خلص / هيتجدد) plus the restock phrase "
            "when the item is out of stock. Do NOT use it for anything that "
            "is not a product the store sells."
        ),
        args_schema=SearchCatalogArgs,
        handler=_search_catalog,
        tags=["catalog"],
    ),
    ToolSpec(
        name="get_product_details",
        description=(
            "Full details for ONE product by id: attributes (material, "
            "properties) and every variant with price and availability. Use "
            "it when the customer asks what a product is made of, how it is "
            "cut, or which sizes/colors it has — usually after search_catalog "
            "found it."
        ),
        args_schema=GetProductDetailsArgs,
        handler=_get_product_details,
        tags=["catalog"],
    ),
    ToolSpec(
        name="get_product_photos",
        description=(
            "List one product's gallery image ids (primary image or all). "
            "Returns ids only — the server attaches the actual images to the "
            "reply. Use it when the customer wants to SEE the product."
        ),
        args_schema=GetProductPhotosArgs,
        handler=_get_product_photos,
        tags=["catalog"],
    ),
    ToolSpec(
        name="find_product_by_image",
        description=(
            "Identify a product from the customer's latest photo. Pass the "
            "kind you believe the photo is; the server attaches the photo "
            "itself. Non-product photos are refused with a handover reason."
        ),
        args_schema=FindProductByImageArgs,
        handler=_find_product_by_image,
        tags=["catalog", "vision"],
    ),
    ToolSpec(
        name="get_store_info",
        description=(
            "The store's own published facts: working hours, branches, "
            "shipping, payment, returns, and how to order. Use it for any "
            "question about the store itself or its policies. Returns the "
            "store's knowledge items as title + content — quote them, never "
            "invent a policy."
        ),
        args_schema=GetStoreInfoArgs,
        handler=_get_store_info,
        tags=["store"],
    ),
    ToolSpec(
        name="search_knowledge",
        description=(
            "Semantic search over the store's knowledge base for a specific "
            "question. Use it when the customer asks about a policy or detail "
            "that get_store_info's titles do not cover."
        ),
        args_schema=SearchKnowledgeArgs,
        handler=_search_knowledge,
        tags=["knowledge"],
    ),
    ToolSpec(
        name="handover_to_human",
        description=(
            "Escalate this conversation to a human staff member. Use it when: "
            "you tried to solve the customer's problem and could not "
            "(complex_problem); the store's data does not have what you need "
            "(missing_data); the customer explicitly asks for a person "
            "(customer_request); the customer is complaining about the store, "
            "an order or the service (complaint); or the customer wants to "
            "PLACE or CHANGE an order — selling is staff work "
            "(purchase_intent). Pass `reason` and a `summary` saying what you "
            "tried and what is missing — the staff reads it before opening "
            "the chat. After calling it, write one short natural reply "
            "telling the customer a team member will continue with them."
        ),
        args_schema=HandoverToHumanArgs,
        handler=_handover_to_human,
        tags=["escalation"],
        risk_level="MEDIUM",
    ),
]


def register_customer_tools() -> list[ToolSpec]:
    """Register all customer agent tools into the central platform registry."""
    for spec in CUSTOMER_TOOL_SPECS:
        register_tool(spec)
    return CUSTOMER_TOOL_SPECS

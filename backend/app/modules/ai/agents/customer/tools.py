"""Customer Agent tool implementations and specs.

All 11 tools exposed to or usable by the Customer Agent:
- Catalog / Inventory: search_products, get_variant_price, check_stock
- Vision / Media: find_product_by_image, resolve_product_media
- Orders / Quotes: create_order, get_order
- Knowledge Base: search_knowledge
- Customer Context: get_customer
- Operational Side Effects: add_task, add_tag
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from app.core.sql import LIKE_ESCAPE, like_pattern
from app.core.storage import get_storage
from app.modules.ai.agents.customer.vision.schemas import ImageKind
from app.modules.ai.tools import ToolSpec, register_tool
from app.modules.catalog.models import Product, ProductImage, ProductVariant
from app.modules.inventory.models import InventoryBalance


def _order_deps():
    """OrderService and its sellable-status vocabulary, from ONE lazy import."""
    from app.modules.orders.service import SELLABLE_PRODUCT_STATUSES, OrderService

    return OrderService, SELLABLE_PRODUCT_STATUSES


def sellable_product_statuses() -> frozenset[str]:
    """The checkout gate's sellable vocabulary, for in-module readers."""
    _, statuses = _order_deps()
    return statuses


def _order_service():
    """OrderService, imported lazily so the registry works without orders."""
    OrderService, _ = _order_deps()
    return OrderService


def _customer_service():
    """CustomerService, imported lazily (customers owns customer data)."""
    from app.modules.customers.service import CustomerService

    return CustomerService


def _task_model():
    """The operations Task model, imported lazily (operations owns tasks)."""
    from app.modules.operations.models import Task

    return Task


def _parse_bound_id(raw: object) -> uuid.UUID | None:
    """Parse a server-side id from the context; malformed is a tool error."""
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise DomainError("bound customer is not a valid id") from exc


def _bound_customer_id(context: dict | None) -> uuid.UUID:
    """§132: the ONLY customer a scoped tool may touch."""
    customer_id = _parse_bound_id((context or {}).get("customer_id"))
    if customer_id is None:
        raise DomainError("no customer bound to this conversation")
    return customer_id


def _money(value) -> str | None:
    """Money is Decimal(Numeric(14,2)) — serialized exactly, never as float."""
    return None if value is None else str(value)


# ----------------------------------------------------------------- handlers --


class SearchProductsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=255)
    attributes: dict[str, str | int | float | bool] | None = None
    option_values: dict[str, str | int | float | bool] | None = None
    limit: int = Field(default=5, ge=1, le=20)


async def _search_products(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    query: str,
    attributes: dict[str, object] | None = None,
    option_values: dict[str, object] | None = None,
    limit: int = 5,
) -> dict:
    _, sellable_statuses = _order_deps()
    pattern = like_pattern(query)
    ts_query = func.plainto_tsquery(literal_column("'simple'"), query)

    conditions = [
        ProductVariant.tenant_id == tenant_id,
        ProductVariant.is_active.is_(True),
        Product.status.in_(sellable_statuses),
        or_(
            Product.search_ts.op("@@")(ts_query),
            Product.title.ilike(pattern, escape=LIKE_ESCAPE),
            ProductVariant.title.ilike(pattern, escape=LIKE_ESCAPE),
            ProductVariant.sku.ilike(pattern, escape=LIKE_ESCAPE),
        ),
    ]
    if attributes:
        conditions.append(Product.attributes.contains(attributes))
    if option_values:
        conditions.append(ProductVariant.option_values.contains(option_values))

    stmt = (
        select(ProductVariant, Product.title)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(*conditions)
        .order_by(Product.title.asc(), ProductVariant.id.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return {
        "results": [
            {
                "variant_id": str(variant.id),
                "title": variant.title or product_title,
                "sku": variant.sku,
                "price": _money(variant.price),
            }
            for variant, product_title in rows
        ]
    }


class GetVariantPriceArgs(BaseModel):
    variant_id: uuid.UUID


async def _get_variant_price(
    session: AsyncSession, tenant_id: uuid.UUID, *, variant_id: uuid.UUID
) -> dict:
    _, sellable_statuses = _order_deps()
    row = (
        await session.execute(
            select(ProductVariant, Product.title)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.id == variant_id,
                ProductVariant.is_active.is_(True),
                Product.status.in_(sellable_statuses),
            )
        )
    ).first()
    if row is None:
        raise NotFoundError(f"variant {variant_id} not found")
    variant, product_title = row
    return {
        "variant_id": str(variant.id),
        "title": variant.title or product_title,
        "sku": variant.sku,
        "price": _money(variant.price),
    }


class CheckStockArgs(BaseModel):
    variant_id: uuid.UUID


async def _check_stock(
    session: AsyncSession, tenant_id: uuid.UUID, *, variant_id: uuid.UUID
) -> dict:
    _, sellable_statuses = _order_deps()
    variant = (
        await session.execute(
            select(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.id == variant_id,
                ProductVariant.is_active.is_(True),
                Product.status.in_(sellable_statuses),
            )
        )
    ).scalar_one_or_none()
    if variant is None:
        raise NotFoundError(f"variant {variant_id} not found")

    available = (
        await session.execute(
            select(
                func.coalesce(func.sum(InventoryBalance.on_hand - InventoryBalance.reserved), 0)
            ).where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.variant_id == variant_id,
            )
        )
    ).scalar_one()
    return {
        "variant_id": str(variant_id),
        "sku": variant.sku,
        "available": int(available),
    }


class CreateOrderItemArgs(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(ge=1, le=999)


class CreateOrderArgs(BaseModel):
    items: list[CreateOrderItemArgs] = Field(min_length=1)


async def _create_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    items: list[dict],
    channel: str = "ai",
    context: dict | None = None,
) -> dict:
    customer_id = _bound_customer_id(context)
    conversation_id = _parse_bound_id((context or {}).get("conversation_id"))
    if conversation_id is None:
        raise DomainError("no conversation bound to this tool call")
    bound_quote_id = _parse_bound_id((context or {}).get("confirmed_quote_id"))
    if bound_quote_id is not None:
        return await _execute_confirmed_order(
            session,
            tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            quote_id=bound_quote_id,
            channel=channel,
        )
    return await _propose_quote(
        session,
        tenant_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        requested_items=items,
    )


async def _execute_confirmed_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    customer_id: uuid.UUID,
    conversation_id: uuid.UUID,
    quote_id: uuid.UUID,
    channel: str,
) -> dict:
    from app.modules.ai.models import AIOrderQuote

    quote = (
        await session.execute(
            select(AIOrderQuote).where(
                AIOrderQuote.tenant_id == tenant_id,
                AIOrderQuote.id == quote_id,
                AIOrderQuote.conversation_id == conversation_id,
                AIOrderQuote.customer_id == customer_id,
                AIOrderQuote.status == "confirmed",
            )
        )
    ).scalar_one_or_none()
    if quote is None:
        raise DomainError(
            "create_order requires a confirmed quote — the customer has not "
            "confirmed this order yet"
        )
    if quote.expires_at is not None and quote.expires_at <= datetime.now(UTC):
        raise DomainError("the confirmed quote expired — propose a fresh quote")

    try:
        OrderService = _order_service()
    except ImportError as exc:
        raise DomainError("orders unavailable") from exc
    order = await OrderService.create_order(
        session,
        tenant_id,
        customer_id,
        [
            {"variant_id": uuid.UUID(str(item["variant_id"])), "quantity": int(item["quantity"])}
            for item in (quote.items or [])
        ],
        channel=channel,
    )
    quote.status = "consumed"
    quote.consumed_at = datetime.now(UTC)
    await session.flush()
    return {
        "order_id": str(order.id),
        "number": order.number,
        "status": order.status,
        "grand_total": _money(order.grand_total),
        "quote_id": str(quote.id),
    }


async def _propose_quote(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    customer_id: uuid.UUID,
    conversation_id: uuid.UUID,
    requested_items: list[dict],
) -> dict:
    from app.modules.ai.agents.customer.confirmation import live_quote, mint_quote, quote_payload

    existing = await live_quote(
        session, tenant_id, conversation_id=conversation_id, customer_id=customer_id
    )
    if existing is not None:
        return quote_payload(existing)

    _, sellable_statuses = _order_deps()
    priced: list[dict] = []
    total = Decimal("0")
    for item in requested_items:
        variant_id = uuid.UUID(str(item["variant_id"]))
        quantity = int(item["quantity"])
        row = (
            await session.execute(
                select(ProductVariant, Product.status)
                .join(Product, Product.id == ProductVariant.product_id)
                .where(
                    ProductVariant.tenant_id == tenant_id,
                    ProductVariant.id == variant_id,
                )
            )
        ).first()
        if row is None:
            raise NotFoundError(f"variant {variant_id} not found")
        variant, product_status = row
        if product_status not in sellable_statuses or not variant.is_active:
            raise ConflictError(
                f"variant {variant_id} is not on sale (product status "
                f"{product_status or 'missing'}, variant active={variant.is_active})"
            )
        line_total = variant.price * quantity
        total += line_total
        priced.append(
            {
                "variant_id": str(variant_id),
                "quantity": quantity,
                "unit_price": _money(variant.price),
                "line_total": _money(line_total),
            }
        )

    quote = await mint_quote(
        session,
        tenant_id,
        conversation_id=conversation_id,
        customer_id=customer_id,
        items=priced,
        grand_total=total,
    )
    return quote_payload(quote)


class GetCustomerArgs(BaseModel):
    """No arguments — §132: the customer is the conversation's, not the model's."""


async def _get_customer(
    session: AsyncSession, tenant_id: uuid.UUID, *, context: dict | None = None
) -> dict:
    customer_id = _bound_customer_id(context)
    customer = await _customer_service().get(session, tenant_id, customer_id)
    return {
        "customer_id": str(customer.id),
        "name": customer.name,
        "locale": customer.locale,
    }


class GetOrderArgs(BaseModel):
    order_id: uuid.UUID


async def _get_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    order_id: uuid.UUID,
    context: dict | None = None,
) -> dict:
    customer_id = _bound_customer_id(context)
    order = await _order_service().get(session, tenant_id, order_id, with_items=True)
    if order.customer_id != customer_id:
        raise NotFoundError(f"order {order_id} not found")
    return {
        "order_id": str(order.id),
        "number": order.number,
        "status": order.status,
        "currency": order.currency,
        "grand_total": _money(order.grand_total),
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "items": [
            {
                "title": item.title,
                "sku": item.sku,
                "quantity": item.quantity,
                "unit_price": _money(item.unit_price),
                "total": _money(item.total),
            }
            for item in (getattr(order, "items", None) or [])
        ],
    }


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

    allowed, handoff_reason = classify(image_kind)
    if not allowed:
        raise DomainError(f"image requires handover: {handoff_reason}")
    image_url = (context or {}).get("customer_image")
    if not image_url:
        raise DomainError("no customer image in this turn")

    result = await run_vision_match(session, tenant_id, image_url=image_url, text_hint=hints)
    return {
        "confidence": result.confidence.value,
        "candidates": result.candidates,
        "reason": result.reason,
    }


class ResolveProductMediaArgs(BaseModel):
    product_id: uuid.UUID
    selection: Literal["primary", "all"] = "primary"


async def _resolve_product_media(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    product_id: uuid.UUID,
    selection: Literal["primary", "all"] = "primary",
) -> dict:
    _, sellable_statuses = _order_deps()
    product_exists = (
        await session.execute(
            select(Product.id).where(
                Product.tenant_id == tenant_id,
                Product.id == product_id,
                Product.status.in_(sellable_statuses),
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


class AddTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    due_date: datetime | None = None
    priority: int = Field(default=2, ge=1, le=3)


async def _add_task(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    title: str,
    description: str | None = None,
    due_date: datetime | None = None,
    priority: int = 2,
    context: dict | None = None,
) -> dict:
    from app.modules.operations.task_service import TaskService

    customer_id = _parse_bound_id((context or {}).get("customer_id"))
    task = await TaskService.create_task(
        session,
        tenant_id,
        title=title,
        description=description,
        due_date=due_date,
        priority=priority,
        source="ai",
        created_by="ai",
        related_entity_type="customer" if customer_id else None,
        related_entity_id=customer_id,
    )
    return {
        "task_id": str(task.id),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
    }


class AddTagArgs(BaseModel):
    tag: str = Field(min_length=1, max_length=63)


async def _add_tag(
    session: AsyncSession, tenant_id: uuid.UUID, *, tag: str, context: dict | None = None
) -> dict:
    customer_id = _bound_customer_id(context)
    created = await _customer_service().add_tag(session, tenant_id, customer_id, tag)
    return {"customer_id": str(customer_id), "tag": created.name}


async def media_payload_for_ids(
    session: AsyncSession, tenant_id: uuid.UUID, image_ids: list[str]
) -> list[dict]:
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
        name="search_products",
        description=(
            "Search the tenant catalog. Pass the customer's words as `query`, and any "
            "specs they named as structured filters: `attributes` for product properties "
            "(color, material) and `option_values` for variant options (size). Returns "
            "variant, sku and price."
        ),
        args_schema=SearchProductsArgs,
        handler=_search_products,
        tags=["catalog"],
    ),
    ToolSpec(
        name="get_variant_price",
        description="Look up the current price of one product variant by id.",
        args_schema=GetVariantPriceArgs,
        handler=_get_variant_price,
        tags=["catalog"],
    ),
    ToolSpec(
        name="check_stock",
        description="Available stock (on hand minus reserved) for a variant, all warehouses.",
        args_schema=CheckStockArgs,
        handler=_check_stock,
        tags=["inventory"],
    ),
    ToolSpec(
        name="create_order",
        description=(
            "Place an order for the conversation's customer (server-bound). "
            "Two-phase: a call without a confirmed quote PROPOSES — it returns "
            "a priced quote with a 6-digit confirmation code the customer must "
            "type in chat; no order exists yet. Once the customer's own message "
            "carries the code, call create_order again to execute the confirmed "
            "quote's items (the execution needs merchant approval)."
        ),
        args_schema=CreateOrderArgs,
        handler=_create_order,
        tags=["orders"],
        risk_level="HIGH",
    ),
    ToolSpec(
        name="get_customer",
        description="Details of the customer in this conversation (server-bound).",
        args_schema=GetCustomerArgs,
        handler=_get_customer,
        tags=["customers"],
    ),
    ToolSpec(
        name="get_order",
        description="One order of this conversation's customer, with its line items.",
        args_schema=GetOrderArgs,
        handler=_get_order,
        tags=["orders"],
    ),
    ToolSpec(
        name="search_knowledge",
        description="Search the tenant knowledge base for answers to a question.",
        args_schema=SearchKnowledgeArgs,
        handler=_search_knowledge,
        tags=["knowledge"],
    ),
    ToolSpec(
        name="add_task",
        description="Create a follow-up task for the team (optionally about this customer).",
        args_schema=AddTaskArgs,
        handler=_add_task,
        tags=["operations"],
        risk_level="MEDIUM",
    ),
    ToolSpec(
        name="add_tag",
        description="Add a tag to this conversation's customer.",
        args_schema=AddTagArgs,
        handler=_add_tag,
        tags=["customers"],
        risk_level="MEDIUM",
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
        name="resolve_product_media",
        description=(
            "List one product's gallery image ids (primary image or all). "
            "Returns ids only — the server attaches the actual images to "
            "the reply."
        ),
        args_schema=ResolveProductMediaArgs,
        handler=_resolve_product_media,
        tags=["catalog", "vision"],
    ),
]


def register_customer_tools() -> list[ToolSpec]:
    """Register all customer agent tools into the central platform registry."""
    for spec in CUSTOMER_TOOL_SPECS:
        register_tool(spec)
    return CUSTOMER_TOOL_SPECS

"""AI tool registry — the ONLY path from the LLM to business logic.

Hard rule: the LLM never touches SQL. It may only request one of the tools
registered here; every handler is a tenant-safe application-service call or a
parameter-bound, tenant-scoped select. UUID args are coerced by the pydantic
``args_schema`` before a handler ever runs; no SQL strings are ever built from
model output.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError
from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import InventoryBalance

# (session, tenant_id, **validated kwargs) -> JSON-safe result dict
Handler = Callable[..., Awaitable[dict]]


@dataclass(slots=True)
class ToolSpec:
    """One callable capability exposed to agents."""

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Handler
    # extra metadata surfaced in logs/UI
    tags: list[str] = field(default_factory=list)
    # §135: HIGH-risk tools mutate business state and must pass through a
    # durable ApprovalRequest (human-in-the-loop) before execution; LOW runs
    # inline. See requires_approval().
    risk_level: str = "LOW"


TOOLS: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> ToolSpec:
    TOOLS[spec.name] = spec
    return spec


def get_tool(name: str) -> ToolSpec | None:
    return TOOLS.get(name)


async def requires_approval(spec: ToolSpec) -> bool:
    """§135: True when a call to this tool must wait for human approval.

    The agent runtime awaits this before executing; HIGH tools persist an
    ApprovalRequest (status PENDING) and the run parks in WAITING_APPROVAL
    until a user decides.
    """
    return spec.risk_level == "HIGH"


def tool_to_openai_schema(spec: ToolSpec) -> dict:
    """OpenAI function-calling schema derived from the pydantic args model."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.args_schema.model_json_schema(),
        },
    }


# ----------------------------------------------------------------- handlers --


class SearchProductsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=255)
    limit: int = Field(default=5, ge=1, le=20)


async def _search_products(
    session: AsyncSession, tenant_id: uuid.UUID, *, query: str, limit: int = 5
) -> dict:
    pattern = f"%{query}%"
    stmt = (
        select(ProductVariant, Product.title)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.is_active.is_(True),
            or_(
                ProductVariant.title.ilike(pattern),
                ProductVariant.sku.ilike(pattern),
                Product.title.ilike(pattern),
            ),
        )
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
                "price": float(variant.price),
            }
            for variant, product_title in rows
        ]
    }


class GetVariantPriceArgs(BaseModel):
    variant_id: uuid.UUID


async def _get_variant_price(
    session: AsyncSession, tenant_id: uuid.UUID, *, variant_id: uuid.UUID
) -> dict:
    row = (
        await session.execute(
            select(ProductVariant, Product.title)
            .join(Product, Product.id == ProductVariant.product_id)
            .where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.id == variant_id,
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
        "price": float(variant.price),
    }


class CheckStockArgs(BaseModel):
    variant_id: uuid.UUID


async def _check_stock(
    session: AsyncSession, tenant_id: uuid.UUID, *, variant_id: uuid.UUID
) -> dict:
    variant = (
        await session.execute(
            select(ProductVariant).where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.id == variant_id,
            )
        )
    ).scalar_one_or_none()
    if variant is None:
        raise NotFoundError(f"variant {variant_id} not found")

    available = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(InventoryBalance.on_hand - InventoryBalance.reserved), 0
                )
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
    # §132: customer_id is DELIBERATELY absent — it is injected server-side
    # from the conversation scope, never taken from model arguments.


async def _create_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    items: list[dict],
    channel: str = "ai",
    context: dict | None = None,
) -> dict:
    # Server-side scope binding (§132): the customer is pinned from the
    # conversation context by the runtime — the model cannot choose it.
    customer_id = (context or {}).get("customer_id")
    if not customer_id:
        raise DomainError("no customer bound to this conversation")
    # Lazy import on purpose: the tool stays registered even if the orders
    # module has not landed yet (and tests can monkeypatch this import site).
    try:
        from app.modules.orders.service import OrderService
    except ImportError as exc:
        raise DomainError("orders unavailable") from exc

    order = await OrderService.create_order(
        session,
        tenant_id,
        __import__("uuid").UUID(customer_id),
        [{"variant_id": item["variant_id"], "quantity": item["quantity"]} for item in items],
        channel=channel,
    )
    return {
        "order_id": str(order.id),
        "number": order.number,
        "status": order.status,
        "grand_total": float(order.grand_total),
    }


# ---------------------------------------------------------------- registry ---


def _bootstrap() -> None:
    register_tool(
        ToolSpec(
            name="search_products",
            description="Search the tenant catalog by keyword; returns variant, sku and price.",
            args_schema=SearchProductsArgs,
            handler=_search_products,
            tags=["catalog"],
        )
    )
    register_tool(
        ToolSpec(
            name="get_variant_price",
            description="Look up the current price of one product variant by id.",
            args_schema=GetVariantPriceArgs,
            handler=_get_variant_price,
            tags=["catalog"],
        )
    )
    register_tool(
        ToolSpec(
            name="check_stock",
            description="Available stock (on hand minus reserved) for a variant, all warehouses.",
            args_schema=CheckStockArgs,
            handler=_check_stock,
            tags=["inventory"],
        )
    )
    register_tool(
        ToolSpec(
            name="create_order",
            description="Place an order for a customer from a list of variant/quantity pairs.",
            args_schema=CreateOrderArgs,
            handler=_create_order,
            tags=["orders"],
            risk_level="HIGH",  # §135: mutating tool — human approval required
        )
    )


_bootstrap()

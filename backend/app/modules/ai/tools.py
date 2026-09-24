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
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError, ValidationError
from app.core.sql import LIKE_ESCAPE, like_pattern
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


# ------------------------------------------------- lazy cross-module access --
#
# Every handler that needs another module's code imports it HERE, inside the
# function. The only module-scope cross-module imports left in this file are
# the catalog/inventory models the original read tools already needed.
#
# Two things this buys, and one it does NOT:
#  * the registry imports and lists its tools even when a sibling module is
#    broken or absent;
#  * no MODULE-SCOPE edge is added, which is what a new import cycle is made
#    of (tests/test_module_boundaries.py).
# It does NOT exempt the import from the ratchet's TOTAL count — that test
# counts function-scope imports too. See the note on `_customer_service` /
# `_task_model` below: both are genuinely new edges on the total.


def _order_deps():
    """OrderService and its sellable-status vocabulary, from ONE lazy import.

    The AI browse tool must agree with the sell gate (§M4): a product whose
    status checkout refuses (draft, archived) must not be enumerable by the
    assistant either, and the honest way to agree is to read the SAME
    ``SELLABLE_PRODUCT_STATUSES`` the gate uses, never re-type "active" here.

    Both names ride the import edge ``_create_order`` already has
    (ai -> orders.service): the boundary ratchet counts import EDGES
    (tests/test_module_boundaries.py, total 97), so a second
    ``from app.modules.orders...`` line here would raise the ceiling.
    Naming a second thing at one existing site moves the number zero.
    """
    from app.modules.orders.service import SELLABLE_PRODUCT_STATUSES, OrderService

    return OrderService, SELLABLE_PRODUCT_STATUSES


def _order_service():
    """OrderService, imported lazily so the registry works without orders."""
    OrderService, _ = _order_deps()
    return OrderService


def _customer_service():
    """CustomerService, imported lazily (customers owns customer data).

    A new ratchet edge (ai -> customers.service). The alternative — reading
    the customers table through the models edge knowledge.py already has —
    would couple ai to customers' tables AND duplicate the tag get-or-create
    rule, so the service call is the honest one.
    """
    from app.modules.customers.service import CustomerService

    return CustomerService


def _task_model():
    """The operations Task model, imported lazily (operations owns tasks).

    A new ratchet edge (ai -> operations.models). operations exposes no
    service today, so there is no application-service path to a Task; this is
    the only way to create one from here.
    """
    from app.modules.operations.models import Task

    return Task


def _parse_bound_id(raw: object) -> uuid.UUID | None:
    """Parse a server-side id from the context; malformed is a tool error.

    Returns None when absent. Never raises a bare ValueError — the runtime
    turns a DomainError into a readable tool error for the model.
    """
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise DomainError("bound customer is not a valid id") from exc


def _bound_customer_id(context: dict | None) -> uuid.UUID:
    """§132: the ONLY customer a scoped tool may touch.

    Read from the server-side conversation binding — never from model
    arguments. A tool call with no bound customer is refused outright rather
    than falling back to anything the model supplied.
    """
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
    limit: int = Field(default=5, ge=1, le=20)


async def _search_products(
    session: AsyncSession, tenant_id: uuid.UUID, *, query: str, limit: int = 5
) -> dict:
    # §M4: browse agrees with the sell gate. A variant is visible to the
    # assistant only when its product's status is one checkout would sell —
    # the same frozen vocabulary, imported from orders, not re-typed here.
    _, sellable_statuses = _order_deps()
    # A7: a LIKE term is data, not a pattern — `like_pattern` escapes the `%` and
    # `_` the caller typed, and the escape character is declared so the
    # backslashes are honoured rather than treated as literal text.
    pattern = like_pattern(query)
    stmt = (
        select(ProductVariant, Product.title)
        .join(Product, Product.id == ProductVariant.product_id)
        .where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.is_active.is_(True),
            Product.status.in_(sellable_statuses),
            or_(
                ProductVariant.title.ilike(pattern, escape=LIKE_ESCAPE),
                ProductVariant.sku.ilike(pattern, escape=LIKE_ESCAPE),
                Product.title.ilike(pattern, escape=LIKE_ESCAPE),
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
                # Decimal as a string (§47): a cent-exact price never
                # round-trips through binary float. None stays None.
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
        # Decimal as a string (§47) — the price tool has no more excuse for
        # a float than the order tool never had. None stays None.
        "price": _money(variant.price),
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
    # Checkout's rules — product sellability included (§M4) — belong to
    # OrderService and are deliberately NOT re-checked here: a second, weaker
    # copy is how a draft product gets sold in chat and refused on the
    # dashboard.
    try:
        OrderService = _order_service()
    except ImportError as exc:
        raise DomainError("orders unavailable") from exc

    order = await OrderService.create_order(
        session,
        tenant_id,
        uuid.UUID(str(customer_id)),
        [{"variant_id": item["variant_id"], "quantity": item["quantity"]} for item in items],
        channel=channel,
    )
    return {
        "order_id": str(order.id),
        "number": order.number,
        "status": order.status,
        # Decimal as a string: the same amount the order row holds (§47).
        "grand_total": _money(order.grand_total),
    }


# ------------------------------------------------- customer / order reads ----


class GetCustomerArgs(BaseModel):
    """No arguments — §132: the customer is the conversation's, not the model's."""


async def _get_customer(
    session: AsyncSession, tenant_id: uuid.UUID, *, context: dict | None = None
) -> dict:
    """The bound conversation's customer. The model cannot name a customer."""
    customer_id = _bound_customer_id(context)
    customer = await _customer_service().get(session, tenant_id, customer_id)
    return {
        "customer_id": str(customer.id),
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "locale": customer.locale,
        "is_blocked": customer.is_blocked,
        "lifetime_value": _money(customer.lifetime_value),
    }


class GetOrderArgs(BaseModel):
    # An order id is safe to take from the model: it is resolved tenant-scoped
    # AND re-checked against the bound customer, so it can only ever reach the
    # caller's own order. A foreign id is a plain "not found".
    order_id: uuid.UUID


async def _get_order(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    order_id: uuid.UUID,
    context: dict | None = None,
) -> dict:
    """One order of the bound customer, with its line items."""
    customer_id = _bound_customer_id(context)
    order = await _order_service().get(session, tenant_id, order_id, with_items=True)
    if order.customer_id != customer_id:
        # Belongs to another customer in the same tenant: invisible.
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


# -------------------------------------------------------------- knowledge ----

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
    """Retrieve tenant knowledge for the model (same service as the API route).

    Reuses ``app.modules.ai.knowledge.search_knowledge`` — pgvector cosine
    search, tenant- and visibility-scoped (§157). Visibility is requested
    EXPLICITLY as customer_facing rather than inherited from the service
    default: this is a security boundary (an AI reply must never quote a
    staff-only/internal document), so it must not move when another module
    changes a default. The model cannot ask for anything else — the tool
    exposes no visibility argument.
    """
    from app.modules.ai import knowledge

    try:
        hits = await knowledge.search_knowledge(
            session, tenant_id, query, limit=limit, visibility="customer_facing"
        )
    except ValidationError as exc:
        # A misconfigured embedding model is NOT the same as "nothing matched".
        # Swallowing this made a broken RAG setup indistinguishable from an
        # empty knowledge base, so the model answered "I don't know" instead of
        # something true. Raise: the runtime records a failed tool call and
        # hands the model an explicit error it can act on.
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


# ----------------------------------------------------------- write: tasks ----

class AddTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    due_date: datetime | None = None
    priority: int = Field(default=2, ge=1, le=3)  # 1 high, 2 normal, 3 low


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
    """Create a follow-up Task. Linked to the bound customer when there is one.

    §13-14: routes through TaskService — never constructs the Task model
    directly. This ensures consistent validation, defaults, and future
    hooks (audit, events) are in one place.
    """
    from app.modules.operations.task_service import TaskService

    # Same defensive parse as _bound_customer_id: a malformed binding must be a
    # controlled tool error, not a bare ValueError from uuid.UUID().
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


# ------------------------------------------------------------ write: tags ----

class AddTagArgs(BaseModel):
    tag: str = Field(min_length=1, max_length=63)


async def _add_tag(
    session: AsyncSession, tenant_id: uuid.UUID, *, tag: str, context: dict | None = None
) -> dict:
    """Tag the bound customer (idempotent — the tag row is created on first use)."""
    customer_id = _bound_customer_id(context)
    created = await _customer_service().add_tag(session, tenant_id, customer_id, tag)
    return {"customer_id": str(customer_id), "tag": created.name}


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
    register_tool(
        ToolSpec(
            name="get_customer",
            description="Details of the customer in this conversation (server-bound).",
            args_schema=GetCustomerArgs,
            handler=_get_customer,
            tags=["customers"],
            # read-only
        )
    )
    register_tool(
        ToolSpec(
            name="get_order",
            description="One order of this conversation's customer, with its line items.",
            args_schema=GetOrderArgs,
            handler=_get_order,
            tags=["orders"],
            # read-only
        )
    )
    register_tool(
        ToolSpec(
            name="search_knowledge",
            description="Search the tenant knowledge base for answers to a question.",
            args_schema=SearchKnowledgeArgs,
            handler=_search_knowledge,
            tags=["knowledge"],
            # read-only
        )
    )
    register_tool(
        ToolSpec(
            name="add_task",
            description="Create a follow-up task for the team (optionally about this customer).",
            args_schema=AddTaskArgs,
            handler=_add_task,
            tags=["operations"],
            risk_level="MEDIUM",  # creates a record
        )
    )
    register_tool(
        ToolSpec(
            name="add_tag",
            description="Add a tag to this conversation's customer.",
            args_schema=AddTagArgs,
            handler=_add_tag,
            tags=["customers"],
            risk_level="MEDIUM",  # mutates the customer record
        )
    )


_bootstrap()

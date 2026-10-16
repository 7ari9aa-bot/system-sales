"""AI tool registry — the central engine connecting LLMs to business logic.

Hard rule: the LLM never touches SQL. It may only request one of the tools
registered here; every handler is a tenant-safe application-service call or a
parameter-bound, tenant-scoped select. UUID args are coerced by the pydantic
``args_schema`` before a handler ever runs; no SQL strings are ever built from
model output.

This module houses the core registry mechanics (ToolSpec, registration, OpenAI
schema conversion, approval checks). Individual agent tools live with their
respective agents:
- Customer tools: ``app.modules.ai.agents.customer.tools``
- Sales Intelligence tools: ``app.modules.ai.agents.sales_intelligence.tools``

All historical customer tool symbols and handlers are re-exported here for 100%
backward compatibility.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

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


async def requires_approval(spec: ToolSpec, context: dict | None = None) -> bool:
    """§135: True when THIS call must wait for human approval before it runs.

    The agent runtime awaits this before executing; HIGH tools persist an
    ApprovalRequest (status PENDING) and the run parks in WAITING_APPROVAL
    until a user decides.

    P1-10 phase awareness: create_order without a bound confirmed quote only
    PROPOSES — it mints a priced quote the customer must confirm by typing
    the server-minted code, and no order row can exist from that call. There
    is nothing for a merchant to approve yet, so it runs inline. The
    EXECUTION call (the coordinator binds the confirmed quote's id into the
    server-side context) still parks: a human signs off on the exact order
    the customer confirmed.
    """
    if spec.risk_level != "HIGH":
        return False
    if spec.name == "create_order" and not (context or {}).get("confirmed_quote_id"):
        return False
    return True


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


# ------------------------------------------------------------- bootstrapping --


def _bootstrap() -> None:
    """Register default built-in tools."""
    from app.modules.ai.agents.customer.tools import register_customer_tools

    register_customer_tools()


_bootstrap()


# ---------------------------------------------------------------- re-exports --
#
# Re-exported from app.modules.ai.agents.customer.tools for backward compatibility
# with existing callers and tests.

from app.modules.ai.agents.customer.tools import (  # noqa: E402, F401
    AddTaskArgs,
    AddTagArgs,
    CheckStockArgs,
    CreateOrderArgs,
    CreateOrderItemArgs,
    FindProductByImageArgs,
    GetCustomerArgs,
    GetOrderArgs,
    GetVariantPriceArgs,
    ResolveProductMediaArgs,
    SearchKnowledgeArgs,
    SearchProductsArgs,
    _add_tag,
    _add_task,
    _bound_customer_id,
    _check_stock,
    _create_order,
    _customer_service,
    _execute_confirmed_order,
    _find_product_by_image,
    _get_customer,
    _get_order,
    _get_variant_price,
    _money,
    _order_deps,
    _order_service,
    _parse_bound_id,
    _propose_quote,
    _resolve_product_media,
    _search_knowledge,
    _search_products,
    _task_model,
    media_payload_for_ids,
    sellable_product_statuses,
)

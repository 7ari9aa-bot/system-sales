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
    until a user decides. LOW/MEDIUM tools run inline — MEDIUM marks
    light-touch side effects (the handover write) that are idempotent by
    design and need no human sign-off.
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
    FindProductByImageArgs,
    GetProductDetailsArgs,
    GetProductPhotosArgs,
    GetStoreInfoArgs,
    HandoverToHumanArgs,
    SearchCatalogArgs,
    SearchKnowledgeArgs,
    _find_product_by_image,
    _get_product_details,
    _get_product_photos,
    _get_store_info,
    _handover_to_human,
    _money,
    _parse_bound_id,
    _search_catalog,
    _search_knowledge,
    media_payload_for_ids,
    sellable_product_statuses,
)

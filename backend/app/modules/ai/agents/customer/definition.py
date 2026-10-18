"""Agent Definition — Customer.

Registers the ``customer`` kind with the platform registry.
Import triggers registration (used by ``discover_agents``).
"""

from __future__ import annotations

from app.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry

# LANGUAGE-ONLY (scope cut, 2026-10-18): the customer agent answers from store
# data and escalates — it never sells, never mutates records. The sales cycle
# (orders, quotes, tags, tasks) is staff work via handover; those tools were
# removed from this kind. The one non-read tool is handover_to_human, whose
# side effect is the handover write itself.
CUSTOMER_TOOLS = [
    "search_catalog",
    "get_product_details",
    "get_product_photos",
    "find_product_by_image",
    "get_store_info",
    "search_knowledge",
    "handover_to_human",
]

# Canonical system prompt defined in dedicated prompts.py module
from app.modules.ai.agents.customer.prompts import CUSTOMER_SYSTEM_PROMPT  # noqa: E402

_DEFINITION = AgentDefinition(
    kind="customer",
    name="Customer Service Agent",
    description=(
        "Answers customer questions from trusted store data: catalog search "
        "with prices and availability, product details and photos, vision "
        "matching, store policies. Language-only — it tries to solve, and "
        "escalates to human staff when it cannot or the data is missing."
    ),
    capabilities=[
        AgentCapability(
            name="search_catalog",
            description="Search products with price and availability",
            required=True,
        ),
        AgentCapability(
            name="get_product_details",
            description="Full product details and variants",
            required=True,
        ),
        AgentCapability(
            name="get_product_photos",
            description="Retrieve product gallery photos",
            required=False,
        ),
        AgentCapability(
            name="find_product_by_image", description="Match product from image", required=False
        ),
        AgentCapability(
            name="get_store_info",
            description="Store facts: hours, branches, shipping, payment, returns",
            required=False,
        ),
        AgentCapability(
            name="search_knowledge", description="Search store knowledge base", required=False
        ),
        AgentCapability(
            name="handover_to_human",
            description="Escalate the conversation to human staff",
            required=True,
        ),
    ],
    system_prompt_template=CUSTOMER_SYSTEM_PROMPT,
    default_model="fast",
    enforce_grounding=True,
    default_tools=CUSTOMER_TOOLS,
    allowed_tools=CUSTOMER_TOOLS,
    task_types=[
        "customer_inquiry",
        "product_search",
        "vision_match",
        "voice_turn",
    ],
    guardrail_profile="customer",
    provisioning_policy={
        "is_canonical": True,
        "auto_provision": True,
        "singleton_per_tenant": True,
    },
)

AgentRegistry.register(_DEFINITION)

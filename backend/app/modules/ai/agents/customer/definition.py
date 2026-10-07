"""Agent Definition — Customer.

Registers the ``customer`` kind with the platform registry.
Import triggers registration (used by ``discover_agents``).
"""

from __future__ import annotations

from app.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry

CUSTOMER_TOOLS = [
    "search_products",
    "get_variant_price",
    "check_stock",
    "create_order",
    "get_customer",
    "get_order",
    "search_knowledge",
    "add_task",
    "add_tag",
    "find_product_by_image",
    "resolve_product_media",
]

_DEFINITION = AgentDefinition(
    kind="customer",
    name="Customer Service Agent",
    description=(
        "Handles customer inquiries, catalog search, orders, tasks, "
        "and vision-based product matching."
    ),
    capabilities=[
        AgentCapability(
            name="create_order", description="Place an order for the customer", required=True
        ),
        AgentCapability(
            name="get_customer", description="Read current customer profile", required=True
        ),
        AgentCapability(name="get_order", description="Read customer order details", required=True),
        AgentCapability(
            name="search_products", description="Search products in catalog", required=True
        ),
        AgentCapability(
            name="get_variant_price", description="Check variant price", required=False
        ),
        AgentCapability(
            name="check_stock", description="Check inventory availability", required=False
        ),
        AgentCapability(
            name="search_knowledge", description="Search store knowledge base", required=False
        ),
        AgentCapability(
            name="resolve_product_media",
            description="Retrieve product gallery photos",
            required=False,
        ),
        AgentCapability(
            name="add_task", description="Create follow-up operational task", required=False
        ),
        AgentCapability(name="add_tag", description="Add tag to customer record", required=False),
        AgentCapability(
            name="find_product_by_image", description="Match product from image", required=False
        ),
    ],
    system_prompt_template="You are a helpful sales assistant.",
    default_model="fast",
    enforce_grounding=True,
    default_tools=CUSTOMER_TOOLS,
    allowed_tools=CUSTOMER_TOOLS,
    task_types=[
        "customer_inquiry",
        "order_placement",
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

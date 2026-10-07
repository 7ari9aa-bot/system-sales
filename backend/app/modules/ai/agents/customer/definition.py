"""Agent Definition — Customer.

Registers the ``customer`` kind with the platform registry.
Import triggers registration (used by ``discover_agents``).
"""
from __future__ import annotations

from app.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry


_DEFINITION = AgentDefinition(
    kind="customer",
    name="Customer Service Agent",
    description="Handles customer inquiries, orders, product search, and vision-based product matching.",
    capabilities=[
        AgentCapability(name="place_order", required=True),
        AgentCapability(name="get_customer", required=True),
        AgentCapability(name="get_order", required=True),
        AgentCapability(name="search_products", required=True),
        AgentCapability(name="resolve_product_media", required=False),
        AgentCapability(name="create_task", required=False),
        AgentCapability(name="tag_customer", required=False),
        AgentCapability(name="match_vision", required=False),
    ],
    # Customer agents use the DB-stored system_prompt from the Agent row;
    # this template is only a fallback for seed / auto-provisioning.
    system_prompt_template="You are a helpful sales assistant.",
    default_model="fast",
    enforce_grounding=True,
    default_tools=[
        "place_order",
        "get_customer",
        "get_order",
        "search_products",
        "resolve_product_media",
        "create_task",
        "tag_customer",
        "match_vision",
    ],
)

AgentRegistry.register(_DEFINITION)

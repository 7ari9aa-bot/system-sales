"""Agent Definition — Sales Intelligence.

Registers the ``sales_intelligence`` kind with the platform registry.
Import triggers registration (used by ``discover_agents``).
"""

from __future__ import annotations

from app.applications.apparel.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT
from app.applications.apparel.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
from app.applications.apparel.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry

_DEFINITION = AgentDefinition(
    kind="sales_intelligence",
    name="Sales Intelligence Agent",
    description=(
        "Analyzes sales data, metrics, trends, fulfillment,"
        " and drivers to provide actionable business intelligence."
    ),
    capabilities=[
        AgentCapability(
            name="si_metric",
            description=(
                "Sales numbers: one metric's value, comparison or split; why revenue moved; "
                "who contacted the shop; what the shop recorded"
            ),
            required=True,
        ),
        AgentCapability(
            name="si_shop",
            description=(
                "The shop's records: best sellers, stock, the cashier, one order, one customer"
            ),
            required=False,
        ),
        AgentCapability(
            name="si_finance",
            description="What the shop spent, earned after costs, bought and owes its suppliers",
            required=False,
        ),
        AgentCapability(
            name="si_cashier",
            description=(
                "The till's cash: drawer movements, expected versus counted cash, shortages and "
                "overages, reconciliation per payment method, hand-overs, daily per device"
            ),
            required=False,
        ),
    ],
    system_prompt_template=SI_SYSTEM_PROMPT,
    default_model="strong",
    enforce_grounding=False,
    default_tools=list(SI_TOOLS),
    allowed_tools=list(SI_TOOLS),
    task_types=["metric_query", "deep_analysis", "scheduled_report", "trend_breakdown"],
    guardrail_profile="analytics",
    provisioning_policy={
        "is_canonical": True,
        "auto_provision": True,
        "singleton_per_tenant": True,
    },
)

AgentRegistry.register(_DEFINITION)

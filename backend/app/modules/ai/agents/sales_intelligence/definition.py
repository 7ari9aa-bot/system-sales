"""Agent Definition — Sales Intelligence.

Registers the ``sales_intelligence`` kind with the platform registry.
Import triggers registration (used by ``discover_agents``).
"""

from __future__ import annotations

from app.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT
from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
from app.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry

_DEFINITION = AgentDefinition(
    kind="sales_intelligence",
    name="Sales Intelligence Agent",
    description=(
        "Analyzes sales data, metrics, trends, fulfillment,"
        " and drivers to provide actionable business intelligence."
    ),
    capabilities=[
        AgentCapability(
            name="si_get_metric", description="Query specific metric window", required=True
        ),
        AgentCapability(
            name="si_compare_periods",
            description="Compare current period to previous window",
            required=True,
        ),
        AgentCapability(
            name="si_breakdown", description="Dimension breakdown for metrics", required=False
        ),
        AgentCapability(
            name="si_analyze_drivers", description="Revenue driver decomposition", required=False
        ),
        AgentCapability(
            name="si_explain_metric",
            description="Metric definition and attribution",
            required=False,
        ),
        AgentCapability(
            name="si_data_status", description="Store data freshness and maturity", required=False
        ),
        AgentCapability(
            name="si_analyze_seasonality",
            description="Weekday mix and seasonality analysis",
            required=False,
        ),
        AgentCapability(
            name="si_analyze_customers",
            description="New vs returning customers analysis",
            required=False,
        ),
        AgentCapability(
            name="si_analyze_fulfillment",
            description="Carrier delivery and rejection rates",
            required=False,
        ),
        AgentCapability(
            name="si_top_products",
            description="Best-selling variants with units, revenue, sizes and colors",
            required=False,
        ),
        AgentCapability(
            name="si_stock_status",
            description="Stock left: out, running low, unsold, and not tracked",
            required=False,
        ),
        AgentCapability(
            name="si_expenses_summary",
            description="What the shop spent: total, by category and method",
            required=False,
        ),
        AgentCapability(
            name="si_profit_summary",
            description="Revenue, cost, expenses and profit, only when costs are known",
            required=False,
        ),
        AgentCapability(
            name="si_purchasing_summary",
            description="What the shop bought and what it owes its suppliers",
            required=False,
        ),
        AgentCapability(
            name="si_cashier_summary",
            description="What the cashier sold and refunded, per cashier and hour, and open shifts",
            required=False,
        ),
        AgentCapability(
            name="si_find_order",
            description="Find an order by number, customer name or phone",
            required=False,
        ),
        AgentCapability(
            name="si_find_customer",
            description="Find a customer by name, phone or email with their spend and orders",
            required=False,
        ),
        AgentCapability(
            name="si_customer_activity",
            description="Customers who contacted the store, with conversation volume",
            required=False,
        ),
        AgentCapability(
            name="si_channel_activity",
            description="Interaction volume per connected platform",
            required=False,
        ),
        AgentCapability(
            name="si_social_comments",
            description="Public comments on the store's social posts",
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

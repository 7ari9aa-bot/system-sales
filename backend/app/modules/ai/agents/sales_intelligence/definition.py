"""Agent Definition — Sales Intelligence.

Registers the ``sales_intelligence`` kind with the platform registry.
Import triggers registration (used by ``discover_agents``).
"""
from __future__ import annotations

from app.modules.ai.agents.sales_intelligence.agent import SI_SYSTEM_PROMPT
from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
from app.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry

_DEFINITION = AgentDefinition(
    kind="sales_intelligence",
    name="Sales Intelligence Agent",
    description="Analyzes sales data, metrics, trends, fulfillment, and drivers to provide actionable business intelligence.",
    capabilities=[
        AgentCapability(name="si_get_metric", description="Query specific metric window", required=True),
        AgentCapability(name="si_compare_periods", description="Compare current period to previous window", required=True),
        AgentCapability(name="si_breakdown", description="Dimension breakdown for metrics", required=False),
        AgentCapability(name="si_analyze_drivers", description="Revenue driver decomposition", required=False),
        AgentCapability(name="si_explain_metric", description="Metric definition and attribution", required=False),
        AgentCapability(name="si_data_status", description="Store data freshness and maturity", required=False),
        AgentCapability(name="si_analyze_seasonality", description="Weekday mix and seasonality analysis", required=False),
        AgentCapability(name="si_analyze_customers", description="New vs returning customers analysis", required=False),
        AgentCapability(name="si_analyze_fulfillment", description="Carrier delivery and rejection rates", required=False),
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

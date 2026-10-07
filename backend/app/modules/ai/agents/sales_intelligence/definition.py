"""Agent Definition — Sales Intelligence.

Registers the ``sales_intelligence`` kind with the platform registry.
Import triggers registration (used by ``discover_agents``).
"""
from __future__ import annotations

from app.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry

# Lazy-import the prompt constant so the heavy agent module is only pulled in
# at definition time (startup), not at every import of this file.
from app.modules.ai.agents.sales_intelligence.agent import SI_SYSTEM_PROMPT


_DEFINITION = AgentDefinition(
    kind="sales_intelligence",
    name="Sales Intelligence Agent",
    description="Analyzes sales data, metrics, and trends to answer business questions.",
    capabilities=[
        AgentCapability(name="analyze_metric_trend", required=True),
        AgentCapability(name="list_available_metrics", required=True),
        AgentCapability(name="compare_segments", required=False),
    ],
    system_prompt_template=SI_SYSTEM_PROMPT,
    default_model="strong",
    default_tools=[
        "analyze_metric_trend",
        "list_available_metrics",
        "compare_segments",
    ],
)

AgentRegistry.register(_DEFINITION)

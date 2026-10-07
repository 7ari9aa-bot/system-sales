"""Extensible Multi-Agent Platform Core Registry.

This registry is the Single Source of Truth for all Agent Definitions in the
platform. It maps an agent ``kind`` (e.g. ``customer``, ``sales_intelligence``,
``inventory``) to its comprehensive definition — capabilities, security boundaries,
task types, guardrail profiles, default model, system prompt template, and lifecycle hooks.

Architecture invariants
-----------------------
* **The core runtime MUST NOT know domain details.** It resolves an agent's
  ``kind`` through this registry and delegates to the matching definition.
* **No hardcode for agent counts.** Adding a new agent means registering a
  new ``AgentDefinition``; no platform-wide rewrite required.
* **Security boundary by definition.** The runtime strictly enforces tool authorization
  against ``allowed_tools``; an agent cannot execute unauthorized tools even if linked in DB.
* **Fail-Closed by default.** Duplicate registrations or broken definitions halt startup
  rather than running in an invalid, degraded state.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────── data models ──


class AgentCapability(BaseModel):
    """One named capability an agent advertises (e.g. ``create_order``)."""

    name: str
    description: str | None = None
    required: bool = False


class AgentDefinition(BaseModel):
    """Immutable blueprint of one agent kind.

    The runtime reads these to enforce tool authorization, determine guardrail profiles,
    inject system prompts, and resolve model aliases.
    """

    kind: str
    name: str
    description: str
    definition_version: int = 1
    capabilities: list[AgentCapability] = Field(default_factory=list)
    system_prompt_template: str = ""
    default_model: str = "fast"
    enforce_grounding: bool = False

    # Tool names this kind is authorized to execute (security boundary)
    # If empty, all tools in default_tools and capabilities are permitted.
    allowed_tools: list[str] = Field(default_factory=list)

    # Tool names this kind automatically gets provisioned with
    default_tools: list[str] = Field(default_factory=list)

    # Architectural extensions
    task_types: list[str] = Field(default_factory=list)
    guardrail_profile: str = "default"  # "customer" | "analytics" | "internal" | "default"
    context_builder: str | None = None  # Dotted-path or callable identifier
    output_policy: dict[str, Any] = Field(default_factory=dict)
    provisioning_policy: dict[str, Any] = Field(
        default_factory=lambda: {
            "is_canonical": False,
            "auto_provision": False,
            "singleton_per_tenant": True,
        }
    )
    configuration_schema: dict[str, Any] = Field(default_factory=dict)
    lifecycle: dict[str, Any] = Field(default_factory=dict)

    # Dotted-path strings to async callables:
    #   (session, tenant_id, agent, **kw) → None
    pre_run_hook: str | None = None
    post_run_hook: str | None = None

    # Extra metadata the domain package wants to attach
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Ensure allowed_tools includes at least default_tools and declared capabilities."""
        effective_allowed = set(self.allowed_tools)
        effective_allowed.update(self.default_tools)
        for cap in self.capabilities:
            effective_allowed.add(cap.name)
        self.allowed_tools = sorted(effective_allowed)


# ──────────────────────────────────────────────────────── registry ──


class AgentRegistry:
    """Process-global, class-level registry — fail-closed single source of truth."""

    _definitions: dict[str, AgentDefinition] = {}

    @classmethod
    def register(cls, definition: AgentDefinition, *, allow_override: bool = False) -> None:
        """Register an agent definition. Fail-closed on duplicate registration."""
        if definition.kind in cls._definitions and not allow_override:
            raise ValueError(
                f"Duplicate registration forbidden: agent kind '{definition.kind}' "
                f"is already registered ({cls._definitions[definition.kind].name})."
            )
        cls._definitions[definition.kind] = definition
        logger.info(
            "agent_registry.registered kind=%s name=%s tools=%d",
            definition.kind,
            definition.name,
            len(definition.allowed_tools),
        )

    @classmethod
    def get(cls, kind: str) -> AgentDefinition:
        if kind not in cls._definitions:
            raise ValueError(
                f"Agent kind '{kind}' is not registered. "
                f"Known kinds: {sorted(cls._definitions)}"
            )
        return cls._definitions[kind]

    @classmethod
    def get_or_none(cls, kind: str) -> AgentDefinition | None:
        return cls._definitions.get(kind)

    @classmethod
    def has(cls, kind: str) -> bool:
        return kind in cls._definitions

    @classmethod
    def get_all(cls) -> list[AgentDefinition]:
        return list(cls._definitions.values())

    @classmethod
    def kinds(cls) -> list[str]:
        return sorted(cls._definitions.keys())

    @classmethod
    def is_tool_authorized(cls, kind: str, tool_name: str) -> bool:
        """Enforce tool authorization boundary for a given kind."""
        defn = cls._definitions.get(kind)
        if defn is None:
            return False
        return tool_name in defn.allowed_tools

    @classmethod
    def clear(cls) -> None:
        """Test-only: reset the registry between tests."""
        cls._definitions.clear()


# ──────────────────────────────────────────────────── auto-discovery ──


def discover_agents() -> None:
    """Import every ``agents/<kind>/definition.py`` module.

    Fail-closed: if an agent definition fails to load, startup MUST fail
    rather than continuing in an incomplete state.
    """
    agents_package = "app.modules.ai.agents"
    agents_dir = Path(__file__).resolve().parent.parent / "agents"

    if not agents_dir.is_dir():
        logger.warning("agent_discovery: agents dir missing %s", agents_dir)
        return

    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        definition_file = entry / "definition.py"
        if not definition_file.exists():
            continue
        module_path = f"{agents_package}.{entry.name}.definition"
        try:
            importlib.import_module(module_path)
            logger.info("agent_discovery.loaded %s", module_path)
        except Exception as exc:
            logger.exception("agent_discovery.failed %s", module_path)
            raise RuntimeError(
                f"Fatal agent discovery error: failed to import definition '{module_path}': {exc}"
            ) from exc

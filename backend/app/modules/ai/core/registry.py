"""Extensible Multi-Agent Platform Core Registry.

This registry is the Single Source of Truth for all Agent Definitions in the
platform.  It maps an agent ``kind`` (e.g. ``customer``, ``sales_intelligence``,
``inventory``) to its definition — capabilities, default model, system prompt
template, and optional lifecycle hooks.

Architecture invariants
-----------------------
* **The core runtime MUST NOT know domain details.**  It resolves an agent's
  ``kind`` through this registry and delegates to the matching definition.
* **No hardcode for agent counts.**  Adding a new agent means registering a
  new ``AgentDefinition``; no platform-wide rewrite required.
* **AgentKind is extensible without deploys** — tenant-level definitions can
  override platform defaults (future: DB-backed dynamic registry).

Discovery
---------
On startup, ``discover_agents()`` imports every ``definition.py`` module
underneath ``app.modules.ai.agents.<kind>/`` and calls its ``register_*``
function.  A plugin can also call ``AgentRegistry.register()`` directly at
import time.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────── data models ──


class AgentCapability(BaseModel):
    """One named capability an agent advertises (e.g. ``place_order``)."""

    name: str
    description: str | None = None
    required: bool = False


class AgentDefinition(BaseModel):
    """Immutable blueprint of one agent kind.

    The runtime reads these to decide which tools to wire, which system
    prompt to inject, and which model alias to request from the gateway.
    """

    kind: str
    name: str
    description: str
    capabilities: list[AgentCapability] = Field(default_factory=list)
    system_prompt_template: str = ""
    default_model: str = "fast"
    enforce_grounding: bool = False
    # Dotted-path strings to async callables:
    #   (session, tenant_id, agent, **kw) → None
    pre_run_hook: str | None = None
    post_run_hook: str | None = None
    # Tool names this kind ALWAYS gets (the router auto-creates AgentTool rows)
    default_tools: list[str] = Field(default_factory=list)
    # Extra metadata the domain package wants to attach
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────── registry ──


class AgentRegistry:
    """Process-global, class-level registry — no singleton gymnastics."""

    _definitions: dict[str, AgentDefinition] = {}

    @classmethod
    def register(cls, definition: AgentDefinition) -> None:
        if definition.kind in cls._definitions:
            logger.warning(
                "agent_registry.overwrite kind=%s", definition.kind
            )
        cls._definitions[definition.kind] = definition
        logger.info(
            "agent_registry.registered kind=%s name=%s",
            definition.kind,
            definition.name,
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
    def has(cls, kind: str) -> bool:
        return kind in cls._definitions

    @classmethod
    def get_all(cls) -> list[AgentDefinition]:
        return list(cls._definitions.values())

    @classmethod
    def kinds(cls) -> list[str]:
        return sorted(cls._definitions.keys())

    @classmethod
    def clear(cls) -> None:
        """Test-only: reset the registry between tests."""
        cls._definitions.clear()


# ──────────────────────────────────────────────────── auto-discovery ──


def discover_agents() -> None:
    """Import every ``agents/<kind>/definition.py`` module.

    Each definition module is expected to call ``AgentRegistry.register()``
    at import time (or expose a ``register_*`` function that the import
    triggers).  Errors are logged but never fatal — a broken plugin must not
    bring down the whole platform.
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
        except Exception:
            logger.exception("agent_discovery.failed %s", module_path)

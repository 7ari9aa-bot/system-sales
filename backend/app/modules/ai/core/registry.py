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
import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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

    Per-kind extensibility hooks are declared as DOTTED-PATH STRINGS (never
    callable objects, so a definition stays serializable). The canonical
    convention is ``"package.module:attr"`` (e.g.
    ``"app.modules.ai.agents.mycustom.hooks:my_hook"``); a bare
    ``"package.module.attr"`` is also accepted. Every path is resolved and
    checked (importable, callable, async) once by ``validate_registry()`` —
    a bad path fails startup, not the first customer turn.
    """

    # Unknown fields are a typo, not a note: reject them so a future
    # declaration that the platform does not implement cannot ship inert.
    model_config = ConfigDict(extra="forbid")

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
    provisioning_policy: dict[str, Any] = Field(
        default_factory=lambda: {
            "is_canonical": False,
            "auto_provision": False,
            "singleton_per_tenant": True,
        }
    )

    # Per-kind extensibility hooks — dotted-path strings to async callables:
    #   context_builder: (session, tenant_id, agent, run_ctx) -> list[str] | None
    #       Lines appended to the run's system-owned context.
    #   pre_run_hook: (session, tenant_id, agent, run_ctx) -> dict | None
    #       The dict merges into the run context (None = no-op); an exception
    #       fails the run (contained, never crashes the worker loop).
    #   post_run_hook: (session, tenant_id, agent, run, result) -> result | str | None
    #       May replace result.content (a bare str replaces the content) or
    #       return a full AgentRunResult; None keeps the original. Hook-produced
    #       content is RE-SCREENED by the output guardrail; an exception keeps
    #       the original result.
    pre_run_hook: str | None = None
    post_run_hook: str | None = None
    context_builder: str | None = None

    # Extra metadata the domain package wants to attach
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Normalize the allowlist.

        Capabilities are DOCUMENTATION, not authorization: a capability name
        must never silently authorize a same-named global tool. Only
        ``allowed_tools`` and ``default_tools`` grant execution.
        """
        effective_allowed = set(self.allowed_tools)
        effective_allowed.update(self.default_tools)
        self.allowed_tools = sorted(effective_allowed)


# ──────────────────────────────────────────────────────── registry ──


VALID_GUARDRAIL_PROFILES = frozenset({"customer", "analytics", "internal", "default"})


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
        if definition.provisioning_policy.get("singleton_per_tenant", True) is False:
            raise ValueError(
                f"Agent kind '{definition.kind}' requests multiple instances per tenant, "
                "but the platform still enforces one agent per (tenant, kind)"
            )
        cls._definitions[definition.kind] = definition
        logger.info(
            "agent_registry.registered kind=%s name=%s tools=%d",
            definition.kind,
            definition.name,
            len(definition.allowed_tools),
        )

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls._definitions:
            discover_agents()

    @classmethod
    def get(cls, kind: str) -> AgentDefinition:
        cls._ensure_loaded()
        if kind not in cls._definitions:
            raise ValueError(
                f"Agent kind '{kind}' is not registered. Known kinds: {sorted(cls._definitions)}"
            )
        return cls._definitions[kind]

    @classmethod
    def get_or_none(cls, kind: str) -> AgentDefinition | None:
        cls._ensure_loaded()
        return cls._definitions.get(kind)

    @classmethod
    def has(cls, kind: str) -> bool:
        cls._ensure_loaded()
        return kind in cls._definitions

    @classmethod
    def get_all(cls) -> list[AgentDefinition]:
        cls._ensure_loaded()
        return list(cls._definitions.values())

    @classmethod
    def kinds(cls) -> list[str]:
        cls._ensure_loaded()
        return sorted(cls._definitions.keys())

    @classmethod
    def is_tool_authorized(cls, kind: str, tool_name: str) -> bool:
        """Enforce tool authorization boundary for a given kind."""
        cls._ensure_loaded()
        defn = cls._definitions.get(kind)
        if defn is None:
            return False
        return tool_name in defn.allowed_tools

    @classmethod
    def clear(cls) -> None:
        """Test-only: reset the registry between tests."""
        cls._definitions.clear()
        _RESOLVED_HOOKS.clear()


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


#: Resolved hook callables, keyed by (field name, dotted path). Resolution is
#: deterministic from the dotted path, so keying on the path (not definition
#: identity) avoids stale entries when a test replaces a kind's definition
#: object. Entries are written by validate_registry() at startup and by lazy
#: resolution at runtime. Plain dict — writes are GIL-atomic, matching the
#: thread-safety level of the registry itself.
_RESOLVED_HOOKS: dict[tuple[str, str], Callable[..., Any]] = {}

#: The declared extensibility-hook fields, in resolution order.
HOOK_FIELDS: tuple[str, ...] = ("context_builder", "pre_run_hook", "post_run_hook")


def _split_dotted_path(path: str) -> tuple[str, str]:
    """Split a hook dotted path into (module, attribute).

    Canonical convention is ``"package.module:attr"``; a bare
    ``"package.module.attr"`` splits on the LAST dot.
    """
    if ":" in path:
        module, _, attr = path.partition(":")
        if not module or not attr or ":" in attr:
            raise ValueError(f"malformed hook path {path!r}")
        return module, attr
    module, _, attr = path.rpartition(".")
    if not module or not attr:
        raise ValueError(f"malformed hook path {path!r}")
    return module, attr


def resolve_definition_hook(definition: AgentDefinition, field: str) -> Callable[..., Any] | None:
    """Resolve one declared hook field to its async callable (cached).

    Returns None when the field is not declared. Resolution is lazy-with-
    cache: validate_registry() warms it at startup, and the runtime calls
    this same function per run (a cache hit after validation; an identical
    validation if the registry was never validated). Any failure — bad path,
    missing attribute, not callable, not async — raises ValueError naming
    the kind and the bad path, so the caller can fail the run closed
    instead of silently skipping a declared hook.
    """
    dotted = getattr(definition, field, None)
    if not dotted:
        return None
    key = (field, dotted)
    cached = _RESOLVED_HOOKS.get(key)
    if cached is not None:
        return cached
    module_name, attr = _split_dotted_path(dotted)
    try:
        module = importlib.import_module(module_name)
        target = getattr(module, attr)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"agent kind {definition.kind!r}: {field} {dotted!r} cannot be resolved ({exc})"
        ) from exc
    if not callable(target) or not inspect.iscoroutinefunction(target):
        raise ValueError(
            f"agent kind {definition.kind!r}: {field} {dotted!r} must be an async callable"
        )
    _RESOLVED_HOOKS[key] = target
    return target


def validate_registry() -> None:
    """Fail startup when a definition references something the platform lacks.

    This is deliberately called AFTER discovery in both entry points. A typo in
    a tool name, an unknown model alias, a guardrail profile with no
    implementation, or an unresolvable extensibility hook must not become a
    silently degraded agent at runtime.
    """
    from app.modules.ai.gateway import ALIASES
    from app.modules.ai.tools import TOOLS

    errors: list[str] = []
    for definition in AgentRegistry.get_all():
        if definition.guardrail_profile not in VALID_GUARDRAIL_PROFILES:
            errors.append(
                f"{definition.kind}: unknown guardrail_profile {definition.guardrail_profile!r}"
            )
        if definition.default_model not in ALIASES:
            errors.append(
                f"{definition.kind}: default_model {definition.default_model!r} "
                "is not a gateway alias"
            )
        unknown_tools = sorted(set(definition.allowed_tools) - set(TOOLS))
        if unknown_tools:
            errors.append(f"{definition.kind}: unknown tools {unknown_tools}")
        for field in HOOK_FIELDS:
            try:
                resolve_definition_hook(definition, field)
            except ValueError as exc:
                errors.append(str(exc))
    if errors:
        raise RuntimeError("Invalid agent registry: " + "; ".join(errors))


# INVARIANT: these static imports exist ONLY for AST reachability
# (tests/test_no_dead_modules.py) — ``discover_agents()`` is the enforcement
# point, re-importing every definition package at startup and failing closed
# on errors. A failing definition import here does NOT fail registry import;
# it is logged at ERROR level and ``discover_agents()`` re-raises it (with the
# full traceback) at first use.
try:
    import app.modules.ai.agents.customer.definition  # noqa: F401
    import app.modules.ai.agents.sales_intelligence.definition  # noqa: F401
except ImportError as exc:
    logger.error(
        "registry_static_import_failed: %s — agent discovery will re-raise this error at first use",
        exc,
    )

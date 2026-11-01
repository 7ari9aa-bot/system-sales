"""Agent-layer hardening guards — DB-free so they run on every machine.

These pin the platform invariants that make a FUTURE agent safe to add:

* a global tool name is a contract — two different specs may not silently
  replace each other, while re-registering the SAME spec stays idempotent;
* canary rollout is not conversation-only — job/API agents (no conversation
  id) must still see a deterministic stable-vs-candidate decision.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel

from app.core.idempotency import should_guard
from app.modules.ai.core.registry import (
    AgentCapability,
    AgentDefinition,
    AgentRegistry,
    discover_agents,
)
from app.modules.ai.runtime import _canary_chosen
from app.modules.ai.tools import TOOLS, ToolSpec, register_tool


class _Args(BaseModel):
    value: str


async def _handler(session, tenant_id, *, value: str = "") -> dict:
    return {"value": value}


TOOL_NAME = "hardening_probe_tool"


def _spec(*, description: str = "hardening probe") -> ToolSpec:
    return ToolSpec(
        name=TOOL_NAME,
        description=description,
        args_schema=_Args,
        handler=_handler,
        tags=["hardening"],
    )


def test_duplicate_tool_registration_fails_closed() -> None:
    """A different spec under an existing name must raise, not overwrite."""
    register_tool(_spec(description="first"))
    try:
        with pytest.raises(ValueError, match="Duplicate tool registration forbidden"):
            register_tool(_spec(description="a completely different handler contract"))
        # The original spec is still the registered one.
        assert TOOLS[TOOL_NAME].description == "first"
    finally:
        TOOLS.pop(TOOL_NAME, None)


def test_registering_the_same_tool_spec_is_idempotent() -> None:
    """Import/re-import and test re-registration must not explode."""
    spec = _spec()
    register_tool(spec)
    try:
        register_tool(spec)
        assert TOOLS[TOOL_NAME] is spec
    finally:
        TOOLS.pop(TOOL_NAME, None)


def test_canary_rollout_covers_conversationless_agents() -> None:
    """No conversation id must not mean 'never canary' for API/job agents."""
    agent_id = uuid.uuid4()
    assert _canary_chosen(100, None, None, agent_id) is True
    assert _canary_chosen(0, None, None, agent_id) is False


def test_canary_rollout_splits_runs_of_an_agent_with_no_ids() -> None:
    """With neither a conversation nor an inbound id, runs bucket FRESH per
    run — seeding on the agent id put every run of that agent in one bucket,
    so its canary was all-or-nothing and §169's comparison had no split."""
    agent_id = uuid.uuid4()
    picks = {_canary_chosen(50, None, None, agent_id) for _ in range(40)}
    assert picks == {True, False}, (
        "a conversation-less agent's canary must split across runs, not pin one bucket"
    )


def test_canary_rollout_is_deterministic_for_the_same_work() -> None:
    """A retried conversation-less run carrying the same inbound event id
    must see the same version bucket."""
    agent_id = uuid.uuid4()
    first = _canary_chosen(37, None, "inbound-event-1", agent_id)
    second = _canary_chosen(37, None, "inbound-event-1", agent_id)
    assert first is second


def test_every_registered_definition_tool_exists() -> None:
    """A typo in a definition must fail startup, not become a silent agent."""
    discover_agents()
    for definition in AgentRegistry.get_all():
        missing = set(definition.allowed_tools) - set(TOOLS)
        assert not missing, f"{definition.kind} references unknown tools: {sorted(missing)}"


def test_capabilities_do_not_authorize_tools() -> None:
    """Capabilities document behavior; only the allowlist grants execution."""
    definition = AgentDefinition(
        kind="capability_probe",
        name="Capability probe",
        description="probe",
        capabilities=[AgentCapability(name="si_get_metric")],
        allowed_tools=[],
    )
    assert "si_get_metric" not in definition.allowed_tools


def test_unimplemented_extension_fields_are_unknown_fields() -> None:
    """The three hooks (pre_run_hook / post_run_hook / context_builder) are now
    IMPLEMENTED dotted-path extensions; the never-built reserved fields
    (output_policy / configuration_schema / lifecycle) were removed, so
    declaring one is a pydantic unknown-field error, not an inert switch."""
    from pydantic import ValidationError

    for field in ("output_policy", "configuration_schema", "lifecycle"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            AgentDefinition(
                kind="reserved_probe",
                name="Reserved probe",
                description="probe",
                **{field: {}},
            )
    # The implemented hooks are legal construction-time: only RESOLUTION
    # (validate_registry / resolve_definition_hook) judges the path.
    definition = AgentDefinition(
        kind="reserved_probe",
        name="Reserved probe",
        description="probe",
        context_builder="app.some.builder",
    )
    assert definition.context_builder == "app.some.builder"
    assert definition.pre_run_hook is None
    assert definition.post_run_hook is None


def test_non_singleton_kind_is_refused() -> None:
    definition = AgentDefinition(
        kind="multi_instance_probe",
        name="Multi-instance probe",
        description="probe",
        provisioning_policy={"singleton_per_tenant": False},
    )
    with pytest.raises(ValueError, match="multiple instances per tenant"):
        AgentRegistry.register(definition)


def test_ai_analysis_paths_are_idempotent() -> None:
    assert should_guard("POST", "/api/v1/ai/sales/analyses") is True
    assert should_guard("POST", "/api/v1/ai/sales/deep-analyses") is True

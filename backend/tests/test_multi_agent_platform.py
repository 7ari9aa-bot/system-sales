"""Tests for Extensible Multi-Agent Platform Core.

Validates:
- Single Source of Truth: AgentRegistry registration, query, and tool authorization.
- Fail-Closed: Duplicate registration raises ValueError.
- Security Boundary: AgentRunner._load_agent_tools discards unauthorized tools.
- Contract Invariant: AgentUpdateRequest schema does not allow mutating kind.
- Canonical Provisioning: Idempotent provisioning and tool syncing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.ai.core.registry import (
    AgentCapability,
    AgentDefinition,
    AgentRegistry,
    discover_agents,
)
from app.modules.ai.models import AgentTool
from app.modules.ai.runtime import AgentRunner
from app.modules.ai.schemas import AgentUpdateRequest


def test_registry_registration_and_queries() -> None:
    """Test registry basic operations and tool authorization."""
    # Ensure customer & sales_intelligence are discoverable
    discover_agents()
    assert AgentRegistry.has("customer")
    assert AgentRegistry.has("sales_intelligence")

    cust_defn = AgentRegistry.get("customer")
    assert cust_defn.kind == "customer"
    assert "search_products" in cust_defn.allowed_tools
    assert "create_order" in cust_defn.allowed_tools
    assert cust_defn.guardrail_profile == "customer"

    # Authorization enforcement checks
    assert AgentRegistry.is_tool_authorized("customer", "search_products") is True
    assert AgentRegistry.is_tool_authorized("customer", "create_order") is True
    # Customer agent must NEVER be authorized for sales intelligence tools
    assert AgentRegistry.is_tool_authorized("customer", "si_analyze_drivers") is False
    assert AgentRegistry.is_tool_authorized("customer", "unknown_tool_xyz") is False

    # Sales Intelligence authorization checks
    assert AgentRegistry.get("sales_intelligence") is not None
    assert AgentRegistry.is_tool_authorized("sales_intelligence", "si_analyze_drivers") is True
    assert AgentRegistry.is_tool_authorized("sales_intelligence", "create_order") is False


def test_registry_fail_closed_duplicate_rejection() -> None:
    """Registry must raise ValueError if duplicate kind is registered without allow_override."""
    test_defn = AgentDefinition(
        kind="test_duplicate_kind",
        name="Duplicate Kind",
        description="Test agent",
        allowed_tools=["test_tool"],
    )
    AgentRegistry.register(test_defn)

    # Re-registering the same kind MUST fail-closed
    with pytest.raises(ValueError, match="Duplicate registration forbidden"):
        AgentRegistry.register(test_defn)

    # But allow_override=True succeeds (useful for testing/hot-reload)
    AgentRegistry.register(test_defn, allow_override=True)


def test_registry_unknown_kind() -> None:
    """Unknown kind must raise ValueError on get(), False on is_tool_authorized."""
    with pytest.raises(ValueError, match="is not registered"):
        AgentRegistry.get("non_existent_kind_999")

    assert AgentRegistry.get_or_none("non_existent_kind_999") is None
    assert AgentRegistry.is_tool_authorized("non_existent_kind_999", "any_tool") is False


def test_agent_update_request_kind_immutable() -> None:
    """AgentUpdateRequest must NOT allow mutating kind."""
    fields = AgentUpdateRequest.model_fields
    assert "kind" not in fields, "kind must be immutable in AgentUpdateRequest"
    assert "name" in fields
    assert "model" in fields
    assert "system_prompt" in fields
    assert "is_active" in fields


@pytest.mark.asyncio
async def test_runtime_tool_isolation_enforcement() -> None:
    """Runtime._load_agent_tools must discard tools unauthorized for agent.kind."""
    discover_agents()
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    # Suppose DB contains 3 tools linked to a customer agent:
    # 2 legitimate customer tools + 1 injected SI tool
    legit_tool1 = AgentTool(
        tenant_id=tenant_id, agent_id=agent_id, name="search_products", is_active=True
    )
    legit_tool2 = AgentTool(
        tenant_id=tenant_id, agent_id=agent_id, name="create_order", is_active=True
    )
    injected_tool = AgentTool(
        tenant_id=tenant_id, agent_id=agent_id, name="si_analyze_drivers", is_active=True
    )

    mock_session = AsyncMock()
    mock_execute_result = MagicMock()
    mock_execute_result.scalars.return_value.all.return_value = [
        legit_tool1,
        legit_tool2,
        injected_tool,
    ]
    mock_session.execute.return_value = mock_execute_result

    # When loading tools with agent_kind="customer"
    loaded = await AgentRunner._load_agent_tools(
        mock_session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_kind="customer",
    )

    loaded_names = [t.name for t in loaded]
    # Authorized tools must remain
    assert "search_products" in loaded_names
    assert "create_order" in loaded_names
    # Injected / unauthorized tool MUST be stripped by the enforcement boundary
    assert "si_analyze_drivers" not in loaded_names
    assert len(loaded) == 2


@pytest.mark.asyncio
async def test_agent_3_extensibility_e2e_lifecycle() -> None:
    """True Platform Acceptance Test:
    1. Register custom Agent #3 (inventory_ops) with unique capabilities & tool.
    2. Verify registry discovers and exposes the definition.
    3. Verify tool authorization boundary rejects cross-domain tool requests.
    4. Verify runtime tool loader only retains tools authorized for this kind.
    5. Execute authorized tool through runtime -> status=ok, facts captured.
    6. Execute unauthorized cross-agent tool through runtime -> status=denied.
    """
    from pydantic import BaseModel

    from app.modules.ai.models import Agent, AgentRun
    from app.modules.ai.providers import ToolCallRequest
    from app.modules.ai.tools import ToolSpec, register_tool

    # Step 1: Register custom Agent #3
    agent3_defn = AgentDefinition(
        kind="inventory_ops",
        name="Inventory Operations Agent",
        description="Monitors stock levels, reconciles warehouses, and triggers supplier POs.",
        definition_version=1,
        capabilities=[
            AgentCapability(
                name="inv_check_reorder_level",
                description="Check reorder thresholds",
                required=True,
            ),
        ],
        system_prompt_template="You are the inventory operations assistant.",
        default_model="fast",
        default_tools=["inv_check_reorder_level"],
        allowed_tools=["inv_check_reorder_level"],
        task_types=["stock_reorder", "inventory_audit"],
        guardrail_profile="internal",
        provisioning_policy={
            "is_canonical": True,
            "auto_provision": True,
            "singleton_per_tenant": True,
        },
    )
    AgentRegistry.register(agent3_defn, allow_override=True)

    # Step 2: Verify registry discovery
    assert AgentRegistry.has("inventory_ops")
    fetched = AgentRegistry.get("inventory_ops")
    assert fetched.name == "Inventory Operations Agent"
    assert fetched.definition_version == 1

    # Step 3: Register custom tool in platform tools registry
    class DummyReorderArgs(BaseModel):
        sku: str

    async def dummy_reorder_handler(session, tenant_id, **kw):
        return {"sku": kw.get("sku"), "reorder_needed": True, "suggested_qty": 50}

    register_tool(
        ToolSpec(
            name="inv_check_reorder_level",
            description="Checks SKU reorder level",
            args_schema=DummyReorderArgs,
            handler=dummy_reorder_handler,
            tags=["inventory"],
        )
    )

    # Step 4: Verify tool authorization boundary
    assert AgentRegistry.is_tool_authorized("inventory_ops", "inv_check_reorder_level") is True
    assert AgentRegistry.is_tool_authorized("inventory_ops", "create_order") is False
    assert AgentRegistry.is_tool_authorized("inventory_ops", "si_analyze_drivers") is False

    # Step 5: Test runtime loading with isolation
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    tool_authorized = AgentTool(
        tenant_id=tenant_id, agent_id=agent_id, name="inv_check_reorder_level", is_active=True
    )
    tool_unauthorized = AgentTool(
        tenant_id=tenant_id, agent_id=agent_id, name="create_order", is_active=True
    )

    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = [tool_authorized, tool_unauthorized]
    mock_session.execute.return_value = mock_res

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_nested():
        yield

    mock_session.begin_nested = MagicMock(side_effect=_mock_nested)

    loaded_tools = await AgentRunner._load_agent_tools(
        mock_session, tenant_id=tenant_id, agent_id=agent_id, agent_kind="inventory_ops"
    )
    assert len(loaded_tools) == 1
    assert loaded_tools[0].name == "inv_check_reorder_level"

    # Step 6: Test authorized tool execution
    runner = AgentRunner()
    agent_instance = Agent(
        id=agent_id,
        tenant_id=tenant_id,
        kind="inventory_ops",
        name="Inventory Operations Agent",
        is_active=True,
    )
    run_instance = AgentRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        status="running",
    )

    # 6a. Execute authorized tool
    valid_request = ToolCallRequest(
        id="call_1",
        name="inv_check_reorder_level",
        arguments={"sku": "SKU-TEST-99"},
    )
    outcome_ok = await runner._execute_tool(
        mock_session,
        tenant_id,
        run=run_instance,
        agent=agent_instance,
        agent_tools=loaded_tools,
        request=valid_request,
    )
    assert outcome_ok["status"] == "ok"
    assert outcome_ok["result"]["reorder_needed"] is True
    assert outcome_ok["result"]["suggested_qty"] == 50

    # 6b. Attempt to execute unauthorized tool (even if requested by model)
    forbidden_request = ToolCallRequest(
        id="call_2",
        name="create_order",
        arguments={"items": []},
    )
    outcome_denied = await runner._execute_tool(
        mock_session,
        tenant_id,
        run=run_instance,
        agent=agent_instance,
        agent_tools=loaded_tools,
        request=forbidden_request,
    )
    assert outcome_denied["status"] == "denied"
    assert "not authorized for agent kind 'inventory_ops'" in outcome_denied["error"]

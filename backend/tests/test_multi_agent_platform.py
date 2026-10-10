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


@pytest.mark.asyncio
async def test_two_way_tool_reconciliation_quarantines_unauthorized_tools() -> None:
    """§5 Tool Reconciliation: missing tools are created, unauthorized tools in DB are disabled."""
    from app.modules.ai.core.provisioning import _sync_agent_tools

    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    # Pre-existing tools: one authorized and one unauthorized
    authorized_tool = AgentTool(
        tenant_id=tenant_id, agent_id=agent_id, name="search_products", is_active=True
    )
    unauthorized_tool = AgentTool(
        tenant_id=tenant_id, agent_id=agent_id, name="si_analyze_drivers", is_active=True
    )

    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = [authorized_tool, unauthorized_tool]
    mock_session.execute.return_value = mock_res

    added = await _sync_agent_tools(mock_session, tenant_id, agent_id, kind="customer")

    # Unauthorized tool must be quarantined (is_active=False)
    assert unauthorized_tool.is_active is False
    # Missing required default tools must have been added
    assert added > 0
    assert mock_session.add.called


@pytest.mark.asyncio
async def test_handover_atomic_claim_and_resolve_lifecycle() -> None:
    """§29-30 Handover claim atomicity and resolve conversation status sync."""
    from app.core.errors import ConflictError
    from app.modules.ai.models import AIHandover
    from app.modules.ai.router import claim_handover, resolve_handover

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    handover_id = uuid.uuid4()

    # Test 1: Conflict when claiming an already claimed handover
    claimed_handover = AIHandover(
        id=handover_id,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        reason="customer_request",
        status="claimed",
        claimed_by_user_id=uuid.uuid4(),
    )
    mock_ctx = MagicMock()
    mock_ctx.tenant_id = tenant_id
    mock_ctx.user_id = user_id
    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = claimed_handover
    mock_session.execute.return_value = mock_res
    mock_ctx.session = mock_session

    with pytest.raises(ConflictError) as exc_info:
        await claim_handover(handover_id, mock_ctx)
    assert "already claimed" in str(exc_info.value)

    # Test 2: Resolve handover synchronizes conversation out of waiting_human
    pending_handover = AIHandover(
        id=handover_id,
        tenant_id=tenant_id,
        conversation_id=conv_id,
        reason="customer_request",
        status="claimed",
    )
    mock_res.scalar_one_or_none.return_value = pending_handover
    out = await resolve_handover(handover_id, mock_ctx)
    assert out.status == "resolved"
    # Ensure SQL update was executed on conversations
    assert mock_session.execute.called


@pytest.mark.asyncio
async def test_ai_approval_rbac_gate() -> None:
    """§33 Approval RBAC: require_ai_approve gates decision endpoint."""
    from app.core.errors import PermissionDeniedError
    from app.modules.ai.router import require_ai_approve

    gate = require_ai_approve()

    # Case 1: user with no permissions and non-owner role -> PermissionDeniedError
    ctx_denied = MagicMock()
    ctx_denied.permission_codes = {"some:other"}
    ctx_denied.role_code = "staff"
    with pytest.raises(PermissionDeniedError):
        await gate(ctx_denied)

    # Case 2: user with explicit ai:approve -> passes
    ctx_explicit = MagicMock()
    ctx_explicit.permission_codes = {"ai:approve"}
    ctx_explicit.role_code = "staff"
    assert await gate(ctx_explicit) is ctx_explicit

    # Case 3: user with owner role -> passes
    ctx_owner = MagicMock()
    ctx_owner.permission_codes = set()
    ctx_owner.role_code = "owner"
    assert await gate(ctx_owner) is ctx_owner

    # Case 4: user with settings:write alone without ai:approve -> rejected (tightened gate)
    ctx_settings = MagicMock()
    ctx_settings.permission_codes = {"settings:write"}
    ctx_settings.role_code = "admin"
    with pytest.raises(PermissionDeniedError):
        await gate(ctx_settings)


@pytest.mark.asyncio
async def test_canary_rollout_updates_the_real_deployment_state(db, tenant_ctx) -> None:
    """A canary must move the deployment row, not just a status string."""
    from sqlalchemy import select

    from app.modules.ai.evaluation import AIEvaluationService
    from app.modules.ai.models import Agent, AgentVersion, AIEvaluation, Deployment

    tenant_id = tenant_ctx.tenant_id
    agent = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Canary Agent",
        model="fast",
        system_prompt="stable",
    )
    stable_version = AgentVersion(
        tenant_id=tenant_id,
        agent_id=agent.id,
        version=1,
        status="published",
        system_prompt="stable",
        model="fast",
    )
    candidate_version = AgentVersion(
        tenant_id=tenant_id,
        agent_id=agent.id,
        version=2,
        status="published",
        system_prompt="candidate",
        model="fast",
    )
    db.add_all([agent, stable_version, candidate_version])
    await db.flush()

    evaluation = AIEvaluation(
        tenant_id=tenant_id,
        agent_id=agent.id,
        agent_version_id=candidate_version.id,
        status="passed",
        rollout_status="none",
        quality_metrics={"canary_success_rate": 1.0},
    )
    db.add(evaluation)
    await db.flush()

    await AIEvaluationService.approve_rollout(db, tenant_id, candidate_version.id)
    deployment = (
        await db.execute(
            select(Deployment).where(
                Deployment.tenant_id == tenant_id,
                Deployment.agent_id == agent.id,
            )
        )
    ).scalar_one()
    assert deployment.stable_version_id == stable_version.id
    assert deployment.candidate_version_id == candidate_version.id
    assert deployment.canary_percent == 5
    assert await AIEvaluationService.get_canary_traffic_percent(db, tenant_id, agent.id) == 5

    evaluation.rollout_status = "canary_100"
    evaluation.quality_metrics = {"canary_success_rate": 1.0}
    await db.flush()

    await AIEvaluationService.ramp_canary(db, tenant_id, evaluation.id)
    deployment = (
        await db.execute(
            select(Deployment).where(
                Deployment.tenant_id == tenant_id,
                Deployment.agent_id == agent.id,
            )
        )
    ).scalar_one()
    assert evaluation.rollout_status == "rolled_out"
    assert deployment.stable_version_id == candidate_version.id
    assert deployment.candidate_version_id is None
    assert deployment.canary_percent == 0
    assert deployment.status == "fully_rollout"

    evaluation.rollout_status = "canary_5"
    evaluation.quality_metrics = {"canary_success_rate": 0.5}
    await db.flush()

    await AIEvaluationService.rollback_canary(
        db, tenant_id, evaluation.id, reason="metric_degradation"
    )
    deployment = (
        await db.execute(
            select(Deployment).where(
                Deployment.tenant_id == tenant_id,
                Deployment.agent_id == agent.id,
            )
        )
    ).scalar_one()
    assert evaluation.rollout_status == "rolled_back"
    assert deployment.candidate_version_id is None
    assert deployment.canary_percent == 0
    assert deployment.status == "rolled_back"


@pytest.mark.asyncio
async def test_customer_tools_enforce_canonical_sellability() -> None:
    """§22 Customer Product Sellability: draft products rejected across all customer tools."""
    from app.core.errors import NotFoundError
    from app.modules.ai.tools import _check_stock, _get_variant_price, _resolve_product_media

    tenant_id = uuid.uuid4()
    variant_id = uuid.uuid4()
    product_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_res = MagicMock()
    # Mocking empty return for non-sellable product
    mock_res.first.return_value = None
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res

    # 1. get_variant_price fails closed when not sellable
    with pytest.raises(NotFoundError):
        await _get_variant_price(mock_session, tenant_id, variant_id=variant_id)

    # 2. check_stock fails closed when not sellable
    with pytest.raises(NotFoundError):
        await _check_stock(mock_session, tenant_id, variant_id=variant_id)

    # 3. resolve_product_media fails closed when parent product is not sellable
    with pytest.raises(NotFoundError):
        await _resolve_product_media(mock_session, tenant_id, product_id=product_id)


def test_worker_process_discovers_registry() -> None:
    """P0-3 Worker Registry Discovery: worker entrypoint must have registered canonical kinds."""
    import subprocess
    import sys

    cmd = [
        sys.executable,
        "-c",
        (
            "import app.workers.run\n"
            "from app.modules.ai.core.registry import AgentRegistry\n"
            "assert 'customer' in AgentRegistry.kinds(), 'customer missing in worker'\n"
            "assert 'sales_intelligence' in AgentRegistry.kinds(), 'sales_intelligence missing'\n"
            "assert AgentRegistry.is_tool_authorized('customer', 'create_order')\n"
            "assert AgentRegistry.is_tool_authorized('sales_intelligence', 'si_get_metric')\n"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Worker process failed registry check: {res.stderr}"


@pytest.mark.asyncio
async def test_semantic_idempotency_message_discriminator() -> None:
    """P0-6 Semantic Idempotency: same message dedupes, distinct inbound messages execute."""
    runner = AgentRunner()
    mock_session = AsyncMock()
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    mock_session.begin_nested = MagicMock(return_value=nested_cm)

    # ToolCall mock
    tenant_id = uuid.uuid4()
    convo_id = uuid.uuid4()
    msg_1 = uuid.uuid4()
    msg_2 = uuid.uuid4()

    run = MagicMock()
    run.id = uuid.uuid4()
    run.status = "running"

    agent_tool = MagicMock()
    agent_tool.name = "add_task"
    agent_tool.is_active = True

    tc_req = MagicMock()
    tc_req.id = "tc_1"
    tc_req.name = "add_task"
    tc_req.arguments = {"title": "Follow up"}

    # First run for msg_1: prior is None (not executed yet)
    mock_res_empty = MagicMock()
    mock_res_empty.scalar_one_or_none.return_value = None

    # Prior completed ToolCall for msg_1
    prior_tc = MagicMock()
    prior_tc.name = "add_task"
    prior_tc.status = "ok"
    prior_tc.error = None
    prior_tc.result = {"task_id": "tsk_123"}
    mock_res_found = MagicMock()
    mock_res_found.scalar_one_or_none.return_value = prior_tc

    # Sequence: first check for msg_1 -> None (executes)
    # retry check for msg_1 -> found (skips)
    # new message msg_2 -> None (executes)
    mock_session.execute.side_effect = [
        mock_res_empty,  # msg_1 first call: no prior
        mock_res_found,  # msg_1 retry: found prior -> skip
        mock_res_empty,  # msg_2 call: no prior -> execute
    ]

    from unittest.mock import patch

    from app.modules.ai.tools import get_tool

    spec = get_tool("add_task")
    assert spec is not None

    with patch.object(spec, "handler", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = {"task_id": "tsk_123"}

        # 1. First execution for msg_1
        res1 = await runner._execute_tool(
            mock_session,
            tenant_id,
            run=run,
            agent=None,
            agent_tools=[agent_tool],
            request=tc_req,
            conversation_id=convo_id,
            inbound_message_id=msg_1,
        )
        assert res1["status"] == "ok"
        assert mock_handler.call_count == 1

        # 2. Retry of same msg_1 -> skipped via idempotency key
        res2 = await runner._execute_tool(
            mock_session,
            tenant_id,
            run=run,
            agent=None,
            agent_tools=[agent_tool],
            request=tc_req,
            conversation_id=convo_id,
            inbound_message_id=msg_1,
        )
        assert res2["status"] == "ok"
        assert res2["result"] == {"task_id": "tsk_123"}
        assert mock_handler.call_count == 1  # not incremented

        # 3. New message msg_2 with same args -> executes anew (NOT swallowed)
        res3 = await runner._execute_tool(
            mock_session,
            tenant_id,
            run=run,
            agent=None,
            agent_tools=[agent_tool],
            request=tc_req,
            conversation_id=convo_id,
            inbound_message_id=msg_2,
        )
        assert res3["status"] == "ok"
        assert mock_handler.call_count == 2  # incremented!


@pytest.mark.asyncio
async def test_tenant_creation_lifecycle_hook_dispatches() -> None:
    """P0-5 Provisioning Hook: tenant creation dispatches canonical agent provisioning."""
    from app.core.tenancy import dispatch_tenant_created_hooks, register_tenant_created_hook

    hook_called = False
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = []
    mock_res.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_res
    tenant_id = uuid.uuid4()

    async def dummy_hook(session, tid):
        nonlocal hook_called
        if tid == tenant_id:
            hook_called = True

    register_tenant_created_hook(dummy_hook)
    await dispatch_tenant_created_hooks(mock_session, tenant_id)
    assert hook_called is True


def test_allowed_numbers_and_full_evidence_validation() -> None:
    """SI Answer Validation: Recursively extracts allowed numbers from facts, comparisons,
    dimensions, drivers, and findings, rejecting hallucinated numbers."""
    from app.modules.ai.agents.sales_intelligence.response import (
        allowed_numbers_from_facts,
        validate_answer,
    )
    from app.modules.analytics.contracts import Finding, Relationship

    evidence = {
        "facts": [
            {"id": "F1", "metric": "revenue", "value": 12500.50},
            {"id": "F2", "metric": "orders", "value": 150},
        ],
        "comparisons": [
            {
                "left_fact_id": "F1",
                "right_fact_id": "F2",
                "delta": 2500,
                "delta_pct": 25.0,
            }
        ],
        "dimensions": [{"dimension": "channel", "value": "web", "metric_value": 7500}],
        "drivers": [
            {
                "kind": "orders_vs_aov",
                "orders_contribution": 1000,
                "aov_contribution": 1500,
                "total_delta": 2500,
            }
        ],
    }
    findings = [
        Finding(
            type="DERIVED",
            relationship=Relationship.CORRELATION,
            confidence="MEDIUM",
            confidence_reasons=["tested"],
            materiality=0.85,
            statement="النمو كان 25% مع مساهمة الويب بـ 7500",
            evidence_refs=["F1", "C1"],
        )
    ]

    allowed = allowed_numbers_from_facts(evidence, findings)
    assert "12500.50" in allowed or "12500.5" in allowed
    assert "150" in allowed
    assert "25" in allowed
    assert "7500" in allowed
    assert "1000" in allowed
    assert "1500" in allowed
    assert "2500" in allowed

    # Valid answer referencing only allowed numbers
    valid_answer = "المبيعات 12500.50 والطلبات 150 بنمو 25% ومساهمة 1000 من الطلبات"
    problems = validate_answer(valid_answer, allowed, findings)
    assert problems == []

    # Hallucinated number 99999
    invalid_answer = "المبيعات 12500.50 والهدف كان 99999"
    problems_invalid = validate_answer(invalid_answer, allowed, findings)
    assert any("free number in answer: 99999" in p for p in problems_invalid)


def test_evidence_reconstruction_and_store_from() -> None:
    """SI Evidence Rebuild: _rebuild_evidence captures all 4 dimensions, and
    _store_from enforces referential integrity for comparisons and driver deltas."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.modules.ai.agents.sales_intelligence.agent import (
        _rebuild_evidence,
        _store_from,
    )
    from app.modules.analytics.contracts import (
        AnalysisPeriod,
        MaturityPolicy,
        MaturityStatus,
        MetricFact,
    )

    tool_calls = [
        {
            "name": "si_get_metric",
            "status": "ok",
            "result": {
                "facts": [
                    {
                        "id": "F1",
                        "metric": "orders_placed",
                        "value": 100,
                        "unit": "orders",
                        "period_start": "2026-09-01T00:00:00+00:00",
                        "period_end": "2026-09-30T00:00:00+00:00",
                        "maturity": "final",
                    },
                    {
                        "id": "F2",
                        "metric": "orders_placed",
                        "value": 150,
                        "unit": "orders",
                        "period_start": "2026-10-01T00:00:00+00:00",
                        "period_end": "2026-10-31T00:00:00+00:00",
                        "maturity": "final",
                    },
                ]
            },
        },
        {
            "name": "si_compare_periods",
            "status": "ok",
            "result": {
                "comparisons": [
                    {
                        "label": "MoM",
                        "left_fact_id": "F1",
                        "right_fact_id": "F2",
                        "delta": 50,
                        "delta_pct": 50.0,
                    },
                    {
                        "label": "InvalidOrphan",
                        "left_fact_id": "F1",
                        "right_fact_id": "NON_EXISTENT",
                        "delta": 10,
                    },
                ]
            },
        },
        {
            "name": "si_analyze_drivers",
            "status": "ok",
            "result": {
                "drivers": [
                    {
                        "kind": "orders_vs_aov",
                        "orders_contribution": 30,
                        "aov_contribution": 20,
                        "total_delta": 50,
                    },
                    {
                        "kind": "orders_vs_aov",
                        "orders_contribution": 10,
                        "aov_contribution": 10,
                        "total_delta": 999,  # Mismatch: 10 + 10 != 999
                    },
                ]
            },
        },
    ]

    evidence = _rebuild_evidence(tool_calls)
    assert len(evidence["facts"]) == 2
    assert len(evidence["comparisons"]) == 2
    assert len(evidence["drivers"]) == 2

    # Create MetricFact dict
    period = AnalysisPeriod(
        start=datetime.now(UTC),
        end=datetime.now(UTC),
        timezone="Africa/Cairo",
        attribution_basis="placed_at",
        maturity_policy=MaturityPolicy(kind="immediate"),
        maturity_status=MaturityStatus.MATURE,
        data_as_of=datetime.now(UTC),
    )
    facts_dict = {
        "F1": MetricFact(
            id="F1",
            metric="orders_placed",
            value=Decimal("100"),
            unit="count",
            period=period,
            source="orders",
            computed_at=datetime.now(UTC),
            data_as_of=datetime.now(UTC),
            maturity_status=MaturityStatus.MATURE,
        ),
        "F2": MetricFact(
            id="F2",
            metric="orders_placed",
            value=Decimal("150"),
            unit="count",
            period=period,
            source="orders",
            computed_at=datetime.now(UTC),
            data_as_of=datetime.now(UTC),
            maturity_status=MaturityStatus.MATURE,
        ),
    }

    store = _store_from(
        facts_dict,
        comparisons=evidence["comparisons"],
        drivers=evidence["drivers"],
    )

    # Valid comparison C1 included, orphan discarded
    assert "C1" in store.comparisons
    assert store.comparisons["C1"].delta == Decimal("50")
    assert len(store.comparisons) == 1

    # Valid driver D1 included, mismatched delta discarded
    assert "D1" in store.drivers
    assert store.drivers["D1"].total_delta == Decimal("50")
    assert len(store.drivers) == 1


def test_agent_version_and_model_pinning_contracts() -> None:
    """Agent version and model pinning across AgentRunResult and trace._run_summary."""
    from app.modules.ai.models import AgentRun
    from app.modules.ai.runtime import AgentRunResult
    from app.modules.ai.trace import _run_summary

    # Check AgentRunResult carries pinned metadata
    result = AgentRunResult(
        content="test content",
        run_id=uuid.uuid4(),
        agent_version=3,
        model="gemini-2.5-pro",
        provider="google",
    )
    assert result.agent_version == 3
    assert result.model == "gemini-2.5-pro"
    assert result.provider == "google"

    # Check _run_summary extracts version from AgentRun input/output JSONB
    run = AgentRun(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        status="completed",
        input={"agent_version": 3, "model": "gemini-2.5-pro"},
        output={"model": "gemini-2.5-pro", "provider": "google"},
    )
    summary = _run_summary(run)
    assert summary["agent_version"] == 3
    assert summary["model"] == "gemini-2.5-pro"


@pytest.mark.asyncio
async def test_ai_evaluation_service_unified_lifecycle() -> None:
    """AIEvaluationService: End-to-end submit, list, and update_status lifecycle."""
    from app.modules.ai.evaluation import AIEvaluationService

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    # 1. submit_evaluation
    eval_item = await AIEvaluationService.submit_evaluation(
        mock_session,
        tenant_id,
        agent_id=agent_id,
        prompt_version=2,
        dataset_id="ds_123",
        results={"passed": True, "score": 0.95},
    )
    assert eval_item.tenant_id == tenant_id
    assert eval_item.agent_id == agent_id
    assert eval_item.prompt_version == 2
    assert eval_item.status == "passed"
    mock_session.add.assert_called_once_with(eval_item)

    # 2. list_evaluations
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = [eval_item]
    mock_session.execute.return_value = mock_res

    evals = await AIEvaluationService.list_evaluations(mock_session, tenant_id, agent_id=agent_id)
    assert len(evals) == 1
    assert evals[0].id == eval_item.id

    # 3. update_evaluation_status
    mock_res_single = MagicMock()
    mock_res_single.scalar_one_or_none.return_value = eval_item
    mock_session.execute.return_value = mock_res_single

    updated = await AIEvaluationService.update_evaluation_status(
        mock_session,
        tenant_id,
        eval_item.id,
        status="passed",
        quality_metrics={"score": 0.98},
        rollout_status="approved",
    )
    assert updated.rollout_status == "approved"
    assert updated.quality_metrics["score"] == 0.98

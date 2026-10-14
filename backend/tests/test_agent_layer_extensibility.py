"""The agent LAYER's extensibility contract — a third agent is ONE file.

The layer ships two canonical agents with completely different mandates (a
customer-facing service agent and an owner-facing analyst) and more are coming.
This file proves the promise ``app/modules/ai/agents/__init__.py`` makes: adding
a kind needs a new ``definition.py`` and NOTHING else — registration, discovery,
provisioning, tool authorization and the guardrail routing all pick it up
without a single edit to shared code, and the two existing agents cannot reach
each other's tools.
"""

from __future__ import annotations

import inspect

import pytest

from app.modules.ai.core.registry import AgentCapability, AgentDefinition, AgentRegistry

THIRD_KIND = "inventory_ops"
# A tool the CUSTOMER agent owns — the third kind must NOT be able to use it.
CUSTOMER_TOOL = "search_products"
# A tool the SALES-INTELLIGENCE agent owns.
SI_TOOL = "si_get_metric"


def _third_definition() -> AgentDefinition:
    """A plausible FUTURE agent: internal operations, its own tool, no sales."""
    return AgentDefinition(
        kind=THIRD_KIND,
        name="Inventory Ops Agent",
        description="Internal stock and operations assistant (a future agent).",
        capabilities=[
            AgentCapability(name="ops_recount_stock", description="Check stock", required=False)
        ],
        # Both lists, exactly like the shipped definitions do: provisioning
        # seeds DEFAULT tools, the runtime authorizes via ALLOWED tools.
        default_tools=["ops_recount_stock"],
        allowed_tools=["ops_recount_stock"],
        task_types=["ops_task"],
        guardrail_profile="default",
        provisioning_policy={"is_canonical": True, "auto_provision": True},
    )


@pytest.fixture
def third_kind():
    """Register a throwaway kind and restore the registry afterwards."""
    definition = _third_definition()
    AgentRegistry.register(definition)
    try:
        yield definition
    finally:
        # The registry is process-global and fail-closed on duplicates, so a
        # test MUST remove what it added or the next run in the same process
        # fails on re-registration.
        AgentRegistry._definitions.pop(THIRD_KIND, None)


# --------------------------------------- 1. registration is the whole story ---


def test_a_third_kind_needs_only_its_definition(third_kind) -> None:
    assert AgentRegistry.has(THIRD_KIND)
    assert AgentRegistry.get(THIRD_KIND) is third_kind
    # And the two shipped kinds are untouched by the newcomer.
    assert AgentRegistry.has("customer")
    assert AgentRegistry.has("sales_intelligence")


def test_discovery_is_idempotent_and_keeps_the_third_kind(third_kind) -> None:
    """`discover_agents` re-imports CACHED definition modules, so a second call
    neither re-registers the shipped kinds nor drops the newcomer."""
    from app.modules.ai.core.registry import discover_agents

    discover_agents()
    assert AgentRegistry.has(THIRD_KIND)
    assert AgentRegistry.has("customer")
    assert AgentRegistry.has("sales_intelligence")


def test_tool_authorization_is_default_deny_per_kind(third_kind) -> None:
    """A new kind can use ONLY what it lists — not the customer's tools, and the
    two shipped agents cannot reach each other's tools either."""
    assert AgentRegistry.is_tool_authorized(THIRD_KIND, "ops_recount_stock") is True
    assert AgentRegistry.is_tool_authorized(THIRD_KIND, CUSTOMER_TOOL) is False
    assert AgentRegistry.is_tool_authorized(THIRD_KIND, SI_TOOL) is False

    assert AgentRegistry.is_tool_authorized("customer", CUSTOMER_TOOL) is True
    assert AgentRegistry.is_tool_authorized("customer", SI_TOOL) is False

    assert AgentRegistry.is_tool_authorized("sales_intelligence", SI_TOOL) is True
    assert AgentRegistry.is_tool_authorized("sales_intelligence", CUSTOMER_TOOL) is False


def test_an_unknown_kind_authorizes_nothing_and_is_not_served() -> None:
    """A kind that was never defined authorizes nothing at all."""
    assert AgentRegistry.is_tool_authorized("brand_new_kind", "ops_recount_stock") is False


# --------------------------------- 2. the shared layer has no kind if-statements


def test_provisioning_is_kind_agnostic() -> None:
    """Provisioning iterates the registry and filters on the POLICY flags —
    never on a hard-coded kind name."""
    from app.modules.ai.core import provisioning

    source = inspect.getsource(provisioning.provision_canonical_agents)
    assert "AgentRegistry.get_all()" in source
    assert '"customer"' not in source
    assert '"sales_intelligence"' not in source


def test_the_reconcile_tooling_is_kind_agnostic() -> None:
    """A prompt fix on a FUTURE kind must be reconcilable without editing the tool."""
    import pathlib

    script = (
        pathlib.Path(__file__).resolve().parent.parent
        / "scripts"
        / "sync_canonical_agent_prompts.py"
    )
    source = script.read_text(encoding="utf-8")
    assert "canonical_definitions()" in source
    assert "Agent.kind.in_(kinds)" in source
    # No kind literal in the reconcile path: a future kind is covered for free.
    assert "kind='customer'" not in source
    assert "kind='sales_intelligence'" not in source


def test_the_messaging_gateway_names_its_agent_deliberately() -> None:
    """`hooks.py` is the CUSTOMER-messaging path; its kind is a documented
    decision, not an accident — a non-customer kind reaches the runtime through
    its own routes instead."""
    from app.modules.ai import hooks

    source = inspect.getsource(hooks._do_auto_reply)
    assert 'resolve_agent_by_kind_optional(session, tenant_id, "customer")' in source


def test_an_unregistered_kind_fails_closed_at_the_guardrail() -> None:
    """A kind with no definition must never run unsupervised."""
    from app.modules.ai import runtime

    source = inspect.getsource(runtime.AgentRunner)
    assert "unknown_agent_kind" in source
    assert '"block"' in source


# ------------------------------------------ 3. the DB-backed proof (CI only) ---


async def test_a_third_canonical_kind_is_provisioned_automatically(db, tenant_ctx):
    """Needs `DATABASE_URL_APP_ADMIN` — skips locally.

    The end-to-end proof of the contract: register a brand-new canonical kind,
    run provisioning ONCE, and the tenant receives the agent and exactly its
    tools — with no edit to the provisioning code.
    """
    from sqlalchemy import select

    from app.modules.ai.agents.customer.definition import CUSTOMER_TOOLS
    from app.modules.ai.core.provisioning import provision_canonical_agents
    from app.modules.ai.models import AgentTool

    third_kind = _third_definition()
    AgentRegistry.register(third_kind)
    try:
        created = await provision_canonical_agents(db, tenant_ctx.tenant_id)
        await db.flush()

        kinds = {agent.kind for agent in created}
        assert THIRD_KIND in kinds, "provisioning skipped a registered canonical kind"

        agent = next(a for a in created if a.kind == THIRD_KIND)
        tools = (
            (
                await db.execute(
                    select(AgentTool.name).where(
                        AgentTool.tenant_id == tenant_ctx.tenant_id,
                        AgentTool.agent_id == agent.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(tools) == set(third_kind.allowed_tools)
        assert not (set(tools) & set(CUSTOMER_TOOLS)), "the new kind received customer tools"
    finally:
        AgentRegistry._definitions.pop(THIRD_KIND, None)

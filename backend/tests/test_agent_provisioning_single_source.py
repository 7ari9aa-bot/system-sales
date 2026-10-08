"""One source of truth for which agents a tenant is born with.

Two paths used to provision the canonical agents:

* ``identity/bootstrap.seed_tenant_defaults`` inserted ``agents`` +
  ``agent_tools`` with raw SQL and its own hardcoded copy of the name, model,
  system prompt and tool list — written that way to avoid an ``identity -> ai``
  import cycle (review G-16 / spec §137).
* ``ai/core/provisioning.provision_canonical_agents`` built the same rows from
  the ``AgentDefinition`` registry, and is registered as a tenant-created hook.

The register path ran the seeder FIRST and the hook second, and the hook only
fills gaps — so the hardcoded copy won every field it set. That is not a
tidiness complaint: the copies had already drifted. The Sales Intelligence
agent's definition prompt carries the rule that every number in an answer must
come from a tool result; the seeder's copy was a one-line English stub with no
such rule, and SI runs with ``enforce_grounding=False``, so nothing downstream
caught a fabricated figure either. Every tenant created since then has the stub.

The cycle the raw SQL was avoiding no longer exists — ``core.tenancy``'s hook
registry is exactly the decoupling it predates — so the seeder stops writing
agent rows and the registry is the only author.
"""

from __future__ import annotations

import pathlib

from sqlalchemy import select

import app.modules.ai  # noqa: F401 — importing the package registers the hook
from app.core.tenancy import dispatch_tenant_created_hooks, tenant_created_hooks
from app.modules.ai.agents.customer.definition import CUSTOMER_SYSTEM_PROMPT, CUSTOMER_TOOLS
from app.modules.ai.agents.sales_intelligence.agent import SI_SYSTEM_PROMPT
from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
from app.modules.ai.core.provisioning import provision_canonical_agents
from app.modules.ai.models import Agent, AgentTool
from app.modules.identity.bootstrap import seed_tenant_defaults

BOOTSTRAP = pathlib.Path(__file__).resolve().parents[1] / "app/modules/identity/bootstrap.py"


async def _provision(db, tenant_id) -> None:
    """The register sequence, in the order identity/service.py runs it."""
    await seed_tenant_defaults(db, tenant_id)
    await dispatch_tenant_created_hooks(db, tenant_id)


async def _agents(db, tenant_id) -> dict[str, Agent]:
    rows = (
        await db.execute(select(Agent).where(Agent.tenant_id == tenant_id))
    ).scalars().all()
    return {a.kind: a for a in rows}


async def _tools(db, tenant_id) -> dict[str, set[str]]:
    rows = (
        await db.execute(
            select(AgentTool.name, Agent.kind)
            .join(Agent, Agent.id == AgentTool.agent_id)
            .where(AgentTool.tenant_id == tenant_id, AgentTool.is_active.is_(True))
        )
    ).all()
    out: dict[str, set[str]] = {}
    for name, kind in rows:
        out.setdefault(kind, set()).add(name)
    return out


def test_the_seeder_no_longer_writes_agent_rows() -> None:
    """The hardcoded copy is gone, not merely second in line.

    Left in place it would keep winning every field it sets, and the next
    definition change would silently not apply to new tenants.
    """
    source = BOOTSTRAP.read_text(encoding="utf-8")
    assert "INSERT INTO agents" not in source
    assert "INSERT INTO agent_tools" not in source
    assert "canonical_agents" not in source


def test_the_definition_path_is_the_registered_hook() -> None:
    assert provision_canonical_agents in tenant_created_hooks(), (
        "nothing would provision agents for a new tenant — the hook is the only "
        "path left now that the seeder does not write agent rows"
    )


async def test_a_new_tenant_gets_the_agents_its_definitions_describe(db, tenant_ctx) -> None:
    await _provision(db, tenant_ctx.tenant_id)

    agents = await _agents(db, tenant_ctx.tenant_id)
    assert set(agents) == {"customer", "sales_intelligence"}
    # The prompt is the field that drifted: these are the definitions' words,
    # including SI's "every number must come from a tool result".
    assert agents["customer"].system_prompt == CUSTOMER_SYSTEM_PROMPT
    assert agents["sales_intelligence"].system_prompt == SI_SYSTEM_PROMPT
    assert agents["customer"].name == "Customer Service Agent"
    assert agents["customer"].model == "fast"
    assert agents["sales_intelligence"].model == "strong"


async def test_a_new_tenant_gets_the_tools_its_definitions_authorize(db, tenant_ctx) -> None:
    await _provision(db, tenant_ctx.tenant_id)

    tools = await _tools(db, tenant_ctx.tenant_id)
    assert tools["customer"] == set(CUSTOMER_TOOLS)
    assert tools["sales_intelligence"] == set(SI_TOOLS)


async def test_provisioning_twice_does_not_double_the_agents(db, tenant_ctx) -> None:
    """Register runs the seeder and the hook in one transaction; a retry, a
    backfill and the hook must all be safe on a tenant that already has them."""
    await _provision(db, tenant_ctx.tenant_id)
    await _provision(db, tenant_ctx.tenant_id)

    agents = await _agents(db, tenant_ctx.tenant_id)
    assert len(agents) == 2
    tools = await _tools(db, tenant_ctx.tenant_id)
    assert len(tools["customer"]) == len(CUSTOMER_TOOLS)
    assert len(tools["sales_intelligence"]) == len(SI_TOOLS)

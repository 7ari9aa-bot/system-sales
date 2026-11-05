"""The agent-catalog endpoint — the console's code-truth view of the agents.

Pins the three behaviours that matter:

* the shared ``x-platform-token`` gate, with an EMPTY configured token meaning
  the endpoint does not exist (404) — the same fail-closed contract as
  impersonation;
* a valid token sees every registered agent kind with its tools projected from
  the ``TOOLS`` spec registry (description + risk level + default flag), so the
  console can never render a stale copy of the runtime's catalog;
* no tenant context is required — this is code truth, not tenant data, and a
  catalog leak is bounded to descriptions by construction.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app

CATALOG_PATH = "/api/v1/platform/agent-catalog"


@pytest.fixture()
def _token(monkeypatch):
    monkeypatch.setattr(get_settings(), "impersonation_platform_token", "test-platform-token")


async def test_an_empty_platform_token_disables_the_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "impersonation_platform_token", "")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(CATALOG_PATH)

    assert resp.status_code == 404, "an unconfigured deployment must not expose the catalog"


async def test_a_wrong_token_is_refused(_token) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(CATALOG_PATH, headers={"x-platform-token": "nope"})

    assert resp.status_code == 403


async def test_the_catalog_lists_the_registered_kinds_with_their_tools(_token) -> None:
    from app.modules.ai.agents.customer import definition as customer_definition  # noqa: F401
    from app.modules.ai.agents.sales_intelligence import definition as si_definition  # noqa: F401
    from app.modules.ai.core.registry import AgentRegistry, discover_agents

    discover_agents()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(CATALOG_PATH, headers={"x-platform-token": "test-platform-token"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    kinds = {agent["kind"] for agent in body["agents"]}
    assert kinds == set(AgentRegistry.kinds()), "the catalog drifted from the live registry"
    assert "customer" in kinds, "the customer agent is the product's core and must be listed"

    customer = next(agent for agent in body["agents"] if agent["kind"] == "customer")
    assert customer["name"]
    assert customer["description"]
    assert customer["tools"], "a catalog with no tools cannot power the console's toggles"
    for tool in customer["tools"]:
        assert tool["description"], f"tool {tool['name']} must carry its merchant-grade description"
        assert tool["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
    names = {tool["name"] for tool in customer["tools"]}
    assert "handover_to_human" in names, "the handover tool is part of the customer agent's story"

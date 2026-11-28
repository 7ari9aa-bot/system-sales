"""The gate a route actually calls, judged without a database.

`workspace_gate` is the function seven routers depend on, so the enforcement is
pinned here with a stub context: the facts are handed in, and what matters is
whether a request is let through, refused, and for which reason.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.errors import PermissionDeniedError
from app.modules.applications import dependencies
from app.modules.applications.access import AccessFacts

KEY = "retail.purchasing"


class _Ctx:
    def __init__(self, states: dict[str, str], entitled: set[str] | None = None) -> None:
        self.session = object()
        self.tenant_id = uuid.uuid4()
        self.workspace_id = uuid.uuid4()
        self._facts = AccessFacts(
            application_key=KEY,
            entitled_applications=frozenset(entitled or set()),
            installation_states=states,
        )


@pytest.fixture()
def facts_from_ctx(monkeypatch):
    """Answer `gather_facts` from the stub context instead of the database."""

    def _install(ctx: _Ctx) -> None:
        async def _fake(session, *, tenant_id, workspace_id, application_key):  # noqa: ANN001
            return ctx._facts

        monkeypatch.setattr(dependencies, "gather_facts", _fake)

    return _install


def _gate(ctx: _Ctx):
    return asyncio.run(dependencies.workspace_gate(KEY, ctx))


def test_an_unpaid_workspace_is_refused_with_403(facts_from_ctx) -> None:
    """The whole point: a workspace with installations but no entitlement is denied."""
    ctx = _Ctx(states={"retail.core": "active"}, entitled=set())
    facts_from_ctx(ctx)
    with pytest.raises(PermissionDeniedError):
        _gate(ctx)


def test_a_dependency_that_is_not_installed_refuses_the_application(facts_from_ctx) -> None:
    """A paid product whose base is missing is still refused, and says which base."""
    ctx = _Ctx(states={KEY: "active"}, entitled={KEY, "retail.core"})
    facts_from_ctx(ctx)
    with pytest.raises(PermissionDeniedError, match="dependency_inactive"):
        _gate(ctx)


def test_a_paid_but_uninstalled_workspace_is_refused(facts_from_ctx) -> None:
    ctx = _Ctx(states={"retail.core": "active"}, entitled={KEY})
    facts_from_ctx(ctx)
    with pytest.raises(PermissionDeniedError):
        _gate(ctx)


def test_an_installed_but_unfinished_setup_is_refused(facts_from_ctx) -> None:
    ctx = _Ctx(states={KEY: "setup_required"}, entitled={KEY})
    facts_from_ctx(ctx)
    with pytest.raises(PermissionDeniedError):
        _gate(ctx)


def test_an_entitled_and_active_application_passes(facts_from_ctx) -> None:
    # retail.purchasing sits on top of retail.core, so both have to be on.
    ctx = _Ctx(states={KEY: "active", "retail.core": "active"}, entitled={KEY, "retail.core"})
    facts_from_ctx(ctx)
    result = _gate(ctx)
    assert result.allowed is True
    assert result.reason == "allowed"


def test_a_workspace_with_no_installations_at_all_still_passes(facts_from_ctx) -> None:
    """The temporary transition rule: every account today has zero rows."""
    ctx = _Ctx(states={}, entitled=set())
    facts_from_ctx(ctx)
    result = _gate(ctx)
    assert result.allowed is True
    assert result.reason == "workspace_not_configured"


def test_a_route_without_a_facts_provider_refuses_to_run() -> None:
    dependency = dependencies.require_application(KEY)
    with pytest.raises(RuntimeError, match="no facts provider"):
        dependency()


def test_the_bypass_is_logged_because_it_is_temporary(facts_from_ctx, caplog) -> None:
    """A workspace outside the gate must leave a trace, not pass in silence."""
    ctx = _Ctx(states={}, entitled=set())
    facts_from_ctx(ctx)
    with caplog.at_level("WARNING", logger="app.modules.applications.dependencies"):
        _gate(ctx)
    assert any("bypassed" in record.message for record in caplog.records), (
        "the transition bypass went unlogged"
    )


def test_a_real_decision_is_not_logged_as_a_bypass(facts_from_ctx, caplog) -> None:
    ctx = _Ctx(states={KEY: "active", "retail.core": "active"}, entitled={KEY, "retail.core"})
    facts_from_ctx(ctx)
    with caplog.at_level("WARNING", logger="app.modules.applications.dependencies"):
        _gate(ctx)
    assert not any("bypassed" in record.message for record in caplog.records)


async def test_install_route_only_touches_the_workspace_in_the_context(monkeypatch) -> None:
    """The workspace id must come from the resolved context, never the request."""
    from app.modules.applications import router as router_module

    seen: dict[str, object] = {}

    async def fake_install(session, *, tenant_id, workspace_id):  # noqa: ANN001
        seen["workspace_id"] = workspace_id
        seen["tenant_id"] = tenant_id
        return ["retail.core"]

    monkeypatch.setattr(router_module, "install_entitled", fake_install)
    ctx = _Ctx(states={}, entitled=set())
    result = await router_module.install_applications(ctx)
    assert seen["workspace_id"] == ctx.workspace_id
    assert seen["tenant_id"] == ctx.tenant_id
    assert result["installed"] == ["retail.core"]


async def test_install_route_refuses_a_context_without_a_workspace() -> None:
    from fastapi import HTTPException

    from app.modules.applications import router as router_module

    ctx = _Ctx(states={}, entitled=set())
    ctx.workspace_id = None
    with pytest.raises(HTTPException) as raised:
        await router_module.install_applications(ctx)
    assert raised.value.status_code == 409

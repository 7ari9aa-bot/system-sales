"""The application registry is the release's answer to "what can be sold".

A commercial row may say an application is for sale and at what price; it may
never say what the application does. These pins keep the code side honest: a
broken registry fails the build instead of the first request that touches a paid
product, and an unknown key fails closed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.platform.applications.access import AccessFacts
from app.platform.applications.dependencies import GateResult, evaluate, require_application
from app.platform.applications.manifests import (
    REGISTRY,
    all_manifests,
    applications_for_industry,
    get_manifest,
    resolve_installation_order,
    validate_registry,
)


def test_the_shipped_registry_is_coherent() -> None:
    assert validate_registry() == []


def test_every_application_names_the_modules_that_own_its_rules() -> None:
    for manifest in all_manifests():
        assert manifest.owner_domain, manifest.key
        assert manifest.api_groups, manifest.key


def test_an_unknown_application_fails_closed() -> None:
    """A typo must never read as "no restriction" — that is how a paid product leaks."""
    with pytest.raises(KeyError):
        get_manifest("retail.purchasingg")


def test_dependencies_install_before_the_application_that_needs_them() -> None:
    order = resolve_installation_order(["apparel.ai_support", "apparel.purchasing"])
    assert order.index("apparel") == 0
    assert order.index("apparel.customers") < order.index("apparel.ai_support")
    assert order.index("apparel") < order.index("apparel.purchasing")


def test_the_base_application_stands_alone() -> None:
    assert get_manifest("apparel").dependencies == ()


def test_each_key_appears_once_however_many_depend_on_it() -> None:
    order = resolve_installation_order(["apparel.purchasing", "apparel.warehouse", "apparel"])
    assert order.count("apparel") == 1


def test_a_dependency_cycle_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    base = get_manifest("apparel")
    monkeypatch.setitem(REGISTRY, "test.a", replace(base, key="test.a", dependencies=("test.b",)))
    monkeypatch.setitem(REGISTRY, "test.b", replace(base, key="test.b", dependencies=("test.a",)))
    with pytest.raises(ValueError, match="cycle"):
        resolve_installation_order(["test.a"])


def test_a_missing_dependency_is_reported_by_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        REGISTRY,
        "test.orphan",
        replace(get_manifest("apparel"), key="test.orphan", dependencies=("does.not.exist",)),
    )
    problems = validate_registry()
    assert any("does.not.exist" in problem for problem in problems)


def test_industry_filter_keeps_every_app_sold_to_every_industry() -> None:
    """Apparel is the only sector in production, and every app ships for it."""
    apparel = applications_for_industry("apparel")
    assert {m.key for m in apparel} == {m.key for m in all_manifests()}


def test_every_route_group_belongs_to_an_application() -> None:
    """A new commercial group must not appear without deciding what sells it."""
    from app.core.route_map.registry import GROUPS
    from app.platform.applications.routing import GROUP_APPLICATIONS

    missing = sorted(set(GROUPS) - set(GROUP_APPLICATIONS))
    assert not missing, f"route groups with no application: {missing}"
    stale = sorted(set(GROUP_APPLICATIONS) - set(GROUPS))
    assert not stale, f"application map names groups that no longer exist: {stale}"


def test_every_mapped_application_exists_in_the_registry() -> None:
    from app.platform.applications.routing import GROUP_APPLICATIONS

    unknown = sorted({app for app in GROUP_APPLICATIONS.values() if app not in REGISTRY})
    assert not unknown, f"groups mapped to applications that do not exist: {unknown}"


def test_an_undecided_group_raises_instead_of_defaulting_to_open() -> None:
    from app.platform.applications.routing import application_for_group

    with pytest.raises(KeyError, match="belongs to no application"):
        application_for_group("not-a-real-group")


# --- application access: every gate, in order, with a reason ---------------


def _facts(**overrides):
    from app.platform.applications.access import AccessFacts

    base = {
        "application_key": "apparel.purchasing",
        "entitled_applications": frozenset({"apparel", "apparel.purchasing"}),
        "installation_states": {"apparel": "active", "apparel.purchasing": "active"},
        "industry": "apparel",
    }
    base.update(overrides)
    return AccessFacts(**base)


def test_a_fully_provisioned_application_is_allowed() -> None:
    from app.platform.applications.access import decide_access

    assert decide_access(_facts()).allowed


def test_an_unknown_application_is_denied_not_ignored() -> None:
    from app.platform.applications.access import decide_access

    decision = decide_access(_facts(application_key="retail.purchasingg"))
    assert not decision.allowed
    assert decision.reason.startswith("unknown_application")


def test_paying_is_not_installing() -> None:
    """Entitled but never installed in this workspace: the screen must not exist."""
    from app.platform.applications.access import decide_access

    decision = decide_access(_facts(installation_states={"apparel": "active"}))
    assert not decision.allowed
    assert decision.reason == "not_installed"


def test_setup_required_is_not_active() -> None:
    from app.platform.applications.access import decide_access

    decision = decide_access(
        _facts(installation_states={"apparel": "active", "apparel.purchasing": "setup_required"})
    )
    assert not decision.allowed
    assert decision.reason == "installation_setup_required"


def test_an_inactive_dependency_closes_the_door() -> None:
    from app.platform.applications.access import decide_access

    decision = decide_access(
        _facts(installation_states={"apparel": "suspended", "apparel.purchasing": "active"})
    )
    assert not decision.allowed
    assert decision.reason == "dependency_inactive:apparel"


def test_a_required_capability_that_is_off_blocks_the_application() -> None:
    from app.platform.applications.access import decide_access

    facts = _facts(
        application_key="apparel.inventory_advanced",
        entitled_applications=frozenset(
            {"apparel", "apparel.warehouse", "apparel.inventory_advanced"}
        ),
        installation_states={
            "apparel": "active",
            "apparel.warehouse": "active",
            "apparel.inventory_advanced": "active",
        },
    )
    decision = decide_access(facts)
    assert not decision.allowed
    assert decision.reason == "capability_missing:lot_expiry"


def test_no_workspace_access_denies_even_a_paid_application() -> None:
    from app.platform.applications.access import decide_access

    decision = decide_access(_facts(user_has_workspace_access=False))
    assert not decision.allowed
    assert decision.reason == "no_workspace_access"


# --- the route gate -------------------------------------------------------


def test_a_licensed_and_active_application_is_allowed() -> None:
    facts = AccessFacts(
        application_key="apparel",
        entitled_applications=frozenset({"apparel"}),
        installation_states={"apparel": "active"},
    )
    assert evaluate(facts, "apparel") == GateResult(True, "allowed")


def test_paying_for_an_application_without_installing_it_is_not_enough() -> None:
    facts = AccessFacts(
        application_key="apparel",
        entitled_applications=frozenset({"apparel"}),
        installation_states={"apparel": "setup_required"},
    )
    verdict = evaluate(facts, "apparel")
    assert not verdict.allowed
    assert verdict.reason == "installation_setup_required"


def test_an_unlicensed_application_is_refused_by_name() -> None:
    facts = AccessFacts(application_key="apparel.purchasing")
    verdict = evaluate(facts, "apparel.purchasing")
    assert not verdict.allowed
    assert verdict.reason == "not_entitled"


def test_an_unknown_application_raises_instead_of_opening() -> None:
    with pytest.raises(KeyError, match="unknown application"):
        evaluate(AccessFacts(application_key="nope.nope"), "nope.nope")


def test_an_unconfigured_workspace_is_the_documented_transition_case() -> None:
    """Every account today has zero installations; closing them all at once is
    a lockout, not enforcement. The reason says so out loud."""
    verdict = evaluate(
        AccessFacts(application_key="apparel"), "apparel", workspace_configured=False
    )
    assert verdict == GateResult(True, "workspace_not_configured")


def test_the_dependency_fails_loudly_until_a_facts_provider_is_wired() -> None:
    dependency = require_application("apparel")
    with pytest.raises(RuntimeError, match="no facts provider"):
        dependency()

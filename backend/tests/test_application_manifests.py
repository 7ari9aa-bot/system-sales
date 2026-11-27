"""The application registry is the release's answer to "what can be sold".

A commercial row may say an application is for sale and at what price; it may
never say what the application does. These pins keep the code side honest: a
broken registry fails the build instead of the first request that touches a paid
product, and an unknown key fails closed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.applications.manifests import (
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
    order = resolve_installation_order(["ai.customer_support", "retail.purchasing"])
    assert order.index("retail.core") == 0
    assert order.index("customer.engagement") < order.index("ai.customer_support")
    assert order.index("retail.core") < order.index("retail.purchasing")


def test_the_base_application_stands_alone() -> None:
    assert get_manifest("retail.core").dependencies == ()


def test_each_key_appears_once_however_many_depend_on_it() -> None:
    order = resolve_installation_order(["retail.purchasing", "retail.warehouse", "retail.core"])
    assert order.count("retail.core") == 1


def test_a_dependency_cycle_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    base = get_manifest("retail.core")
    monkeypatch.setitem(REGISTRY, "test.a", replace(base, key="test.a", dependencies=("test.b",)))
    monkeypatch.setitem(REGISTRY, "test.b", replace(base, key="test.b", dependencies=("test.a",)))
    with pytest.raises(ValueError, match="cycle"):
        resolve_installation_order(["test.a"])


def test_a_missing_dependency_is_reported_by_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        REGISTRY,
        "test.orphan",
        replace(get_manifest("retail.core"), key="test.orphan", dependencies=("does.not.exist",)),
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
    from app.modules.applications.routing import GROUP_APPLICATIONS

    missing = sorted(set(GROUPS) - set(GROUP_APPLICATIONS))
    assert not missing, f"route groups with no application: {missing}"
    stale = sorted(set(GROUP_APPLICATIONS) - set(GROUPS))
    assert not stale, f"application map names groups that no longer exist: {stale}"


def test_every_mapped_application_exists_in_the_registry() -> None:
    from app.modules.applications.routing import GROUP_APPLICATIONS

    unknown = sorted({app for app in GROUP_APPLICATIONS.values() if app not in REGISTRY})
    assert not unknown, f"groups mapped to applications that do not exist: {unknown}"


def test_an_undecided_group_raises_instead_of_defaulting_to_open() -> None:
    from app.modules.applications.routing import application_for_group

    with pytest.raises(KeyError, match="belongs to no application"):
        application_for_group("not-a-real-group")


# --- application access: every gate, in order, with a reason ---------------


def _facts(**overrides):
    from app.modules.applications.access import AccessFacts

    base = {
        "application_key": "retail.purchasing",
        "entitled_applications": frozenset({"retail.core", "retail.purchasing"}),
        "installation_states": {"retail.core": "active", "retail.purchasing": "active"},
        "industry": "apparel",
    }
    base.update(overrides)
    return AccessFacts(**base)


def test_a_fully_provisioned_application_is_allowed() -> None:
    from app.modules.applications.access import decide_access

    assert decide_access(_facts()).allowed


def test_an_unknown_application_is_denied_not_ignored() -> None:
    from app.modules.applications.access import decide_access

    decision = decide_access(_facts(application_key="retail.purchasingg"))
    assert not decision.allowed
    assert decision.reason.startswith("unknown_application")


def test_paying_is_not_installing() -> None:
    """Entitled but never installed in this workspace: the screen must not exist."""
    from app.modules.applications.access import decide_access

    decision = decide_access(_facts(installation_states={"retail.core": "active"}))
    assert not decision.allowed
    assert decision.reason == "not_installed"


def test_setup_required_is_not_active() -> None:
    from app.modules.applications.access import decide_access

    decision = decide_access(
        _facts(installation_states={"retail.core": "active", "retail.purchasing": "setup_required"})
    )
    assert not decision.allowed
    assert decision.reason == "installation_setup_required"


def test_an_inactive_dependency_closes_the_door() -> None:
    from app.modules.applications.access import decide_access

    decision = decide_access(
        _facts(installation_states={"retail.core": "suspended", "retail.purchasing": "active"})
    )
    assert not decision.allowed
    assert decision.reason == "dependency_inactive:retail.core"


def test_a_required_capability_that_is_off_blocks_the_application() -> None:
    from app.modules.applications.access import decide_access

    facts = _facts(
        application_key="retail.inventory_advanced",
        entitled_applications=frozenset(
            {"retail.core", "retail.warehouse", "retail.inventory_advanced"}
        ),
        installation_states={
            "retail.core": "active",
            "retail.warehouse": "active",
            "retail.inventory_advanced": "active",
        },
    )
    decision = decide_access(facts)
    assert not decision.allowed
    assert decision.reason == "capability_missing:lot_expiry"


def test_no_workspace_access_denies_even_a_paid_application() -> None:
    from app.modules.applications.access import decide_access

    decision = decide_access(_facts(user_has_workspace_access=False))
    assert not decision.allowed
    assert decision.reason == "no_workspace_access"

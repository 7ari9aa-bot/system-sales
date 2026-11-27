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

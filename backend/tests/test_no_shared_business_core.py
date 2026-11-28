"""No shared Business Core, and no route group without a sector owner.

The architecture allows exactly two levels: platform infrastructure and industry
applications. A manifest named ``retail.core`` that other products depend on is
the third level the document forbids, so this test fails if one comes back, and
it also pins the bridge that keeps a not-yet-migrated database working.
"""

from __future__ import annotations

from app.platform.applications.manifests import (
    LEGACY_KEYS,
    REGISTRY,
    all_manifests,
    get_manifest,
    normalize_key,
    resolve_installation_order,
)
from app.platform.applications.routing import GROUP_APPLICATIONS, application_for_group


def test_no_manifest_calls_itself_a_core() -> None:
    assert [m.key for m in all_manifests() if m.key.split(".")[-1] == "core"] == []


def test_every_application_is_namespaced_under_its_sector() -> None:
    # One sector ships today: apparel. A second sector adds its own prefix here.
    assert {m.key.split(".")[0] for m in all_manifests()} == {"apparel"}


def test_the_base_application_is_the_sector_application() -> None:
    base = get_manifest("apparel")
    assert base.title_en == "FIHRIST Apparel"
    assert base.dependencies == ()


def test_every_dependency_resolves_and_installs_in_order() -> None:
    keys = tuple(REGISTRY)
    ordered = resolve_installation_order(keys)
    assert set(ordered) == set(keys)
    assert ordered.index("apparel") == 0


def test_legacy_keys_point_at_a_shipped_application() -> None:
    for legacy, current in LEGACY_KEYS.items():
        assert current in REGISTRY, f"{legacy} points at {current}, which does not exist"
        assert get_manifest(legacy).key == current
        assert normalize_key(current) == current


def test_a_current_key_is_left_alone() -> None:
    assert normalize_key("apparel") == "apparel"


def test_every_route_group_is_owned_by_a_shipped_application() -> None:
    for group, key in GROUP_APPLICATIONS.items():
        assert key in REGISTRY, f"route group {group!r} points at unknown {key!r}"
        assert application_for_group(group) == key

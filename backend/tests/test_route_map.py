"""The route map must match the code, both ways, or CI fails.

A developer who adds a route in a new group, moves a route to another module, or names a capability
that does not exist gets a failure that says which line of ``route_map/registry.py`` to edit.
"""

from __future__ import annotations

import pytest

from app.core.route_map.registry import (
    CAPABILITY_ROUTES,
    CORE,
    GROUPS,
    SCOPE_MODULES,
    capability_of,
    scope_of,
)
from app.core.route_map.scan import ACCESS_KINDS, scan
from app.main import create_app
from app.modules.settings.capabilities import CAPABILITIES


@pytest.fixture(scope="module")
def routes():
    return scan(create_app())


@pytest.fixture(scope="module")
def scoped(routes):
    return [r for r in routes if r.module in SCOPE_MODULES]


def test_every_scoped_route_belongs_to_a_registered_group(scoped):
    missing = sorted({r.group for r in scoped if r.group not in GROUPS})
    assert not missing, (
        f"Route group(s) {missing} are served by a mapped module but not listed. "
        "Add a line to GROUPS in app/core/route_map/registry.py."
    )


def test_a_group_is_served_only_by_the_modules_it_names(scoped):
    wrong = sorted(
        f"{r.key} is in module {r.module}, registry says {GROUPS[r.group].module}"
        for r in scoped
        if r.group in GROUPS and not GROUPS[r.group].owns(r.module)
    )
    assert not wrong, wrong


def test_no_group_in_the_registry_is_dead(routes):
    live = {r.group for r in routes}
    dead = sorted(g for g in GROUPS if g not in live)
    assert not dead, f"GROUPS lists {dead} but no route is served there any more. Remove the line."


def test_every_group_points_at_a_module_in_scope():
    stray = sorted(g for g, v in GROUPS.items() if v.module not in SCOPE_MODULES)
    assert not stray, f"{stray} name a module that is not in SCOPE_MODULES."


def test_capability_names_exist():
    named = {g.capability for g in GROUPS.values()} | {c for _, c in CAPABILITY_ROUTES}
    unknown = sorted(c for c in named if c != CORE and c not in CAPABILITIES)
    assert not unknown, f"Unknown capability {unknown}. Valid: {sorted(CAPABILITIES)} or '{CORE}'."


def test_every_capability_exception_matches_a_real_route(scoped):
    unused = [frag for frag, _ in CAPABILITY_ROUTES if not any(frag in r.path for r in scoped)]
    assert not unused, f"CAPABILITY_ROUTES fragments match no route: {unused}"


def test_access_kind_is_always_one_we_know(routes):
    assert {r.access for r in routes} <= set(ACCESS_KINDS)


def test_a_permission_route_always_names_its_permission(routes):
    bad = [r.key for r in routes if r.access == "permission" and not r.permissions]
    assert not bad, bad


def test_scope_follows_the_capability(scoped):
    for r in scoped:
        cap = capability_of(r.path, GROUPS[r.group])
        assert scope_of(cap) == ("core" if cap == CORE else "vertical")


def test_the_scan_sees_the_whole_api(routes):
    """Guards the scanner: the API has ~600 operations, so a near-empty scan is a bug."""
    assert len(routes) > 550
    assert len({r.module for r in routes}) > 25

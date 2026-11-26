"""The account workspace: three read routes, and the words that keep them apart.

The codebase has two things called a workspace. The account workspace (the tenant) is
what the settings map means; the §151 hierarchy workspace is an internal level inside
a tenant, managed under Locations. They are different resources with different routes,
and confusing them would put a branch's settings on the container's page. These tests
pin the routes, the mount, and the role set that counts as "administers the workspace".
"""

from __future__ import annotations

from app.modules.identity.routers.workspaces import workspaces_router
from app.modules.identity.services.workspace import ADMIN_ROLES, WorkspaceService


def _paths(router) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }


def test_the_three_read_routes_exist() -> None:
    paths = _paths(workspaces_router)
    assert ("GET", "/workspaces") in paths
    assert ("GET", "/workspaces/current") in paths
    assert ("GET", "/workspaces/current/admins") in paths


def test_nothing_on_this_router_writes() -> None:
    """Switching workspace is a session change (/auth/switch-tenant), not a workspace edit."""
    methods = {method for method, _path in _paths(workspaces_router)}
    assert methods == {"GET"}


def test_the_account_workspace_is_not_the_hierarchy_workspace() -> None:
    """The hierarchy level lives under /hierarchy, so the two can never shadow each other."""
    from app.modules.identity.routers.hierarchy import hierarchy_router

    assert all(route.path.startswith("/hierarchy") for route in hierarchy_router.routes)
    assert all(not route.path.startswith("/hierarchy") for route in workspaces_router.routes)


def test_owner_and_admin_are_the_roles_that_run_a_workspace() -> None:
    assert ADMIN_ROLES == ("owner", "admin")


def test_the_service_answers_the_three_questions_the_pages_ask() -> None:
    for name in ("memberships", "overview", "admins"):
        assert callable(getattr(WorkspaceService, name))


def test_the_router_is_mounted() -> None:
    """Mounting is a separate fact from defining: main.py lists routers by hand."""
    from app import main

    source = main.__file__ and open(main.__file__, encoding="utf-8").read()
    assert "workspaces_router as identity_workspaces_router" in source
    assert "identity_workspaces_router," in source

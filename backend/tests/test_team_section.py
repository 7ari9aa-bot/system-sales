"""Team & permissions: the routes, and the one rule that keeps teams harmless.

The section's risk is not a missing button, it is a team that quietly grants access.
A team is a grouping; permissions come from ``role_permissions`` and the location
grants. These tests pin that invariant structurally, and pin the routes the six
pages call so a page cannot point at an endpoint that does not exist.
"""

from __future__ import annotations

from app.platform.identity.models import Team, TeamMember
from app.platform.identity.routers.roles import roles_router
from app.platform.identity.routers.teams import teams_router
from app.platform.identity.routers.tenants import tenants_router
from app.platform.identity.services.teams import TeamService


def _operations(router) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }


def test_team_routes() -> None:
    ops = _operations(teams_router)
    assert ("GET", "/teams") in ops
    assert ("POST", "/teams") in ops
    assert ("PATCH", "/teams/{team_id}") in ops
    assert ("DELETE", "/teams/{team_id}") in ops
    assert ("GET", "/teams/{team_id}/members") in ops
    assert ("PUT", "/teams/{team_id}/members/{user_id}") in ops
    assert ("DELETE", "/teams/{team_id}/members/{user_id}") in ops


def test_team_membership_carries_no_role() -> None:
    """A team that could grant would be a second permission system."""
    columns = set(TeamMember.__table__.columns.keys())
    assert "role_id" not in columns
    assert "role_code" not in columns
    assert "permissions" not in columns
    # and the team itself does not carry one either
    assert "role_id" not in set(Team.__table__.columns.keys())


def test_every_team_table_is_tenant_scoped() -> None:
    """Tenant on both tables, so the RLS policy is a plain comparison."""
    assert "tenant_id" in Team.__table__.columns
    assert "tenant_id" in TeamMember.__table__.columns


def test_permission_matrix_is_read_only() -> None:
    """Editing the matrix would let a workspace grant what the guards do not know."""
    methods = {method for method, _path in _operations(roles_router)}
    assert methods == {"GET"}


def test_membership_routes() -> None:
    """Invitations are listed by the existing /invitations route, not a second copy."""

    ops = _operations(tenants_router)
    assert ("PUT", "/tenants/{tenant_id}/members/{user_id}") in ops
    assert ("DELETE", "/tenants/{tenant_id}/members/{user_id}") in ops


def test_the_service_covers_every_operation_the_pages_need() -> None:
    for name in (
        "list_teams",
        "create_team",
        "rename_team",
        "delete_team",
        "members",
        "add_member",
        "remove_member",
    ):
        assert callable(getattr(TeamService, name))

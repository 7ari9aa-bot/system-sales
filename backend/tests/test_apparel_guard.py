"""The apparel gate refuses the right things for the right reasons.

Every case here is one the architecture names: no workspace, unknown
permission, licence suspended, read-only versus a write, and a user who simply
does not hold the code. A gate that only ever says yes is not a gate.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.applications.apparel.guard import (
    UNCONFIGURED,
    apparel_access,
    decide_apparel_access,
    is_write,
)
from app.core.errors import PermissionDeniedError

TENANT = "11111111-1111-1111-1111-111111111111"
WORKSPACE = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"

ALL_CODES = frozenset({"apparel.pos.sell", "apparel.reports.view"})


def _ctx(*, session=None, workspace_id=WORKSPACE, user_id=USER, codes=ALL_CODES):
    return SimpleNamespace(
        session=session,
        tenant_id=TENANT,
        workspace_id=workspace_id,
        user=SimpleNamespace(id=user_id),
        permission_codes=set(codes),
    )


def test_write_verbs_are_recognised() -> None:
    assert is_write("apparel.pos.sell") is True
    assert is_write("apparel.products.create") is True
    assert is_write("apparel.reports.view") is False
    assert is_write("apparel.dashboard.view") is False


def test_an_installed_workspace_with_the_permission_is_allowed() -> None:
    access = decide_apparel_access(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        user_id=USER,
        permission_code="apparel.pos.sell",
        held_codes=ALL_CODES,
        installation_state="active",
    )
    assert access.permission_code == "apparel.pos.sell"
    assert access.read_only is False


def test_read_only_allows_reading_and_refuses_writing() -> None:
    decide_apparel_access(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        user_id=USER,
        permission_code="apparel.reports.view",
        held_codes=ALL_CODES,
        installation_state="read_only",
    )
    with pytest.raises(PermissionDeniedError, match="read only"):
        decide_apparel_access(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            user_id=USER,
            permission_code="apparel.pos.sell",
            held_codes=ALL_CODES,
            installation_state="read_only",
        )


def test_a_suspended_licence_is_refused() -> None:
    with pytest.raises(PermissionDeniedError, match="suspended"):
        decide_apparel_access(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            user_id=USER,
            permission_code="apparel.reports.view",
            held_codes=ALL_CODES,
            installation_state="suspended",
        )


def test_a_missing_permission_is_refused_by_name() -> None:
    with pytest.raises(PermissionDeniedError, match="apparel.pos.sell"):
        decide_apparel_access(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            user_id=USER,
            permission_code="apparel.pos.sell",
            held_codes=frozenset({"apparel.reports.view"}),
            installation_state="active",
        )


def test_no_workspace_is_refused_before_anything_else() -> None:
    with pytest.raises(PermissionDeniedError, match="workspace"):
        decide_apparel_access(
            tenant_id=TENANT,
            workspace_id=None,
            user_id=USER,
            permission_code="apparel.reports.view",
            held_codes=ALL_CODES,
            installation_state="active",
        )


def test_an_unknown_permission_code_is_a_programming_error() -> None:
    with pytest.raises(KeyError):
        decide_apparel_access(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            user_id=USER,
            permission_code="apparel.not_a_real_code",
            held_codes=ALL_CODES,
            installation_state="active",
        )


@pytest.mark.asyncio
async def test_a_context_without_a_session_still_checks_the_permission() -> None:
    """The cheap refusal: no database read, but never a free pass."""
    access = await apparel_access(_ctx(), "apparel.reports.view")
    assert access.installation_state == UNCONFIGURED

    with pytest.raises(PermissionDeniedError, match="missing permission"):
        await apparel_access(_ctx(codes=set()), "apparel.reports.view")

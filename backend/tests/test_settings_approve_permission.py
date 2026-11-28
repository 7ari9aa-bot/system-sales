"""Reviewing a settings change is a permission of its own.

Approving or rejecting a change request required ``settings:write``, so any reviewer
also held the power to change every key directly — and a shop could not have a manager
who reviews proposals without being able to write settings. ``settings:approve`` is now
its own grant, held by owner and manager, and a cashier still holds neither.
"""

from __future__ import annotations

import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROUTER = (BACKEND / "app/platform/settings/router.py").read_text(encoding="utf-8")
MIGRATION = (BACKEND / "migrations/versions/fe2026112604_settings_approve_permission.py").read_text(
    encoding="utf-8"
)


def _endpoint(name: str) -> str:
    start = ROUTER.index(f"async def {name}(")
    rest = ROUTER[start + 10 :]
    return ROUTER[start : start + 10 + rest.index("\n@")]


def test_approve_and_reject_accept_settings_approve() -> None:
    for endpoint in ("approve_change_request", "reject_change_request"):
        body = _endpoint(endpoint)
        assert "settings:approve" in body, f"{endpoint} still demands settings:write only"


def test_a_write_holder_can_still_review() -> None:
    """The owner holds settings:write and must not lose the ability to review."""
    body = _endpoint("approve_change_request")
    assert '"settings:write"' in body


def test_the_permission_is_created_and_granted_to_owner_and_manager() -> None:
    assert "'settings:approve', 'settings', 'approve'" in MIGRATION
    assert "r.code IN ('owner', 'manager')" in MIGRATION
    assert "settings:approve" in MIGRATION.split("def downgrade")[0]


def test_downgrade_removes_only_this_permission() -> None:
    down = MIGRATION.split("def downgrade")[1]
    assert "settings:approve" in down
    assert not re.search(r"DELETE FROM permissions\s*;", down), "downgrade wipes the table"


def test_cashier_does_not_get_it() -> None:
    granted = re.findall(r"r\.code IN \(([^)]*)\)", MIGRATION)
    assert granted, "no role grant found"
    for group in granted:
        assert "cashier" not in group

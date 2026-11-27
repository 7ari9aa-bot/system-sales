"""A policy can vanish while its migration still reads "applied".

On 27 Nov ``invitations_accept_read`` was absent from production while
``alembic_version`` read ``fe2026112608``: every ``POST /invitations/accept``
answered 404 for a valid token, and no log line said so. A stamped revision
never re-runs, so the recovery has to be (a) a migration that re-creates the
object idempotently and (b) a startup invariant that reports the drift.

These pins keep both halves honest.
"""

from __future__ import annotations

import pathlib

from app.core.boot import REQUIRED_NAMED_POLICIES

_BACKEND = pathlib.Path(__file__).resolve().parents[1]


def test_the_invitation_accept_policy_is_a_required_invariant() -> None:
    assert ("invitations", "invitations_accept_read") in REQUIRED_NAMED_POLICIES


def test_a_migration_recreates_every_required_named_policy() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (_BACKEND / "migrations/versions").glob("*.py")
    )
    for table, policy in REQUIRED_NAMED_POLICIES:
        assert f"CREATE POLICY {policy} ON {table}" in sources, (
            f"no migration creates {policy} on {table}, so a database where the "
            "policy was lost has no path back to a working public flow"
        )


def test_the_recovery_migration_is_idempotent() -> None:
    recovery = _BACKEND / "migrations/versions/fe2026112609_reassert_invitation_accept_policy.py"
    source = recovery.read_text(encoding="utf-8")
    assert "DROP POLICY IF EXISTS invitations_accept_read" in source
    assert "CREATE POLICY invitations_accept_read" in source

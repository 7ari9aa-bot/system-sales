"""A load-bearing object can vanish while its migration still reads "applied".

On 27 Nov ``invitations_accept_read`` was absent from production while ``alembic_version``
read ``fe2026112608``: every ``POST /invitations/accept`` answered 404 for a valid token, and
no log line said so. The repair that followed re-created that policy, which was the wrong
object: a second permissive policy on a tenant table is OR-ed with ``tenant_isolation``, so a
session that could set ``app.invitation_token`` could read the invitation row. The accept flow
resolves its tenant with ``public.invitation_tenant_by_token`` and then reads under the bound
tenant, so the function is the object to watch and the policy is the hole to keep closed.

These pins keep all three halves honest: nothing requires a second policy, the function is
required, and a migration converges a database that lost either.
"""

from __future__ import annotations

import pathlib

from app.core.boot import REQUIRED_NAMED_POLICIES, REQUIRED_PUBLIC_FUNCTIONS

_BACKEND = pathlib.Path(__file__).resolve().parents[1]


def test_no_tenant_table_requires_a_second_permissive_policy() -> None:
    assert REQUIRED_NAMED_POLICIES == (), (
        "every tenant table carries exactly tenant_isolation; requiring another policy here "
        "would OR-open the table for any session that can set its predicate"
    )


def test_the_invitation_lookup_is_a_required_invariant() -> None:
    assert ("public", "invitation_tenant_by_token") in REQUIRED_PUBLIC_FUNCTIONS


def test_a_migration_recreates_every_required_function() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (_BACKEND / "migrations/versions").glob("*.py")
    )
    for schema, function in REQUIRED_PUBLIC_FUNCTIONS:
        assert f"CREATE OR REPLACE FUNCTION {schema}.{function}(" in sources, (
            f"no migration creates {schema}.{function}, so a database that lost it has no "
            "path back to a working public flow"
        )


def test_the_converging_migration_drops_the_permissive_policy_and_never_restores_it() -> None:
    converging = (
        _BACKEND / "migrations/versions/fe2026112619_invitation_lookup_not_a_second_policy.py"
    )
    source = converging.read_text(encoding="utf-8")
    assert "DROP POLICY IF EXISTS invitations_accept_read" in source
    assert "CREATE POLICY invitations_accept_read" not in source, (
        "re-creating the policy re-opens the table beside tenant_isolation"
    )
    assert "CREATE OR REPLACE FUNCTION public.invitation_tenant_by_token(" in source

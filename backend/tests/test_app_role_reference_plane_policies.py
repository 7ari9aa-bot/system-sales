"""Every `sales_app_read` policy a migration declares must be re-issued by provision.py.

The failure this pins is fe2026100805's, and it is silent in the worst way
---------------------------------------------------------------------------
fd2026100410 made the RBAC reference plane (`permissions`, `roles`,
`role_permissions`, `plans`) SELECT-only for the runtime role; fd2026100502
then ENABLEd RLS on those four tables; fe2026100805 finally created the
`sales_app_read` policies that make the reads work. But the migration creates
each policy under

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app')

— required, because CI's alembic runs before that role exists — and the guard
is also the hole. CI's order is `alembic upgrade head` → `python
scripts/provision.py` → `pytest`, so at migration time every policy is
skipped, and RLS enabled with no policy is not "restrict some reads": it is
DENY ALL for every non-owner. The first symptom is not a permission error —
a plain SELECT just returns zero rows — so every DB-backed test dies at setup
with `NoResultFound` on `Role.code == "owner"` (conftest cannot build a
tenant context), and any environment running the documented runtime DSN has
no working RBAC plane at all.

The rule is convergence, not a list: for every reference-plane policy the
migration declares, `provision.py` must re-issue the same statement after it
creates the role. Same shape as `test_app_role_function_grants.py` (EXECUTE
grants), `test_snapshot_truncate_freeze.py` (TRUNCATE freeze) and
`test_migrations.py` (channel resolver) — each is a deploy-order pair where
only the provision half can run in CI.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND = Path(__file__).resolve().parent.parent
PROVISION_PATH = BACKEND / "scripts" / "provision.py"
MIGRATIONS_DIR = BACKEND / "migrations" / "versions"
POLICY_MIGRATION = MIGRATIONS_DIR / "fe2026100805_reference_plane_rls_read_policy.py"

#: The four tables fd2026100410 made SELECT-only and fd2026100502 put under RLS.
REFERENCE_TABLES = ("permissions", "roles", "role_permissions", "plans")

_POLICY_RE = re.compile(
    r"CREATE\s+POLICY\s+sales_app_read\s+ON\s+public\.(\w+)",
    re.IGNORECASE,
)


def _policies_in(text_blob: str) -> set[str]:
    # Implicit string concatenation in source splits one statement in two.
    joined = re.sub(r'"\s*\n\s*"', "", text_blob)
    return {m.group(1).lower() for m in _POLICY_RE.finditer(joined)}


def _setup_app_role_body() -> str:
    source = PROVISION_PATH.read_text(encoding="utf-8")
    _, _, rest = source.partition("async def setup_app_role")
    assert rest, "setup_app_role is gone from provision.py"
    return rest.split("\nasync def ", 1)[0]


# ------------------------------------------------------- the premise -------


def test_the_migration_declares_the_reference_plane_policies() -> None:
    """Non-vacuity guard: the four tables really are policy-covered upstream.

    A probe that matched nothing would make the convergence check below pass
    for the wrong reason; this also fails when fe2026100805's contract itself
    changes, forcing this file to move with it. The table names live in the
    migration's `_REFERENCE_TABLES` constant (the SQL interpolates them), so
    read the constant rather than regexing the statement text.
    """
    source = POLICY_MIGRATION.read_text(encoding="utf-8")
    declared: list[str] = []
    for node in ast.walk(ast.parse(source)):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "_REFERENCE_TABLES":
                declared = [
                    elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)
                ]
    assert set(declared) == set(REFERENCE_TABLES), (
        "fe2026100805 no longer covers exactly the four reference-plane tables; "
        "update REFERENCE_TABLES here to the migration's contract"
    )
    assert (
        source.count("IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app')") >= 1
    ), "the migration's policy creation must stay guarded on the role existing"


# ------------------------------------------------------ the rule -----------


def test_every_reference_plane_policy_is_reissued_by_provision() -> None:
    """A migration-only policy is RLS with no policy: DENY ALL for sales_app."""
    provisioned = _policies_in(PROVISION_PATH.read_text(encoding="utf-8"))
    missing = set(REFERENCE_TABLES) - provisioned
    assert not missing, (
        f"provision.py never creates sales_app_read on {sorted(missing)}; CI "
        "creates the role after alembic runs, so the migration's guarded policy "
        "was skipped — every DB-backed test then errors at setup and the "
        "runtime role cannot read its own role permissions."
    )


def test_the_policies_run_after_the_role_is_created() -> None:
    """Ordering is the point: a policy FOR sales_app needs the role to exist."""
    body = _setup_app_role_body()
    created = body.find("CREATE ROLE sales_app")
    applied = body.find("REFERENCE_PLANE_READ_POLICIES")
    assert created != -1, "setup_app_role no longer creates the app role"
    assert applied != -1, "setup_app_role never applies REFERENCE_PLANE_READ_POLICIES"
    assert created < applied, "the reference-plane policies run before CREATE ROLE"

    source = PROVISION_PATH.read_text(encoding="utf-8")
    declared: list[str] = []
    for node in ast.walk(ast.parse(source)):
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == "REFERENCE_PLANE_READ_POLICIES":
            declared = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
    assert declared, "provision.py declares no REFERENCE_PLANE_READ_POLICIES"
    provisioned = {t.lower() for stmt in declared for t in _policies_in(stmt)}
    missing = set(REFERENCE_TABLES) - provisioned
    assert not missing, f"{sorted(missing)} are not in provision.py's policy tuple"


# ------------------------------------------------- CI-only: the bit -------


async def test_the_app_role_reads_the_reference_plane(db: AsyncSession) -> None:
    """The privilege, read off the database rather than off the source text.

    RLS without a policy fails silently — a plain SELECT returns zero rows,
    not an error — which is exactly how fe2026100805's gap hid until pytest's
    session fixture could no longer resolve `Role.code == "owner"`.
    """
    user, is_super, bypasses = (
        await db.execute(
            text(
                "SELECT current_user, "
                "(SELECT coalesce(bool_or(r.rolsuper), false) "
                " FROM pg_roles r WHERE r.rolname = current_user), "
                "(SELECT coalesce(bool_or(r.rolbypassrls), false) "
                " FROM pg_roles r WHERE r.rolname = current_user)"
            )
        )
    ).one()
    if is_super or bypasses:
        pytest.skip(f"{user!r} is a superuser/BYPASSRLS — RLS is not enforced")

    for table in REFERENCE_TABLES:
        rows = (
            await db.execute(text(f"SELECT count(*) FROM public.{table}"))
        ).scalar_one()
        assert rows > 0, (
            f"sales_app reads zero rows from public.{table} — the table is "
            "under RLS with no usable policy for the runtime role (DENY ALL), "
            "which denies every require_permission call"
        )

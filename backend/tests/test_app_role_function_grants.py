"""The app role must hold EXECUTE on every function a migration granted it.

Why this is a separate rule from the table grants
-------------------------------------------------
Migration `f7a2c9d4e8b1` creates four `SECURITY DEFINER` maintenance functions
and makes them reachable by the application exactly one way:

    REVOKE ALL ON FUNCTION ... FROM PUBLIC;
    DO $$ IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT EXECUTE ON FUNCTION ... TO sales_app;

The guard is required — CI is plain Postgres and `sales_app` does not exist when
alembic runs — and the guard is also the hole. CI's order is
`alembic upgrade head` → `python scripts/provision.py` → `pytest`, so at
migration time the role is absent, every guarded `GRANT` is skipped, and
`setup_app_role` then blanket-grants TABLES and SEQUENCES and never touches
FUNCTIONS. The application role ends the pipeline holding no EXECUTE anywhere.

That is not a cosmetic ACL difference; it is the runtime calling a function the
database refuses: `core/partitioning` raises `PartitionMaintenanceUnavailable`
and the retention worker cannot ask "did every tenant choose a policy". Both are
§55–57 paths that pass in isolation and fail in CI — the failure mode Wave C's
review named.

The rule is therefore convergence, not a list: for every `GRANT EXECUTE … TO
sales_app` a migration declares, `provision.py` must re-issue the same statement
after it creates the role. Pinned beside the precedent for the same shape in
`test_snapshot_truncate_freeze.py` (TRUNCATE) and `test_migrations.py` (the
channel resolver).
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

APP_ROLE = "sales_app"

#: The functions the application role calls by name at runtime.
MAINTENANCE_FUNCTIONS = (
    "public.partitioning_ensure_partition(text, date)",
    "public.partitioning_ensure_months(text, integer)",
    "public.retention_drop_horizon(text)",
    "public.partitioning_purge_month(text, date)",
)

_GRANT_RE = re.compile(
    rf"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+([\w.]+\([^)]*\))\s+TO\s+{APP_ROLE}",
    re.IGNORECASE,
)


def _grants_in(text_blob: str) -> set[str]:
    # Implicit string concatenation in source splits one statement in two.
    joined = re.sub(r'"\s*\n\s*"', "", text_blob)
    return {m.group(1).lower() for m in _GRANT_RE.finditer(joined)}


def _grants_declared_by_migrations() -> set[str]:
    """Every function signature a migration hands to the app role."""
    found: set[str] = set()
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found |= _grants_in(node.value)
    return found


def _setup_app_role_body() -> str:
    source = PROVISION_PATH.read_text(encoding="utf-8")
    _, _, rest = source.partition("async def setup_app_role")
    assert rest, "setup_app_role is gone from provision.py"
    return rest.split("\nasync def ", 1)[0]


def _grants_reissued_by_provision() -> set[str]:
    """Every EXECUTE grant provision.py issues, anywhere in the script."""
    return _grants_in(PROVISION_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------- the premise -------


def test_the_migrations_do_grant_the_app_role_function_execute() -> None:
    """The hole is real: these grants exist only inside a role-exists guard.

    Also the non-vacuity guard for the probe below — a regex that matched
    nothing would make `test_every_function_..._reissued_by_provision` pass for
    the wrong reason.
    """
    declared = _grants_declared_by_migrations()
    assert declared, "no migration grants EXECUTE to sales_app: the probe matches nothing"
    missing = {sig.lower() for sig in MAINTENANCE_FUNCTIONS} - declared
    assert not missing, f"{sorted(missing)} are not granted by any migration"


def test_a_migration_grant_never_ships_unguarded() -> None:
    """`sales_app` may not exist when alembic runs, so each grant is conditional.

    If this ever passes vacuously because someone removed the guards, the
    convergence rule above becomes optional — which is exactly the drift it
    exists to prevent.
    """
    sql = (MIGRATIONS_DIR / "f7a2c9d4e8b1_w4_partition_ai_usage_chosen_retention.py").read_text(
        encoding="utf-8"
    )
    assert sql.count("IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app')") >= len(
        MAINTENANCE_FUNCTIONS
    ), "a maintenance-function grant is no longer guarded on the role existing"


# ------------------------------------------------------ the rule -----------


def test_every_function_the_migrations_grant_is_reissued_by_provision() -> None:
    """A migration-only grant is a grant the app role does not hold in CI."""
    declared = _grants_declared_by_migrations()
    missing = declared - _grants_reissued_by_provision()
    assert not missing, (
        f"provision.py never grants the app role EXECUTE on {sorted(missing)}; "
        "CI creates the role after alembic runs, so the migration's guarded GRANT "
        "was skipped and these calls fail with `permission denied for function`."
    )


def test_the_grants_run_after_the_role_is_created() -> None:
    """Ordering is the point: a GRANT to a missing role aborts provisioning.

    The statements live in one declared tuple that `setup_app_role` applies after
    its `CREATE ROLE` — the same shape `PRIVILEGE_REFREEZE` uses, so the next
    rule added has an obvious place and an existing order to respect.
    """
    body = _setup_app_role_body()
    created = body.find("CREATE ROLE sales_app")
    applied = body.find("FUNCTION_EXECUTE_GRANTS")
    assert created != -1, "setup_app_role no longer creates the app role"
    assert applied != -1, "setup_app_role never applies FUNCTION_EXECUTE_GRANTS"
    assert created < applied, "the function grants run before CREATE ROLE"

    source = PROVISION_PATH.read_text(encoding="utf-8")
    declared: list[str] = []
    for node in ast.walk(ast.parse(source)):
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == "FUNCTION_EXECUTE_GRANTS":
            declared = [
                elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)
            ]
    assert declared, "provision.py declares no FUNCTION_EXECUTE_GRANTS"
    signatures = {sig.lower() for stmt in declared for sig in _grants_in(stmt)}
    missing = [sig for sig in MAINTENANCE_FUNCTIONS if sig.lower() not in signatures]
    assert not missing, f"{missing} are not in provision.py's function-grant tuple"


# ------------------------------------------------- CI-only: the bit -------


async def test_the_app_role_holds_execute_on_the_maintenance_functions(
    db: AsyncSession,
) -> None:
    """The privilege, read off the database rather than off the source text."""
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
        pytest.skip(f"{user!r} is a superuser/BYPASSRLS — privileges are not enforced")
    # Vacuity guard: this must be the role the rule is written against.
    holds_table_grant = (
        await db.execute(
            text("SELECT has_table_privilege(current_user, 'public.invoices', 'SELECT')")
        )
    ).scalar_one()
    assert holds_table_grant, (
        f"{user!r} is not the provisioned app role (no table grants at all), so "
        "the EXECUTE checks below would pass for the wrong reason"
    )

    for signature in MAINTENANCE_FUNCTIONS:
        granted = (
            await db.execute(
                text(
                    "SELECT has_function_privilege(current_user, :sig, 'EXECUTE')"
                ),
                {"sig": signature},
            )
        ).scalar_one()
        assert granted is True, (
            f"{user} cannot EXECUTE {signature} — the application calls it, and "
            "the migration that revoked PUBLIC ran before this role existed"
        )

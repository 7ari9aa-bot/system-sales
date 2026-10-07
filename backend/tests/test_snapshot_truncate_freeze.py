"""Spec §53–54 — the frozen snapshot must also survive `TRUNCATE`.

What was already true, and what was not
--------------------------------------
Migration `e7a8b9c0d1e2` made an UPDATE or a DELETE of a closed period
refusable BY THE DATABASE (a BEFORE UPDATE OR DELETE row trigger keyed on
``period_start IS NOT NULL``). Reading this file alongside that one, the
guarantee looked complete. It is not, and the hole is exactly the statement the
row trigger never fires for:

    TRUNCATE TABLE invoices;   -- every closed period, gone, in one statement

PostgreSQL is explicit about it: TRUNCATE fires only *truncate* triggers — no
row triggers, no rules, no cascaded deletes — and the manual warns it should be
used with care for that reason. So the immutability rule that "holds against
writers the application never sees" had a single-statement bypass that a
backfill script, a mis-typed ops command, or a restore helper walks straight
into — and it is worse than an UPDATE, because it erases *every* snapshot at
once and leaves nothing to audit against.

It is reachable by the app role, not just by an operator: `invoices` is granted
to ``sales_app`` by the blanket

    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sales_app

(`scripts/provision.py::setup_app_role`), and "ALL PRIVILEGES" on a table
includes TRUNCATE. So the convention "nobody truncates billing" was carrying a
privilege the runtime role holds.

The two halves, and why BOTH are needed
---------------------------------------
1. **A BEFORE TRUNCATE statement trigger** that always raises. This is the half
   that binds *everyone who is not the superuser disabling triggers*, including
   the table owner and the migration role, because a trigger fires regardless of
   privileges and ``GRANT`` cannot hand one back. It is also the durable half:
   `provision.py` re-issues its blanket grant on every run, so a privilege
   revoke alone would be dissolved by the next deploy.
2. **`REVOKE TRUNCATE ON public.invoices FROM sales_app`**, guarded on the role
   existing (CI is plain Postgres and `sales_app` may not exist yet when
   alembic runs — the same guard `b2c3d4e5f6a7` and `f1a2b3c4d5e6` use). This is
   the half that refuses the statement at the permission check, *before* any
   trigger machinery, so it still holds on a database where someone has disabled
   or dropped the trigger. Because of (1)'s durability problem, provision.py
   re-asserts the same statement right after its blanket grant —
   `test_the_provision_refreeze_is_the_migrations_statement` below pins that
   the two copies cannot drift, following the precedent set by
   `test_resolver_sql_matches_between_migration_and_provision`.

Why NOT a privilege revoke on UPDATE/DELETE as well
---------------------------------------------------
Privileges are ROW-BLIND. `REVOKE UPDATE ON invoices` would freeze the ordinary
invoice lifecycle too (`status` draft -> open -> paid, `issued_at`/`paid_at`,
and the `ON DELETE SET NULL` cascades from `subscriptions`/`workspaces` that
UPDATE `subscription_id`/`workspace_id` on every invoice the tenant owns), and
the column-level variant cannot subtract from the table-level grant the blanket
`GRANT ALL` provides — column privileges are a UNION with table privileges, so
`REVOKE UPDATE (total)` is a no-op while `GRANT ALL` stands. TRUNCATE is the one
statement on this table that is never legitimate for any row, which is what
makes it revocable without collateral damage. `test_truncating_any_other_table_is_untouched`
below is the negative control for that narrowing.

Who can still get past this (stated, not glossed)
------------------------------------------------
* Every NON-OWNER role is bound by both halves, which is the case that matters:
  the API and the workers are ``sales_app``, it is created WITHOUT BYPASSRLS, it
  does not own the table, and a role that does not own a table can neither drop
  nor disable its triggers. So for `sales_app` the refusal is a permission error
  before it is a trigger, and it survives `SET LOCAL` tricks, ALTERs and re-runs
  of the application.
* The table **owner** (`postgres` / `supabase_admin`, i.e. the migration and
  provisioning role) is bound by the TRIGGER only. An owner holds its table's
  privileges implicitly, so `REVOKE` cannot bind it, and the owner can drop or
  disable the guard and then truncate. The owner can also simply `DROP TABLE
  invoices`, which no trigger here can prevent — that is the same trust
  boundary `e7a8b9c0d1e2` already accepted, and it is why migrations are a
  reviewed code path.
* A **superuser** additionally may `SET session_replication_role = replica`,
  which skips non-origin triggers entirely.
* A restore from backup replaces the whole table by definition.

CI-only vs local: every test below named `db` is gated on
`DATABASE_URL_APP_ADMIN` (conftest skips it locally, so the TRUNCATE refusal can
only be OBSERVED in CI, where the suite connects as `sales_app`). The rest run
anywhere.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.models import Invoice, UsageRecord
from app.modules.billing.service import BillingSnapshotService

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION_PATH = (
    BACKEND / "migrations" / "versions" / "a9b0c1d2e3f4_invoice_snapshot_truncate_freeze.py"
)
PROVISION_PATH = BACKEND / "scripts" / "provision.py"

#: The head this revision must extend. An applied revision is immutable, so a
#: new rule arrives as a NEW file whose down_revision is today's head.
CURRENT_HEAD = "f7a2c9d4e8b1"
#: The role the API and the workers connect as (scripts/provision.py).
APP_ROLE = "sales_app"
#: The single privilege statement, spelled once and compared everywhere.
TRUNCATE_REVOKE_SQL = "REVOKE TRUNCATE ON public.invoices FROM sales_app"
#: The guard's own words: used to prove WHICH failure the database produced.
GUARD_MESSAGE = "cannot TRUNCATE"

PERIOD_START = date(2026, 8, 1)
PERIOD_END = date(2026, 9, 1)


# ------------------------------------------------ the migration (DB-free) --


class _RecordingOp:
    """Permissive Alembic `op` stand-in: records execute(), no-ops the rest."""

    def __init__(self, captured: list[str]) -> None:
        self._captured = captured

    def execute(self, sql, *args, **kwargs) -> None:
        if isinstance(sql, str):
            self._captured.append(sql)

    def __getattr__(self, name: str):
        return lambda *a, **k: None


def _load_migration() -> tuple[object, list[str]]:
    captured: list[str] = []
    spec = importlib.util.spec_from_file_location(
        "snapshot_truncate_freeze_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = _RecordingOp(captured)  # type: ignore[attr-defined]
    return module, captured


def _upgraded_sql() -> str:
    module, captured = _load_migration()
    module.upgrade()  # type: ignore[attr-defined]
    return "\n".join(captured)


def test_the_revision_descends_from_the_current_head() -> None:
    """`alembic upgrade head` branches — and the deploy stops — on a wrong parent."""
    module, _ = _load_migration()
    assert module.revision != CURRENT_HEAD
    assert module.down_revision == CURRENT_HEAD


def test_truncate_is_refused_by_a_statement_trigger() -> None:
    """Row triggers never fire for TRUNCATE, so the guard must be a statement one.

    `FOR EACH ROW` here would be a silent no-op: PostgreSQL only runs
    statement-level triggers for TRUNCATE.
    """
    sql = _upgraded_sql()
    assert "BEFORE TRUNCATE ON public.invoices" in sql
    assert "FOR EACH STATEMENT" in sql
    assert "RAISE EXCEPTION" in sql
    assert GUARD_MESSAGE in sql


def test_the_guard_is_idempotent_and_reversible_in_shape() -> None:
    """Deploy safety, copied from the precedent this closes.

    `CREATE OR REPLACE FUNCTION` + `DROP TRIGGER IF EXISTS` make a re-run a no-op
    on a database that already has the guard; `downgrade()` drops exactly the two
    objects `upgrade()` made.
    """
    module, captured = _load_migration()
    sql = _upgraded_sql()
    assert "CREATE OR REPLACE FUNCTION public.invoices_truncate_guard()" in sql
    assert "DROP TRIGGER IF EXISTS" in sql

    after_upgrade = len(captured)
    module.downgrade()  # type: ignore[attr-defined]
    down = "\n".join(captured[after_upgrade:])
    assert "DROP TRIGGER IF EXISTS" in down
    assert "DROP FUNCTION IF EXISTS public.invoices_truncate_guard()" in down


def test_the_revoke_is_guarded_on_the_role_existing() -> None:
    """Plain-Postgres CI has no `sales_app` when alembic runs.

    provision.py creates that role and CI runs migrations FIRST, so an unguarded
    `REVOKE ... FROM sales_app` aborts `alembic upgrade head` with `role "
    sales_app" does not exist`. This is the guard `b2c3d4e5f6a7` and
    `f1a2b3c4d5e6` already use.
    """
    sql = _upgraded_sql()
    assert TRUNCATE_REVOKE_SQL in sql
    assert "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app')" in sql


def test_the_migration_sql_parses_as_postgresql() -> None:
    """Offline syntax proof: a malformed statement fails the deploy, not a test."""
    pglast = pytest.importorskip("pglast", reason="pglast is a dev-only parser")
    module, captured = _load_migration()
    module.upgrade()  # type: ignore[attr-defined]
    for sql in captured:
        pglast.parser.parse_sql(sql)


# ------------------------------------------- the convention side (no DB) ----


def _app_sources() -> list[Path]:
    return sorted((BACKEND / "app").rglob("*.py"))


#: SQL that would mutate a snapshot row through the session or a raw statement.
_MUTATING_SQL = re.compile(
    r"\b(UPDATE\s+(public\.)?invoices\b|DELETE\s+FROM\s+(public\.)?invoices\b"
    r"|\bTRUNCATE\b[^;]{0,40}\binvoices\b)",
    re.IGNORECASE,
)


def test_no_application_code_ever_mutates_an_invoice_row() -> None:
    """The code path refuses to issue an UPDATE at all — asserted, not assumed.

    Two directions guard the same fact. Application code must not build
    `update(Invoice)` / `delete(Invoice)`, and must not carry raw SQL that names
    the table as a mutation target. The database rule is what makes a violation
    harmless; this makes it visible in review instead of discovered in prod.
    """
    offenders: list[str] = []
    for path in _app_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name not in {"update", "delete"} or not node.args:
                    continue
                target = node.args[0]
                root = target.value if isinstance(target, ast.Attribute) else target
                if getattr(root, "id", None) == "Invoice":
                    offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno} {name}(Invoice)")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _MUTATING_SQL.search(node.value):
                    offenders.append(
                        f"{path.relative_to(BACKEND)}:{getattr(node, 'lineno', 0)} mutating SQL"
                    )
    assert not offenders, "application code mutates invoices: " + "; ".join(offenders)


def test_the_mutating_sql_probe_is_not_vacuous() -> None:
    """A guard that matches nothing proves nothing.

    `test_no_application_code_ever_mutates_an_invoice_row` passes on an empty
    offender list, which is also what it would print if the probe were broken.
    Feed it the statements it exists to catch.
    """
    for statement in (
        "UPDATE invoices SET total = 999.99 WHERE id = $1",
        "update public.invoices set status = 'void'",
        "DELETE FROM invoices WHERE period_start IS NOT NULL",
        "delete from public.invoices where period_start is not null",
        "TRUNCATE TABLE invoices",
        "TRUNCATE invoices",
    ):
        assert _MUTATING_SQL.search(statement), f"the probe missed: {statement}"

    for benign in (
        "SELECT total FROM invoices WHERE id = $1",
        "INSERT INTO invoices (id, tenant_id) VALUES ($1, $2)",
        "a BEFORE UPDATE OR DELETE trigger refuses the mutation",
    ):
        assert not _MUTATING_SQL.search(benign), f"the probe cries wolf at: {benign}"


def test_the_provision_refreeze_is_the_migrations_statement() -> None:
    """The privilege half must survive `provision.py`, or it is not a rule.

    CI order is `alembic upgrade head` -> `python scripts/provision.py` ->
    `pytest`, and `setup_app_role` ends with `GRANT ALL PRIVILEGES ON ALL TABLES
    IN SCHEMA public TO sales_app`, which hands TRUNCATE straight back. A revoke
    that lives only in the migration is therefore dissolved before a single test
    runs — so the same statement is re-issued after the blanket grant, and this
    test pins (a) the order and (b) that the two copies are the SAME statement.
    """
    source = PROVISION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    refreeze: list[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) or isinstance(node, ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(getattr(t, "id", None) == "PRIVILEGE_REFREEZE" for t in targets):
                refreeze = list(ast.literal_eval(node.value))
    assert refreeze is not None, (
        "provision.py declares no PRIVILEGE_REFREEZE — the blanket GRANT ALL "
        "restores TRUNCATE on invoices and the §53–54 rule silently disappears"
    )
    assert TRUNCATE_REVOKE_SQL in refreeze, (
        f"the re-freeze statement drifted from the migration: {refreeze}"
    )

    body = source.split("async def setup_app_role", 1)
    assert len(body) == 2, "setup_app_role is gone from provision.py"
    setup = body[1].split("\nasync def ", 1)[0]
    blanket = setup.find("GRANT ALL PRIVILEGES ON ALL TABLES")
    applied = setup.find("PRIVILEGE_REFREEZE")
    assert blanket != -1, "setup_app_role no longer blanket-grants every table"
    assert applied != -1, "setup_app_role never applies the re-freeze"
    assert blanket < applied, (
        "the re-freeze must run AFTER the blanket grant — before it, GRANT ALL "
        "simply puts TRUNCATE back on invoices"
    )


# ---------------------------------------------------------------- helpers --


async def _closed_invoice(db: AsyncSession, tenant_id: uuid.UUID) -> Invoice:
    """Freeze a period through the real service — the legitimate writer."""
    db.add(
        UsageRecord(
            tenant_id=tenant_id,
            feature="messages",
            quantity=Decimal("10.00"),
            period_date=PERIOD_START,
        )
    )
    await db.flush()
    return await BillingSnapshotService.close_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )


async def _role_probe(db: AsyncSession) -> tuple[str, bool, bool]:
    """(current_user, is superuser, bypasses rls) — is this run worth trusting?

    One row ALWAYS comes back: through the Supavisor pooler the connected
    username is `sales_app.<project-ref>`, which is no `pg_roles.rolname`, so a
    JOIN-shaped query would raise NoResultFound instead of telling us anything.
    """
    row = (
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
    return str(row[0]), bool(row[1]), bool(row[2])


# --------------------------------------------- CI-only: the refusal itself --


async def test_the_app_role_holds_no_truncate_privilege(db: AsyncSession) -> None:
    """The grants analysis, executed rather than asserted in a docstring.

    Before: `GRANT ALL PRIVILEGES ON ALL TABLES` gave sales_app TRUNCATE here.
    After: `has_table_privilege(... 'TRUNCATE')` is false. This is the half that
    a re-run of provision.py used to dissolve.
    """
    user, is_super, bypasses = await _role_probe(db)
    if is_super or bypasses:
        pytest.skip(
            f"DATABASE_URL_APP_ADMIN points at {user!r}, which is a superuser or "
            "BYPASSRLS — the privilege rule cannot be observed through it"
        )
    granted = (
        await db.execute(
            text("SELECT has_table_privilege(current_user, 'public.invoices', 'TRUNCATE')")
        )
    ).scalar_one()
    # Vacuity guard: `False` is only interesting if this connection is the role
    # the rule was written against. A connection with no grants anywhere would
    # pass the assertion below for the wrong reason.
    still = (
        await db.execute(
            text(
                "SELECT has_table_privilege(current_user, 'public.invoices', 'SELECT'), "
                "has_table_privilege(current_user, 'public.invoices', 'INSERT')"
            )
        )
    ).one()
    assert still[0] and still[1], (
        f"{user!r} holds no SELECT/INSERT on invoices at all, so it is not the app "
        "role this rule is written against and the check below proves nothing"
    )
    assert granted is False, (
        f"{user} can still TRUNCATE public.invoices — every closed billing period "
        "in the database can be erased by one statement"
    )

    # The refusal must be observable as an actual statement, not only as a bit
    # in an ACL: run the thing and require the database to say no. Either half
    # of the rule may produce the denial — the permission check first, the
    # trigger on a database where the grant was handed back.
    with pytest.raises(DBAPIError) as exc:
        async with db.begin_nested():
            await db.execute(text("TRUNCATE TABLE invoices"))
    message = str(exc.value)
    assert GUARD_MESSAGE in message or "permission denied for table invoices" in message, (
        f"TRUNCATE was refused by something other than the snapshot freeze: {message}"
    )


async def test_the_database_refuses_truncating_invoices(db: AsyncSession, tenant_ctx) -> None:
    """THE rule this change adds. Raw SQL, so only the database can satisfy it.

    A savepoint isolates the aborted statement; without it the surrounding test
    transaction would be poisoned and the follow-up read impossible.
    """
    invoice = await _closed_invoice(db, tenant_ctx.tenant_id)
    invoice_id = invoice.id

    with pytest.raises(DBAPIError) as exc:
        async with db.begin_nested():
            await db.execute(text("TRUNCATE TABLE invoices"))

    message = str(exc.value)
    assert GUARD_MESSAGE in message or "permission denied for table invoices" in message, (
        f"TRUNCATE was refused by something other than the snapshot freeze: {message}"
    )

    surviving = (
        await db.execute(text("SELECT count(*) FROM invoices WHERE id = :id"), {"id": invoice_id})
    ).scalar_one()
    assert surviving == 1, "a TRUNCATE erased a closed billing period"


async def test_an_update_of_a_closed_snapshot_is_still_refused(
    db: AsyncSession, tenant_ctx
) -> None:
    """The half `e7a8b9c0d1e2` already closed, re-pinned beside the new one.

    The new guard must not weaken the row guard: both statement forms have to be
    refused for the period to be immutable in anything but name.
    """
    invoice = await _closed_invoice(db, tenant_ctx.tenant_id)
    invoice_id = invoice.id

    with pytest.raises(DBAPIError) as exc:
        async with db.begin_nested():
            await db.execute(
                text("UPDATE invoices SET total = 999.99 WHERE id = :id"),
                {"id": invoice_id},
            )
    assert "frozen billing snapshot" in str(exc.value), (
        f"the UPDATE was refused by something else: {exc.value}"
    )

    total = (
        await db.execute(text("SELECT total FROM invoices WHERE id = :id"), {"id": invoice_id})
    ).scalar_one()
    assert total == Decimal("0.00")


async def test_the_legitimate_insert_path_still_writes_a_snapshot(
    db: AsyncSession, tenant_ctx
) -> None:
    """Freezing the table must not freeze metering.

    `POST /billing/periods/close` -> `BillingSnapshotService.close_period` is the
    only writer, and it INSERTs. Both guards are TRUNCATE-specific, so the insert
    still has to land — otherwise this migration has broken §53's metering while
    "improving" §54.
    """
    invoice = await _closed_invoice(db, tenant_ctx.tenant_id)
    invoice_id = invoice.id
    tenant_id = tenant_ctx.tenant_id

    assert invoice.period_start == PERIOD_START
    assert invoice.period_end == PERIOD_END

    db.expire_all()
    reread = await BillingSnapshotService.get_snapshot(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )
    assert reread.id == invoice_id
    assert reread.extra["snapshot"], "the snapshot payload is not on the frozen row"


async def test_truncate_is_revoked_schema_wide(db: AsyncSession) -> None:
    """The G-04 contract supersedes the one-table narrowing of §53–54.

    fd2026100409 revokes TRUNCATE on ALL tables (and from the default ACL):
    TRUNCATE bypasses RLS and row triggers, so the runtime role holding it on
    ANY table — `usage_records` included — leaves that table one statement
    from mass erasure for every tenant. The old negative control ("only
    invoices loses it") asserted exactly the world this hardening closes.
    """
    user, is_super, bypasses = await _role_probe(db)
    if is_super or bypasses:
        pytest.skip(f"{user!r} is a superuser/BYPASSRLS: privileges are not enforced")
    granted = (
        await db.execute(
            text("SELECT has_table_privilege(current_user, 'public.usage_records', 'TRUNCATE')")
        )
    ).scalar_one()
    assert granted is False, (
        "the app role can still TRUNCATE an ordinary table — the G-04 "
        "schema-wide revoke (and its default-ACL freeze) is not in force"
    )

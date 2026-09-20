"""Alembic migration invariants.

These are static checks over the migration scripts — no database required.
They exist because two classes of defect here are invisible to the unit suite
and only surface at deploy time, when `alembic upgrade head` is the FIRST step
of the release and its failure blocks everything behind it:

1. A guard expression spliced into a `format()` string instead of being passed
   as an argument puts a raw single quote inside a single-quoted literal, so
   the plpgsql block fails to parse.
2. An index dropped in `downgrade()` but never created in `upgrade()` — the
   `ON CONFLICT` clause that targets it then fails at runtime.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"
HARDENING_MIGRATION = (
    VERSIONS_DIR / "b2c3d4e5f6a7_hardening_rls_segments_worker_columns.py"
)


class _RecordingOp:
    """Permissive Alembic `op` stand-in: records execute(), no-ops everything else.

    `upgrade()` of every migration is invoked, so any op method a migration
    happens to use must resolve — otherwise the test fails for an unrelated
    reason and stops being a reliable guard.
    """

    def __init__(self, captured: list[str]) -> None:
        self._captured = captured

    def execute(self, sql, *args, **kwargs) -> None:
        if isinstance(sql, str):
            self._captured.append(sql)

    def f(self, name: str) -> str:
        return name

    def __getattr__(self, name: str):
        return lambda *a, **k: None


def _load_migration(path: Path):
    """Import a migration module and capture everything it sends to op.execute."""
    captured: list[str] = []
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.op = _RecordingOp(captured)
    return module, captured


_DOLLAR_TAG = re.compile(r"\$([A-Za-z_]*)\$")


def _strip_dollar_quoted(sql: str) -> str:
    """Remove dollar-quoted regions, honouring the tag.

    A naive non-greedy regex pairs the opening `$$` of a DO block with the next
    `$g$` inside it, which exposes the body and makes the statement count wrong.
    """
    out: list[str] = []
    i = 0
    while i < len(sql):
        match = _DOLLAR_TAG.match(sql, i)
        if match:
            tag = match.group(0)
            end = sql.find(tag, match.end())
            if end == -1:
                out.append(sql[i:])
                break
            i = end + len(tag)
            continue
        out.append(sql[i])
        i += 1
    return "".join(out)


def _statement_count(sql: str) -> int:
    """Count statements in `sql`, ignoring dollar-quoted function bodies."""
    stripped = _strip_dollar_quoted(sql)
    return len([part for part in stripped.split(";") if part.strip()])


def _all_migrations() -> list[Path]:
    return sorted(p for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("__"))


def test_no_migration_issues_multiple_statements_per_execute() -> None:
    """asyncpg rejects multiple commands in a single execute().

    Migrations run through asyncpg, whose extended-query protocol accepts one
    statement per call: passing "CREATE INDEX ...; ALTER TABLE ...;" fails with
    `cannot insert multiple commands into a prepared statement`, aborting
    `alembic upgrade head` — the first step of every deploy. This must be
    checked across EVERY migration, not just the newest one: a revision that
    already exists in history still runs on every fresh database and in CI.
    """
    offenders: list[str] = []
    for path in _all_migrations():
        module, captured = _load_migration(path)
        if hasattr(module, "upgrade"):
            module.upgrade()
        for sql in captured:
            count = _statement_count(sql)
            if count > 1:
                offenders.append(f"{path.name} ({count} statements): {sql.strip()[:60]}")
    assert not offenders, "op.execute() called with multiple statements:\n" + "\n".join(
        offenders
    )


def test_migration_files_are_importable() -> None:
    """Every migration must at least import — a syntax error blocks the deploy."""
    paths = sorted(p for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("__"))
    assert paths, "no migrations found"
    for path in paths:
        _load_migration(path)


def test_rls_guards_are_format_arguments_not_spliced() -> None:
    """The guard must reach format() as an argument, never inside the template.

    The original version interpolated the guard into the format string, which
    put `current_setting('app.tenant_id', ...)` inside a single-quoted literal.
    The inner quotes terminate the outer literal, so Postgres rejected the
    whole DO block with `syntax error at or near "app"` and every
    `alembic upgrade head` aborted before applying a single change.
    """
    module, captured = _load_migration(HARDENING_MIGRATION)
    module._rls_do_block()
    assert captured, "_rls_do_block produced no SQL"

    do_block = captured[0]
    # Everything after BEGIN is the loop: it must reference the guards by
    # variable, and must never re-inline a current_setting() call.
    loop_body = do_block.split("BEGIN", 1)[1]
    assert "current_setting" not in loop_body, (
        "guard expression is spliced into the loop body — pass it to format() "
        "as a %s argument instead"
    )
    assert "tenant_guard" in loop_body and "user_guard" in loop_body
    # Dollar-quoted declarations, so the inner quotes need no escaping.
    assert do_block.count("$g$") == 4
    assert "USING (tenant_id = %s" in loop_body


def test_rls_policy_statements_parse() -> None:
    """The CREATE POLICY text the loop generates must be valid SQL."""
    pglast = pytest.importorskip("pglast", reason="pglast is a dev-only parser")
    module, _ = _load_migration(HARDENING_MIGRATION)

    tenant_guard = module._TENANT_GUARD
    user_guard = module._USER_GUARD
    statements = [
        f'CREATE POLICY tenant_isolation ON public."orders" '
        f"USING (tenant_id = {tenant_guard}) WITH CHECK (tenant_id = {tenant_guard})",
        f'CREATE POLICY tenant_isolation ON public."tenant_users" '
        f"USING (tenant_id = {tenant_guard} OR user_id = {user_guard}) "
        f"WITH CHECK (tenant_id = {tenant_guard} OR user_id = {user_guard})",
    ]
    for statement in statements:
        pglast.parser.parse_sql(statement)


def test_tenant_users_keeps_the_user_guard() -> None:
    """`tenant_users` must NOT get the strict tenant-only policy.

    Membership discovery at login runs BEFORE any tenant GUC exists, so the
    strict policy would hide every row and break sign-in. This must agree with
    scripts/provision.py.
    """
    module, _ = _load_migration(HARDENING_MIGRATION)
    assert "tenant_users" in module._USER_GUARDED
    assert "tenant_users" not in module._RLS_EXEMPT


def test_every_dropped_index_was_created() -> None:
    """`downgrade()` must not drop an index `upgrade()` never created.

    Indexes are created both inline in `upgrade()` and inside helper functions
    (e.g. `_segments_table`), so the "created" set is scanned across the whole
    module rather than only the `upgrade()` body.
    """
    source = HARDENING_MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade()", 1)[1]
    upgrade_source = source.split("def downgrade()", 1)[0]

    created = set(re.findall(r'create_index\(\s*"([^"]+)"', upgrade_source))
    dropped = set(re.findall(r'drop_index\(\s*"([^"]+)"', downgrade_body))

    missing = dropped - created
    assert not missing, f"downgrade drops indexes never created in upgrade: {missing}"


def test_webhook_replay_index_is_unique() -> None:
    """ON CONFLICT (provider, external_event_id) needs a UNIQUE index.

    The model declares a NON-unique index of the same columns, so without this
    the conflict target cannot be inferred and every inbound webhook fails.
    """
    source = HARDENING_MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    match = re.search(
        r'create_index\(\s*"uq_webhook_events_provider_external"(.*?)\n    \)',
        upgrade_body,
        re.DOTALL,
    )
    assert match, "uq_webhook_events_provider_external is never created in upgrade()"
    assert "unique=True" in match.group(1)


def test_channel_tenant_resolver_is_security_definer() -> None:
    """Pre-tenant tenant resolution must not depend on the RLS GUC.

    `integrations` is FORCE-RLS, so a plain SELECT before the tenant is known
    returns zero rows — every inbound webhook was acknowledged while ingesting
    nothing. The resolver must be SECURITY DEFINER with a pinned search_path
    (the mandatory hardening for SECURITY DEFINER functions).
    """
    pglast = pytest.importorskip("pglast", reason="pglast is a dev-only parser")
    module, _ = _load_migration(HARDENING_MIGRATION)

    sql = module._CHANNEL_TENANT_FN
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = public, pg_temp" in sql
    # Only the tenant id may leave the function — never integrations.config.
    assert "SELECT i.tenant_id" in sql
    assert "credentials" not in sql
    # Both the current lifecycle value and the legacy one must resolve.
    assert "'active', 'connected'" in sql
    pglast.parser.parse_sql(sql)


def _effective_sql(sql: str) -> str:
    """Normalise for comparison: drop comment lines, collapse whitespace.

    The two copies are allowed to carry different explanatory comments — what
    must not diverge is the SQL that actually runs.
    """
    lines = [
        line for line in sql.splitlines() if not line.strip().startswith("--")
    ]
    return " ".join(" ".join(lines).split())


def test_resolver_sql_matches_between_migration_and_provision() -> None:
    """The migration and scripts/provision.py must converge on one definition.

    They run in either order, so a behavioural divergence would leave the
    function different depending on which ran last.
    """
    import ast

    module, _ = _load_migration(HARDENING_MIGRATION)
    provision_source = (
        VERSIONS_DIR.parent.parent / "scripts" / "provision.py"
    ).read_text(encoding="utf-8")
    provision_sql = None
    for node in ast.walk(ast.parse(provision_source)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", None) == "CHANNEL_TENANT_FN_SQL":
                    provision_sql = ast.literal_eval(node.value)
    assert provision_sql is not None, "CHANNEL_TENANT_FN_SQL not found in provision.py"
    assert _effective_sql(provision_sql) == _effective_sql(module._CHANNEL_TENANT_FN)


def _declared_columns() -> dict[str, set[str]]:
    """Columns every migration creates, via create_table or add_column."""
    import ast as _ast

    declared: dict[str, set[str]] = {}

    def _add(table: str, col: str) -> None:
        declared.setdefault(table, set()).add(col)

    def _column_name(arg) -> str | None:
        if (
            isinstance(arg, _ast.Call)
            and isinstance(arg.func, _ast.Attribute)
            and arg.func.attr == "Column"
            and arg.args
            and isinstance(arg.args[0], _ast.Constant)
        ):
            return str(arg.args[0].value)
        return None

    for path in _all_migrations():
        tree = _ast.parse(path.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call) or not node.args:
                continue
            func = node.func
            if not isinstance(func, _ast.Attribute):
                continue
            if not isinstance(node.args[0], _ast.Constant):
                continue
            table = str(node.args[0].value)
            if func.attr == "create_table":
                for arg in node.args[1:]:
                    col = _column_name(arg)
                    if col:
                        _add(table, col)
            elif func.attr == "add_column" and len(node.args) > 1:
                col = _column_name(node.args[1])
                if col:
                    _add(table, col)
    return declared


# Tables whose DDL lives inside a plpgsql DO block, so the AST cannot see their
# columns: e1f2a3b4c5d6 creates/alters `notifications` conditionally
# (CREATE TABLE ... ELSE ALTER TABLE ... ADD COLUMN IF NOT EXISTS). Listed
# explicitly rather than weakening the check for every table.
_DYNAMIC_DDL_TABLES = frozenset({"notifications"})


def test_every_model_column_is_created_by_a_migration() -> None:
    """Model/migration drift fails at RUNTIME, not at import.

    A column on the model that no migration creates surfaces as
    `UndefinedColumnError` on the first INSERT — which is exactly how the
    ai_budget_reservations model came to declare workspace_id/location_id
    (from a mixin) that its migration never created. This catches that class of
    drift statically, before a deploy.
    """
    from app.core.model_registry import Base

    declared = _declared_columns()
    assert declared, "no create_table/add_column found — the parser is broken"

    problems: list[str] = []
    for table, columns in declared.items():
        model = Base.metadata.tables.get(table)
        if model is None or table in _DYNAMIC_DDL_TABLES:
            continue
        missing = sorted(set(model.c.keys()) - columns)
        if missing:
            problems.append(f"{table}: model declares {missing} that no migration creates")

    assert not problems, "model/migration column drift: " + "; ".join(problems)


async def test_not_null_server_defaults_exist_in_the_database(db) -> None:
    """A model that declares a server_default for a NOT NULL column the database
    created without one makes SQLAlchemy omit that column from the INSERT, so
    every insert fails with NotNullViolationError.

    This is exactly how `notifications.channel` was broken: the model declared
    `server_default="inapp"`, the table was created `NOT NULL` with no default,
    and `NotificationService.create()` could never insert a row. The AST guard
    above cannot see it because `notifications`' DDL lives in a plpgsql DO
    block, so this one checks the live schema instead.

    Only NOT NULL columns are checked. A missing default on a nullable column is
    harmless (the INSERT just writes NULL), so flagging those would be noise.
    """
    from sqlalchemy import text

    from app.core.model_registry import Base

    rows = (
        await db.execute(
            text(
                "SELECT table_name, column_name, column_default "
                "FROM information_schema.columns WHERE table_schema = 'public'"
            )
        )
    ).all()
    db_columns = {(table, column): default for table, column, default in rows}
    db_tables = {table for table, _ in db_columns}
    assert db_columns, "information_schema returned no columns — migrations not applied?"

    problems: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in db_tables:
            continue
        for column in table.c:
            # A Python-side default supplies the value client-side, so a missing
            # database default cannot break the INSERT.
            if column.server_default is None or column.default is not None:
                continue
            if column.nullable:
                continue
            key = (table_name, column.name)
            if key in db_columns and db_columns[key] is None:
                problems.append(f"{table_name}.{column.name}")

    assert not problems, (
        "model declares server_default for NOT NULL column(s) that the database "
        "has no default for; SQLAlchemy omits them on INSERT: "
        + ", ".join(sorted(problems))
    )

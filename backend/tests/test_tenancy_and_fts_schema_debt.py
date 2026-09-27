"""Schema debt: untenanted `workflow_versions`, missing FTS, unnamed constraints.

Three register lines, one file. Each is a SCHEMA claim, so each is checked
against the DDL the migrations actually emit rather than against a live
database — which matters because locally there is none:

    SKIPPED [1] ...: no app database URL configured (DATABASE_URL_APP_ADMIN)

The guards below therefore run everywhere, including a laptop with no Postgres.
The two tests at the bottom that DO need a database are marked CI-only in their
docstrings and are the ones that skip without `DATABASE_URL_APP_ADMIN`.

What is being kept honest:

(a) `workflow_versions` carries no `tenant_id` (models.py:66-85), so the
    b2c3d4e5f6a7 RLS sweep — which is dynamic over "tables having a tenant_id
    column" — walked straight past it. `GET /workflows/{id}/versions` is then
    isolated ONLY by the `WorkflowService.get()` call in front of it, i.e. by
    the caller's memory, not by the database. The golden rule says RLS must
    reflect ownership.
(b) spec §45 asked for full-text search; `core/search.py` ships `ILIKE '%…%'`
    and says so in its own docstring. Add real tsvector + GIN. `simple` is not
    a taste choice: a GENERATED column must be IMMUTABLE, and the 1-argument
    `to_tsvector(text)` is only STABLE — the config HAS to be spelled out. Once
    it must be spelled out, `simple` is also the only config that treats Arabic
    and Latin alike without stemming one of them into a different word.
(c) register O2 claimed the `segments` migration was empty and the model
    unregistered. `24037e2ebc05` IS empty, but `b2c3d4e5f6a7` creates the table
    and `model_registry` imports the model — the line is stale. A guard here
    stops it being re-filed, and stops the empty revision from being mistaken
    for the live definition.
(d) register O3: the downgrade chain dies on `op.drop_constraint(None, ...)`.
    The whole repo has ~145 of them; this slice has 22 unnamed constraints on
    six tables, and every one of them is now named by explicit DDL.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import pkgutil
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR

from tests.test_migrations import _all_migrations, _statement_count

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"

TENANCY_MIGRATION = VERSIONS_DIR / "a1f2c3d4e5b6_workflow_versions_tenancy_rls.py"
FTS_MIGRATION = VERSIONS_DIR / "b2e3d4f5a6c7_full_text_search_tsvector_gin.py"
NAMING_MIGRATION = VERSIONS_DIR / "c3f4e5a6b7d8_name_slice_constraints.py"

# The six tables this branch touches: (a)'s child and its parent, (b)'s three
# searched tables, and (c)'s segment table.
SLICE_TABLES = (
    "workflow_versions",
    "workflows",
    "customers",
    "products",
    "knowledge_items",
    "segments",
)

_SEARCH_TABLES = ("customers", "products", "knowledge_items")

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


# ------------------------------------------------------------------ recorder
class _Recorder:
    """Alembic `op` stand-in that records EVERY call, not just execute().

    The existing `_RecordingOp` in `tests/test_migrations.py` captures only SQL
    strings, which is right for its statement-count guard. These guards assert on
    structured ops (`add_column`, `create_unique_constraint`, …) so the names,
    column lists and `ondelete` must survive to be inspected.
    """

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.calls: list[tuple[str, tuple, dict]] = []

    def execute(self, sql, *args, **kwargs) -> None:
        if isinstance(sql, str):
            self.executed.append(sql)

    def f(self, name: str) -> str:
        return name

    def __getattr__(self, name: str):
        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _record

    def of(self, *names: str):
        wanted = set(names)
        return [c for c in self.calls if c[0] in wanted]


def _load(path: Path) -> tuple[object, _Recorder]:
    assert path.exists(), f"migration missing: {path.name}"
    spec = importlib.util.spec_from_file_location(f"mig_{path.name[:12]}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rec = _Recorder()
    module.op = rec
    return module, rec


def _upgrade(path: Path) -> tuple[object, _Recorder]:
    module, rec = _load(path)
    module.upgrade()
    return module, rec


def _all_executed(path: Path) -> str:
    _, rec = _upgrade(path)
    return "\n".join(rec.executed)


def _find_call(calls, name: str, target: str):
    """The first `name(...)` call whose first string arg is `target`."""
    for op_name, args, kwargs in calls:
        if op_name != name:
            continue
        flat = [a for a in args if isinstance(a, str)] + [
            v for v in kwargs.values() if isinstance(v, str)
        ]
        if target in flat:
            return args, kwargs
    return None


# ------------------------------------------------------------- chain shape
def test_the_three_new_revisions_exist_and_chain_from_the_head() -> None:
    """Rule 5: ONE head. A second head breaks the whole build (§C11 did).

    The three revisions must hang off each other in order and the first must
    name the head that existed before this branch — not some older revision,
    which would drop every migration in between out of the chain.
    """
    ids = {}
    for path in _all_migrations():
        src = path.read_text(encoding="utf-8")
        # Two template generations coexist here: the current
        # `revision: str = "..."` / `down_revision: str | None = "..."` and the
        # older quoted/`Union[...]` form Alembic ships in script.py.mako. Both
        # are valid, so the guard must read both — a regex that only matches one
        # reports a fork that does not exist.
        rev = re.search(r"^revision:\s*\S+\s*=\s*[\"']([^\"']+)[\"']", src, re.M)
        down = re.search(
            r"^down_revision:\s*[^=]+=\s*(?:None|[\"']([0-9a-f]{12})[\"'])", src, re.M
        )
        assert rev, f"{path.name}: no parseable `revision` assignment"
        assert down, f"{path.name}: no parseable `down_revision` assignment"
        ids[path.name[:12]] = (rev.group(1), down.group(1) if down.group(1) else None)

    roots = {r for r, (_, parent) in ids.items() if parent is None}
    orphan_roots = roots - {"0b79f7470c1a"}
    assert not orphan_roots, f"extra chain root(s) would fork the history: {orphan_roots}"

    # exactly one revision nobody points at
    pointed_to = {parent for _, parent in ids.values() if parent}
    tail = set(ids) - pointed_to
    assert tail == {"b7c9d2e4f6a1"}, (
        f"expected one linear head b7c9d2e4f6a1, found {sorted(tail)} — "
        "two heads break `alembic upgrade head` for every environment"
    )


def test_no_new_migration_leaves_an_unnamed_constraint_behind() -> None:
    """The O3 failure mode, prevented rather than mopped up.

    `op.drop_constraint(None, table, type_="foreignkey")` cannot be rendered:
    the name is None, so the downgrade aborts. Every constraint op this branch
    adds must pass an explicit name, so a fresh failure is impossible even
    though the 22 historical ones are only now being repaired.
    """
    constraint_ops = {
        "create_foreign_key",
        "create_unique_constraint",
        "create_check_constraint",
        "create_primary_key",
        "drop_constraint",
        "drop_foreign_key",
        "drop_unique_constraint",
    }
    problems: list[str] = []
    for path in (TENANCY_MIGRATION, FTS_MIGRATION, NAMING_MIGRATION):
        module, rec = _load(path)
        for phase in ("upgrade", "downgrade"):
            rec.calls.clear()
            getattr(module, phase)()
            for op_name, args, kwargs in rec.calls:
                if op_name not in constraint_ops:
                    continue
                name = kwargs.get("name", args[0] if args else None)
                if name is None:
                    problems.append(f"{path.name} {phase}(): {op_name} with name=None")
    assert not problems, "unnamed constraint op:\n" + "\n".join(problems)


# ------------------------------------------------------- (a) workflow_versions
def test_workflow_version_model_declares_a_cascading_tenant_id() -> None:
    """The column must exist on the ORM side or no INSERT can ever set it."""
    from app.modules.automation.models import WorkflowVersion

    column = WorkflowVersion.__table__.c.get("tenant_id")
    assert column is not None, "workflow_versions model has no tenant_id"
    assert column.nullable is False, "tenancy cannot be optional"
    assert column.foreign_keys, "tenant_id must reference tenants"
    fk = next(iter(column.foreign_keys))
    assert fk.target_fullname == "tenants.id"
    assert fk.ondelete == "CASCADE", "the tenant that owns the workflow owns its snapshots"


def test_workflow_version_uniqueness_is_a_named_constraint() -> None:
    """(workflow_id, version) unique — as a CONSTRAINT, not a bare index.

    It already existed as a unique INDEX under the same name; the name is kept
    so nothing that targets the index breaks, but a constraint is visible to
    pg_constraint, can be a FK target, and is what `downgrade()` can drop by a
    name that actually resolves.
    """
    from app.modules.automation.models import WorkflowVersion

    constraints = [
        c
        for c in WorkflowVersion.__table__.constraints
        if isinstance(c, UniqueConstraint)
        and [col.name for col in c.columns] == ["workflow_id", "version"]
    ]
    assert constraints, "no UniqueConstraint on (workflow_id, version)"
    assert constraints[0].name == "uq_workflow_versions_workflow_version"


def test_tenancy_migration_backfills_from_the_parent_workflow() -> None:
    """The value must come from `workflows`, and must be proven non-NULL.

    A NULL-bearing `tenant_id` under FORCE RLS is invisible to its own owner,
    so `SET NOT NULL` is not decoration — it is the assertion that the backfill
    reached every row.
    """
    module, rec = _upgrade(TENANCY_MIGRATION)
    sql = "\n".join(rec.executed)

    added = _find_call(rec.calls, "add_column", "workflow_versions")
    assert added, "tenant_id is never added to workflow_versions"
    col = added[0][1]
    assert col.name == "tenant_id"
    assert col.nullable is True, (
        "add the column NULLable, backfill, then SET NOT NULL — adding a NOT "
        "NULL column to a populated table fails before the backfill can run"
    )

    assert re.search(r"UPDATE\s+public\.workflow_versions", sql, re.I), "no backfill UPDATE"
    assert "FROM public.workflows" in sql, "backfill must read the parent workflow"
    assert "wv.tenant_id IS NULL" in sql, "backfill must be re-runnable"

    set_not_null = _find_call(rec.calls, "alter_column", "workflow_versions")
    assert set_not_null and set_not_null[1].get("nullable") is False, (
        "tenant_id is never made NOT NULL"
    )


def test_orphans_abort_the_migration_instead_of_being_skipped() -> None:
    """The explicit mission requirement: fail loudly, never silently skip.

    `workflow_id` carries an ON DELETE CASCADE FK, so a version row with no
    parent is already a contradiction — it can only mean a row written outside
    the constraint (a bad restore). Any tenant guessed for it is a coin flip,
    and a wrong coin flip is a cross-tenant read. So: count the survivors of
    the backfill and RAISE, which aborts the whole transaction and leaves the
    schema exactly as it was.
    """
    module, rec = _upgrade(TENANCY_MIGRATION)
    sql = "\n".join(rec.executed)
    assert "RAISE EXCEPTION" in sql, (
        "backfill silently skips rows whose workflow is gone — an orphan must "
        "abort the migration, not become a row no tenant can see"
    )
    assert re.search(r"tenant_id IS NULL", sql) and "orphan" in sql.lower()
    assert "_validate" not in sql, "placeholder left in the SQL"


def test_tenancy_migration_adds_the_standard_policy_and_force_rls() -> None:
    """Without this the new column is decoration.

    The b2c3d4e5f6a7 sweep selects `column_name = 'tenant_id'`, so it ran past
    this table; re-running provision.py later would catch it, but a migrated
    but unprovisioned database must already be isolated.
    """
    module, rec = _upgrade(TENANCY_MIGRATION)
    sql = "\n".join(rec.executed)
    assert "ALTER TABLE public.workflow_versions ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE public.workflow_versions FORCE ROW LEVEL SECURITY" in sql, (
        "ENABLE without FORCE leaves the table owner — the migration role — "
        "able to read every tenant's snapshots"
    )
    assert "CREATE POLICY tenant_isolation ON public.workflow_versions" in sql
    assert _TENANT_GUARD in sql, (
        "the canonical NULLIF guard: an unset app.tenant_id must match zero "
        "rows rather than raise a cast error"
    )
    assert "WITH CHECK (tenant_id = " in sql, "USING alone still allows forged writes"


def test_tenancy_migration_names_everything_it_creates() -> None:
    module, rec = _upgrade(TENANCY_MIGRATION)
    fk = _find_call(rec.calls, "create_foreign_key", "workflow_versions")
    assert fk, "no FK from workflow_versions.tenant_id to tenants"
    args, kwargs = fk
    assert args[0] == "fk_workflow_versions_tenant_id_tenants"
    assert kwargs.get("ondelete") == "CASCADE"

    unique = _find_call(rec.calls, "create_unique_constraint", "workflow_versions")
    assert unique and unique[0][0] == "uq_workflow_versions_workflow_version"
    assert list(unique[0][2]) == ["workflow_id", "version"]

    index = _find_call(rec.calls, "create_index", "workflow_versions")
    assert index, "tenant_id needs its own index — RLS filters on it every read"


def test_everything_the_tenancy_downgrade_drops_the_upgrade_created() -> None:
    """Replayable AND downgradeable, which is the whole point of naming.

    A `drop_constraint` for a name `upgrade()` never created aborts the
    rollback at 03:00, when it is the only thing anyone wanted to work.
    """
    module, rec = _load(TENANCY_MIGRATION)

    created_constraints, created_indexes = set(), set()
    rec.calls.clear()
    module.upgrade()
    for op_name, args, _kwargs in rec.calls:
        if op_name in {"create_foreign_key", "create_unique_constraint", "create_index"}:
            if args and isinstance(args[0], str):
                (created_indexes if op_name == "create_index" else created_constraints).add(
                    args[0]
                )
        if op_name == "add_column":
            assert args[0] in SLICE_TABLES

    rec.calls.clear()
    module.downgrade()
    problems: list[str] = []
    for op_name, args, kwargs in rec.calls:
        if op_name in {"drop_constraint", "drop_foreign_key", "drop_unique_constraint"}:
            name = kwargs.get("name", args[0] if args else None)
            if name is None:
                problems.append(f"drop_constraint(name=None) — {op_name} cannot render")
            elif name not in created_constraints:
                problems.append(f"downgrade drops {name!r} which upgrade never created")
        elif op_name == "drop_index":
            name = args[0] if args else kwargs.get("index_name")
            if name not in created_indexes:
                problems.append(f"downgrade drops index {name!r} never created by upgrade")
    assert not problems, "; ".join(problems)


def test_tenancy_downgrade_removes_the_policy_and_keeps_rls_enabled() -> None:
    """Rolling back must not leave a policy pointing at a dropped column, and
    must not quietly `DISABLE ROW LEVEL SECURITY` — turning isolation off is
    never a rollback anyone should want (same reasoning as b2c3d4e5f6a7)."""
    module, rec = _load(TENANCY_MIGRATION)
    rec.executed.clear()
    module.downgrade()
    sql = "\n".join(rec.executed)
    assert "DROP POLICY IF EXISTS tenant_isolation ON public.workflow_versions" in sql
    assert "NO FORCE ROW LEVEL SECURITY" in sql
    assert "DISABLE ROW LEVEL SECURITY" not in sql

    dropped_columns = [
        c
        for c in rec.calls
        if c[0] == "drop_column"
        and c[1] == ("workflow_versions", "tenant_id")
    ]
    assert dropped_columns, "downgrade must drop the tenant_id column it added"


# ------------------------------------------------------------- (b) full text
def _computed_expression_for(table_name: str, model) -> str | None:
    """The GENERATED ALWAYS expression the ORM would emit for `search_ts`."""
    column = model.__table__.c.get("search_ts")
    if column is None:
        return None
    computed = column.computed
    return computed.sqltext.text if computed is not None else None


@pytest.mark.parametrize("table_name", _SEARCH_TABLES)
def test_search_column_is_a_stored_tsvector_generated_column(table_name: str) -> None:
    """Not a trigger, not a hand-maintained column: the database derives it.

    A trigger can be missed by a bulk UPDATE and drifts silently; a generated
    column cannot disagree with its own row.
    """
    module, rec = _upgrade(FTS_MIGRATION)
    added = _find_call(rec.calls, "add_column", table_name)
    assert added, f"{table_name} gains no search column"
    column = added[0][1]
    assert column.name == "search_ts"
    assert isinstance(column.type, TSVECTOR)
    assert column.computed is not None, "search_ts must be GENERATED, not plain"
    assert column.computed.persisted, "must be STORED — a VIRTUAL tsvector cannot be indexed"


@pytest.mark.parametrize("table_name", _SEARCH_TABLES)
def test_gin_index_sits_on_every_search_column(table_name: str) -> None:
    """A tsvector nobody can reach is a write penalty and nothing else."""
    _, rec = _upgrade(FTS_MIGRATION)
    hits = [
        c
        for c in rec.calls
        if c[0] == "create_index"
        and c[1][0] == f"ix_{table_name}_search_ts"
        and c[1][2] == [
            "search_ts"
        ]
        and c[2].get("postgresql_using") == "gin"
    ]
    assert hits, f"no GIN index on {table_name}.search_ts"


@pytest.mark.parametrize(
    ("table_name", "import_path", "attr", "columns"),
    [
        ("customers", "app.modules.customers.models", "Customer", ["name", "email", "phone"]),
        ("products", "app.modules.catalog.models", "Product", ["title", "description"]),
        (
            "knowledge_items",
            "app.modules.ai.models",
            "KnowledgeItem",
            ["title", "content"],
        ),
    ],
)
def test_search_document_covers_the_columns_the_searchers_ask_for(
    table_name: str, import_path: str, attr: str, columns: list[str]
) -> None:
    """The vector must index what the ILIKE path searched, or the rewrite loses rows."""
    import importlib

    model = getattr(importlib.import_module(import_path), attr)
    expr = _computed_expression_for(table_name, model)
    assert expr is not None, f"{model.__name__} declares no computed search_ts"
    assert expr == _migration_expression(table_name), (
        f"{table_name}: the ORM's GENERATED expression and the migration's differ — "
        "the drift test cannot see computed expressions, so this is the guard"
    )
    for column in columns:
        assert re.search(rf"coalesce\({column},\s*''\)", expr), (
            f"{table_name}.search_ts must include {column}"
        )


def _migration_expression(table_name: str) -> str:
    module, _ = _load(FTS_MIGRATION)
    return module._SEARCH_TS[table_name]


def test_fts_config_is_pinned_to_simple_because_generated_needs_immutable() -> None:
    """The reason for `simple`, in one assertion.

    `to_tsvector('english', …)` would stem Latin (`running` -> `run`) and does
    nothing useful for Arabic; `to_tsvector('arabic', …)` stems Arabic and
    mangles Latin. A per-row locale does not exist here. But the binding
    argument is narrower than taste: `to_tsvector(text)` — the one-argument
    form that takes the config from `default_text_search_config` — is STABLE,
    and a GENERATED column requires IMMUTABLE, so the config must be spelled
    out at all. `simple` is the only spelled-out config that is honest about
    mixed Arabic+Latin content: it tokenises and lowercases both, stems neither.
    """
    module, _ = _load(FTS_MIGRATION)
    for table_name, expr in module._SEARCH_TS.items():
        for call in re.findall(r"to_tsvector\((.*?)\)", expr):
            assert call.startswith("'simple'"), (
                f"{table_name}: to_tsvector({call}) — the config must be the "
                "literal 'simple' for immutability and language neutrality"
            )
        assert "to_tsvector(" in expr


def test_no_unpinned_to_tsvector_anywhere_in_the_new_migrations() -> None:
    """The 1-argument form must not appear in ANYTHING THAT RUNS.

    One `to_tsvector('x')` slipped into an index expression is enough to make
    the whole migration fail with "functions in index expression must be marked
    IMMUTABLE" — on the deploy, not in review.

    Scoped to executable SQL (what reaches op.execute, plus the computed
    expressions the ORM would emit), deliberately not to the file text: the
    docstrings here argue against the wrong configurations by naming them, and a
    comment cannot make a column mutable.
    """
    offenders: list[str] = []
    for path in (FTS_MIGRATION, TENANCY_MIGRATION, NAMING_MIGRATION):
        module, rec = _load(path)
        executable = list(rec.executed)
        for phase in ("upgrade", "downgrade"):
            rec.executed.clear()
            getattr(module, phase)()
            executable.extend(rec.executed)
        for expr in getattr(module, "_SEARCH_TS", {}).values():
            executable.append(expr)
        for sql in executable:
            for match in re.finditer(r"to_tsvector\s*\(([^;]*?)\)\s*[,)]", sql):
                inner = match.group(1)
                if not inner.lstrip().startswith("'simple'"):
                    offenders.append(f"{path.name}: to_tsvector({inner[:40]})")
    assert not offenders, "unpinned to_tsvector config:\n" + "\n".join(offenders)


def test_weighting_gives_the_ranking_the_ilike_path_cannot() -> None:
    """§45 wanted relevance; ILIKE has none, so a title hit and an email hit
    were indistinguishable. setweight is what makes `ts_rank` mean something."""
    module, _ = _load(FTS_MIGRATION)
    assert "setweight(" in module._SEARCH_TS["customers"]
    assert "'A'" in module._SEARCH_TS["customers"] and "'C'" in module._SEARCH_TS["customers"]
    assert "||" in module._SEARCH_TS["customers"], "weighted vectors must be merged"


@pytest.mark.parametrize("table_name", _SEARCH_TABLES)
def test_the_like_fallback_is_still_intact(table_name: str) -> None:
    """§45 adds FTS, it does not remove containment.

    `tsvector` cannot answer `phone ILIKE '%5521%'` — a partial contact is not a
    token — so the LIKE path stays load-bearing. Guarded here by asserting the
    FTS migration never touches the indexes or columns it runs through, and by
    the existing escape gate importing cleanly.
    """
    _, rec = _upgrade(FTS_MIGRATION)
    assert not _find_call(rec.calls, "drop_column", table_name)
    assert not _find_call(rec.calls, "drop_index", table_name)

    module, _ = _load(FTS_MIGRATION)
    rec2 = _Recorder()
    module.op = rec2
    module.downgrade()
    dropped = [c for c in rec2.calls if c[0] == "drop_index"]
    assert [d[1][0] for d in dropped if d[1][0] == f"ix_{table_name}_search_ts"], (
        f"{table_name}: downgrade must remove the GIN index it added"
    )


def test_fts_ops_address_tables_by_literal_not_by_loop_variable() -> None:
    """The repo's own drift guard reads THIS FILE with `ast`, not by running it.

    `test_migrations._declared_columns` records a column only when
    `op.add_column`'s first argument is a string CONSTANT. Written as a loop
    over `_SEARCH_TS` the guard sees a Name, finds nothing to check, and passes
    — so `search_ts` would sit on three models with no migration anyone could
    see creating it, and the first INSERT would fail on a live database. This
    burned the notifications and ai_budget_reservations models already. Writing
    the tables out is not verbosity here, it is what keeps the guard armed, so
    the shape itself is now pinned.
    """
    tree = ast.parse(FTS_MIGRATION.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attr = getattr(node.func, "attr", None)
        if attr not in {"add_column", "drop_column", "create_index", "drop_index"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            offenders.append(f"{attr}() first arg is not a literal: {ast.dump(node)[:60]}")
    assert not offenders, (
        "FTS migration addresses a table through a variable, which makes "
        "test_every_model_column_is_created_by_a_migration blind to it:\n"
        + "\n".join(offenders)
    )


def test_migration_sql_parses_as_postgres() -> None:
    """Local proof, not CI-only: every statement these revisions emit is
    accepted by the real Postgres grammar (pglast is libpg_query).

    This is what substitutes for a database on a laptop — it catches the exact
    class of bug that aborted `alembic upgrade head` before (a stray quote
    inside a single-quoted literal), because a parse error is a parse error
    whether or not anything is connected. It does NOT catch a wrong column
    name, a missing table, or a policy that does not isolate.
    """
    pglast = pytest.importorskip("pglast", reason="pglast is a dev-only parser")

    for path in (TENANCY_MIGRATION, FTS_MIGRATION, NAMING_MIGRATION):
        module, rec = _load(path)
        for phase in ("upgrade", "downgrade"):
            rec.executed.clear()
            getattr(module, phase)()
            for sql in rec.executed:
                pglast.parser.parse_sql(sql)


def test_no_new_migration_issues_multiple_statements_per_execute() -> None:
    """asyncpg's extended protocol rejects N>1 commands per execute, and that
    aborts the deploy. Re-uses the repo's own statement counter."""
    for path in (TENANCY_MIGRATION, FTS_MIGRATION, NAMING_MIGRATION):
        module, rec = _load(path)
        for phase in ("upgrade", "downgrade"):
            rec.executed.clear()
            getattr(module, phase)()
            for sql in rec.executed:
                assert _statement_count(sql) == 1, f"{path.name} {phase}: {sql[:70]}"


# ------------------------------------------------------- (c) segments is fixed
def test_segments_table_exists_and_is_registered_despite_the_empty_revision() -> None:
    """Register O2 says the table may not exist. It does.

    `24037e2ebc05_segments_table.py` really is an empty `pass` — but the table
    is created by `b2c3d4e5f6a7`, whose `_segments_table()` runs first in its
    own `upgrade()`, and `app/core/model_registry.py` imports the model (which
    lives in `segments/service.py`, not a models.py). So the line is stale.
    This guard keeps the next reviewer from re-filing it, and pins the one
    thing that WAS wrong: a revision named `segments_table` that creates no
    segments table.
    """
    from app.core.model_registry import Base
    from app.modules.segments.service import Segment

    assert "segments" in Base.metadata.tables
    assert Segment.__tablename__ == "segments"
    assert Segment.__table__.c.tenant_id is not None

    empty = VERSIONS_DIR / "24037e2ebc05_segments_table.py"
    tree = ast.parse(empty.read_text(encoding="utf-8"))
    upgrade = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"
    )
    meaningful = [
        n
        for n in upgrade.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
    ]
    assert all(isinstance(n, ast.Pass) for n in meaningful), (
        "24037e2ebc05 changed: this guard's premise (that it creates nothing) "
        "needs re-reading against the real DDL"
    )

    # the real DDL, in the real place
    hardening = VERSIONS_DIR / "b2c3d4e5f6a7_hardening_rls_segments_worker_columns.py"
    source = hardening.read_text(encoding="utf-8")
    assert 'op.create_table(\n        "segments"' in source
    assert "fk_segments_tenant_id_tenants" in source


# What the DDL says is unnamed on the slice, enumerated from every migration
# that created one (stage1 `0b79f7470c1a`, the W2-a hierarchy pass
# `48528b41d6db`, `49303e2e2dd0`, the automation domain `6cd2037d7891`, the
# §151 Q4 scope columns `d4a7c1e9f0b5`, and `b2c3d4e5f6a7` for segments).
# kind is "p" (primary key) or "f" (foreign key); columns is the LOCAL list.
EXPECTED_SLICE_CONSTRAINTS: set[tuple] = {
    ("customers", "p", ("id",), None),
    ("customers", "f", ("tenant_id",), "tenants"),
    ("customers", "f", ("workspace_id",), "workspaces"),
    ("customers", "f", ("location_id",), "locations"),
    ("customers", "f", ("merged_into_customer_id",), "customers"),
    ("knowledge_items", "p", ("id",), None),
    ("knowledge_items", "f", ("tenant_id",), "tenants"),
    ("knowledge_items", "f", ("workspace_id",), "workspaces"),
    ("knowledge_items", "f", ("location_id",), "locations"),
    ("products", "p", ("id",), None),
    ("products", "f", ("tenant_id",), "tenants"),
    ("products", "f", ("brand_id",), "brands"),
    ("products", "f", ("category_id",), "categories"),
    ("products", "f", ("workspace_id",), "workspaces"),
    ("products", "f", ("location_id",), "locations"),
    ("segments", "p", ("id",), None),
    ("workflow_versions", "p", ("id",), None),
    ("workflow_versions", "f", ("workflow_id",), "workflows"),
    ("workflows", "p", ("id",), None),
    ("workflows", "f", ("tenant_id",), "tenants"),
    ("workflows", "f", ("workspace_id",), "workspaces"),
    ("workflows", "f", ("location_id",), "locations"),
}


def test_every_slice_constraint_is_named_by_the_naming_migration() -> None:
    """22 constraints, counted from the DDL that created them, not projected.

    These are the constraints on `SLICE_TABLES` that Alembic emitted with no
    name, so Postgres invented `<table>_<column>_fkey` / `<table>_pkey`. A
    rollback can only be written once there is a name to write it with, which
    is the whole of O3 — narrowed to the six tables this branch touches instead
    of pretending to repair ~145.
    """
    module, _ = _load(NAMING_MIGRATION)
    assert set(module._RENAME_SPECS) == EXPECTED_SLICE_CONSTRAINTS, (
        "the named slice disagrees with what the migrations actually created"
    )
    assert len(module._RENAME_SPECS) == 22, "O3 slice is 22 constraints, not a projection"
    assert {s[0] for s in module._RENAME_SPECS} == set(SLICE_TABLES), "slice not covered"


def test_default_and_target_names_are_derived_not_transcribed() -> None:
    """The names cannot disagree with the rule because they ARE the rule.

    `pg_get_constraintname` builds `<table>_<col>_fkey` / `<table>_pkey`; if the
    migration hand-wrote either side, a typo would rename a constraint that is
    not the one intended — or miss its own idempotency check and abort the
    upgrade on a column nobody meant to touch.
    """
    module, _ = _load(NAMING_MIGRATION)
    for table, kind, columns, referent in module._RENAME_SPECS:
        old, new = module.constraint_names(table, kind, columns, referent)
        if kind == "p":
            assert old == f"{table}_pkey"
            assert new == f"pk_{table}"
        else:
            assert old == f"{table}_{'_'.join(columns)}_fkey"
            assert new == f"fk_{table}_{'_'.join(columns)}_{referent}"


def test_generated_names_fit_the_63_byte_identifier_ceiling() -> None:
    """Postgres silently truncates beyond 63 bytes, and a truncated name is a
    name nothing can find on the way back down."""
    module, _ = _load(NAMING_MIGRATION)
    for table, kind, columns, referent in module._RENAME_SPECS:
        for name in module.constraint_names(table, kind, columns, referent):
            assert len(name.encode()) <= 63, f"{name} exceeds 63 bytes"


def test_rename_helper_is_idempotent_and_loud() -> None:
    """Replay-safe in both directions, and it refuses to rename air.

    Upgrade skips when the target name already exists (so a re-run after a
    partial failure is harmless); it raises when NEITHER name exists, because
    that means the assumption about the live schema is wrong and inventing a
    constraint silently would make the next rollback worse, not better.
    """
    module, rec = _load(NAMING_MIGRATION)
    rec.executed.clear()
    module.upgrade()
    sql = "\n".join(rec.executed)
    assert "RENAME CONSTRAINT" in sql
    assert "RAISE EXCEPTION" in sql, "a missing constraint must abort, not be skipped"
    assert "CONTINUE" in sql, "already-renamed must be a no-op so the revision replays"
    assert "pg_constraint" in sql, "existence must be checked in the catalogue"


def test_naming_downgrade_reverses_to_the_postgres_default_names() -> None:
    """Every name upgrade() invents, downgrade() must give back — checked
    structurally per constraint, so a pair added to the spec without its
    reverse cannot slip through."""
    module, rec = _load(NAMING_MIGRATION)

    rec.executed.clear()
    module.upgrade()
    up_sql = "\n".join(rec.executed)

    rec.executed.clear()
    module.downgrade()
    down_sql = "\n".join(rec.executed)

    assert up_sql != down_sql, "downgrade emits the same SQL as upgrade"
    assert "DISABLE ROW LEVEL SECURITY" not in down_sql
    for table, kind, columns, referent in module._RENAME_SPECS:
        old, new = module.constraint_names(table, kind, columns, referent)
        assert new in up_sql, f"{table}: upgrade never applies {new}"
        assert old in up_sql, f"{table}: upgrade never references the default {old}"
        assert new in down_sql, f"{table}: downgrade does not reverse {new}"
        assert old in down_sql, f"{table}: downgrade does not restore {old}"


def test_alembic_still_reports_a_single_head() -> None:
    """Belt and braces alongside the chain-shape test: ask Alembic itself."""
    import subprocess
    import sys

    root = VERSIONS_DIR.parent.parent
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line for line in out.stdout.splitlines() if line.strip()]
    assert out.returncode == 0, out.stderr
    assert len(lines) == 1, f"multiple heads would break the build: {lines}"
    assert lines[0].startswith("b7c9d2e4f6a1"), lines


# ------------------------------------------- DB-backed: CI-only, not watched
async def test_workflow_versions_isolates_across_tenants(db) -> None:
    """CI-only: needs `DATABASE_URL_APP_ADMIN`, skips locally.

    The static guards above prove the DDL is written. This proves the database
    refuses: a snapshot owned by tenant A must be invisible under tenant B's GUC
    even though the SELECT carries no tenant filter at all — which is exactly
    the shape of the router's query that motivated this whole change.

    The stranger writes its OWN rows, under its OWN bound GUC (the hierarchy
    pattern): CI's `sales_app` role refuses any INSERT whose `app.tenant_id`
    is unset, so the row-owning tenant must bind first — then a different
    tenant binds and must not see what it wrote.

    Both of those tenants are REAL rows. A bare uuid satisfies
    `tenant_isolation`'s WITH CHECK and then dies one step later on the
    `workflows.tenant_id` foreign key — `Key is not present in table
    "tenants"` (run on c85e130) — and a reader that owns no tenant row would
    answer the final SELECT with nothing for the wrong reason.
    """
    from sqlalchemy import text

    from app.core.db import bind_tenant
    from app.modules.automation.models import Workflow, WorkflowVersion
    from app.modules.identity.models import Tenant

    stranger = Tenant(slug=f"wf-{uuid.uuid4().hex[:8]}", name="Workflow Stranger")
    reader = Tenant(slug=f"wf-read-{uuid.uuid4().hex[:8]}", name="Workflow Reader")
    db.add_all([stranger, reader])
    await db.flush()

    await bind_tenant(db, stranger.id)
    workflow = Workflow(
        tenant_id=stranger.id, name="isolated", trigger_event="order.created", current_version=1
    )
    db.add(workflow)
    await db.flush()
    db.add(
        WorkflowVersion(workflow_id=workflow.id, version=1, definition={}, tenant_id=stranger.id)
    )
    await db.flush()

    # Non-vacuity control, in the same shape `test_hierarchy_rls.py` uses: the
    # owner, bound to its own tenant, DOES see the snapshot through an
    # unfiltered SELECT. Without this the assertion below can be green simply
    # because nothing was ever written.
    owned = (
        await db.execute(
            text("SELECT id FROM workflow_versions WHERE workflow_id = :w"),
            {"w": workflow.id},
        )
    ).all()
    assert len(owned) == 1, "the seed wrote no snapshot, so isolation proves nothing"

    await bind_tenant(db, reader.id)  # a different, equally real tenant reads
    rows = (
        await db.execute(
            text(
                "SELECT id FROM workflow_versions WHERE workflow_id = :w"
            ),  # no TENANT predicate, on purpose — the workflow id is the row's
            # own identity, not a tenancy filter, and it still has to bind.
            {"w": workflow.id},
        )
    ).all()
    assert rows == [], "RLS must hide the snapshots; the app filter is not the boundary"


async def test_every_tenant_scoped_model_table_has_a_policy(db) -> None:
    """CI-only: needs `DATABASE_URL_APP_ADMIN`, skips locally.

    The sweep's own blind spot, made structural. `workflow_versions` was missed
    because a dynamic "tables that have a tenant_id column" sweep can only ever
    cover what exists at the moment it runs — every table created afterwards
    relies on someone remembering. This closes the loop from the ORM side:
    whatever the models declare today must already carry a policy.
    """
    from sqlalchemy import text

    from app.core.model_registry import Base
    from app.modules import __path__ as modules_path

    # metadata fills lazily; walk the package so nothing hides by not imported
    for module in pkgutil.walk_packages(modules_path, "app.modules."):
        importlib.import_module(module.name)

    # Tables the migrations deliberately exclude from tenant_isolation:
    # no-tenant plumbing, user-keyed, or NULL-tenant variants (see b2c3d4e5f6a7).
    exempt = {
        "outbox_events",
        "idempotency_keys",
        "plans",
        "refresh_tokens",
        "webhook_events",
        "scheduled_jobs",
        "tenant_users",
    }
    tenant_tables = {
        name
        for name, table in Base.metadata.tables.items()
        if "tenant_id" in table.c and name not in exempt
    }
    assert "workflow_versions" in tenant_tables, "model lost its tenant_id?"

    rows = (
        await db.execute(
            text(
                "SELECT tablename FROM pg_policies "
                "WHERE schemaname = 'public' AND policyname = 'tenant_isolation'"
            )
        )
    ).all()
    covered = {r[0] for r in rows}
    missing = sorted(tenant_tables - covered)
    assert not missing, (
        "tenant-scoped tables with no tenant_isolation policy — the database "
        "is not enforcing anything for these: " + ", ".join(missing)
    )

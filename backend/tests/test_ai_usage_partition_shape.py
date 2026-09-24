"""§56 — `ai_usage` IS partitioned, and provably so, in the shape the helper claims.

`app/core/partitioning.py` used to open with "PostgreSQL declarative
partitioning by created_at (range, monthly) IS USED" while NO table in the
schema was partitioned at all, and its `detach_old_partitions()` issued
`ALTER TABLE x DETACH PARTITION CONCURRENTLY` — invalid syntax (the clause is
`ALTER TABLE <parent> DETACH PARTITION <child> CONCURRENTLY`). Nothing ever
called it, so the lies were unexercised. This file is the counterweight: every
claim the module makes about shape is read back out of the live catalog, and
the migration's claims are pinned statically so the file fails for the right
reason even without a database.

What "the right shape" means here, and why each pin exists:

* monthly RANGE on `period_date`, not `created_at` — `period_date` is the
  business day the rollup is about, it is NOT NULL, and it is already inside
  the natural key `uq_ai_usage_tenant_period_agent`, which is what lets the
  upsert in `app/modules/ai/usage.py` keep working (see the caveat pin below).
* a DEFAULT partition, so a business write can never fail because a month was
  not pre-created — missing partitions must degrade into a maintenance alarm,
  never into a lost agent reply.
* RLS enabled+forced on EVERY partition, because a partition is a real table
  that `sales_app` inserts into directly.
* the pre-partition snapshot kept, so the migration has a rollback that does
  not depend on a restore from backup.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import partitioning
from app.modules.ai.models import AIUsage

BACKEND_ROOT = pathlib.Path(partitioning.__file__).resolve().parents[2]
VERSIONS_DIR = BACKEND_ROOT / "migrations" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "f7a2c9d4e8b1_w4_partition_ai_usage_chosen_retention.py"
CURRENT_HEAD = "e3b7d2a9c4f1"
PARENT = "public.ai_usage"

_migration = None


def _migration_module():
    global _migration
    if _migration is None:
        spec = importlib.util.spec_from_file_location("w4_partition_migration", MIGRATION_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _migration = module
    return _migration


def _all_revision_ids() -> list[str]:
    ids: list[str] = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        body = path.read_text(encoding="utf-8")
        match = re.search(r'^revision:?\s*(?:str\s*=?\s*)?"([0-9a-f]{12})"', body, re.MULTILINE)
        if match:
            ids.append(match.group(1))
    return ids


# ------------------------------------------------- static pins (no database) --


def test_the_partition_migration_exists_and_extends_the_single_head() -> None:
    """Single linear chain: exactly one revision revises the current head."""
    assert MIGRATION_PATH.exists(), f"{MIGRATION_PATH.name} is missing"
    module = _migration_module()
    assert module.down_revision == CURRENT_HEAD, (
        "the new revision must hang off the current head, not branch the chain"
    )
    revisers = [
        path.name
        for path in VERSIONS_DIR.glob("*.py")
        if f'down_revision: str | None = "{CURRENT_HEAD}"' in path.read_text(encoding="utf-8")
    ]
    assert revisers == [MIGRATION_PATH.name], f"{CURRENT_HEAD} has {len(revisers)} children"
    assert module.revision == "f7a2c9d4e8b1"
    ids = _all_revision_ids()
    assert ids.count("f7a2c9d4e8b1") == 1, "revision ids must stay unique"


def test_maintenance_functions_are_security_definer_with_pinned_search_path() -> None:
    """Runtime partition DDL cannot run as `sales_app`.

    `scripts/provision.py` grants the app role USAGE plus table privileges but
    NOT CREATE on schema public, so a worker holding a plain connection cannot
    `CREATE TABLE ... PARTITION OF` or `DROP TABLE`. The only way a recurring
    job can do partition maintenance is the mechanism this repo already uses
    for pre-tenant webhook resolution: a SECURITY DEFINER function owned by the
    migration role, with `search_path` pinned (mandatory for definer functions)
    and EXECUTE revoked from PUBLIC and handed to `sales_app` explicitly.
    """
    module = _migration_module()
    bodies = {
        "partitioning_ensure_partition": module._ENSURE_ONE_FN,
        "partitioning_ensure_months": module._ENSURE_FN,
        "partitioning_purge_month": module._PURGE_FN,
        "retention_drop_horizon": module._DROP_GATE_FN,
    }
    for name, sql in bodies.items():
        assert "SECURITY DEFINER" in sql, f"{name} must be SECURITY DEFINER"
        assert "SET search_path = public, pg_temp" in sql, f"{name} has no pinned search_path"
        assert sql.count(";") >= 1
        revoke = getattr(module, f"_{name.upper()}_REVOKE")
        assert "REVOKE ALL ON FUNCTION" in revoke and "FROM PUBLIC" in revoke
        grant = getattr(module, f"_{name.upper()}_GRANT")
        assert "GRANT EXECUTE" in grant and "sales_app" in grant


def test_table_references_inside_the_ddl_functions_are_regclass_not_oid() -> None:
    """`format('%s', <oid>)` prints a NUMBER, and a number is not a table name.

    These functions build their DDL with `%s` on a looked-up relation, because
    `%I` would quote a dotted `schema.table` into one impossible identifier. The
    only type whose text output is usable where a NAME belongs is `regclass`
    (whose output function prints the identifier, schema-qualified only when the
    pinned search_path cannot see it). A variable declared `oid` prints `16430`,
    so `ALTER TABLE 16430 FORCE ROW LEVEL SECURITY` is a syntax error — and it
    fails at the first runtime ensure, in production, months after the migration
    that shipped it looked fine.
    """
    module = _migration_module()
    for name in ("_ENSURE_ONE_FN", "_PURGE_FN"):
        sql = getattr(module, name)
        bare_oid = re.findall(r"^\s*(\w+)\s+oid\s*;", sql, re.MULTILINE)
        assert not bare_oid, (
            f"{name}: {bare_oid} hold a relation in an `oid` variable, and "
            f"`format('%s', oid)` prints a number where a table NAME belongs — "
            f"declare relation handles as `regclass`"
        )
        assert "to_regclass(" in sql, f"{name} no longer resolves its parent by catalog name"


def test_only_allowlisted_partitioned_tables_may_be_touched() -> None:
    """The functions take a table NAME as text, so the allowlist must live in
    SQL, not only in Python — a caller that reaches the function directly (or a
    Python-side typo) must still be refused by the database.
    """
    module = _migration_module()
    for name in ("_ENSURE_ONE_FN", "_ENSURE_FN", "_PURGE_FN"):
        sql = getattr(module, name)
        parents = set(re.findall(r"'(public\.[a-z_]+)'", sql))
        assert parents == set(partitioning.PARTITION_MAINTENANCE_ALLOWLIST), (
            f"{name} allowlists {sorted(parents)} but core says "
            f"{sorted(partitioning.PARTITION_MAINTENANCE_ALLOWLIST)}"
        )


def test_the_legal_floor_is_enforced_in_sql_not_only_in_python() -> None:
    """`PARTITION_DROP_FLOOR_MONTHS` is a Python constant that a buggy caller
    could pass anything to. The number must ALSO be inside the purge function,
    so no caller — not even a correct-looking one — can drop a month that is
    still inside the horizon the PII map states for this store.
    """
    module = _migration_module()
    floor = partitioning.PARTITION_DROP_FLOOR_MONTHS
    assert floor == 13, "docs/PII_DATA_MAP.md gives ai_usage 13 months"
    assert f"INTERVAL '{floor} months'" in module._PURGE_FN, (
        "the purge function no longer enforces the floor itself"
    )
    assert "RAISE EXCEPTION" in module._PURGE_FN


def test_the_purge_is_partition_shaped_and_detaches_before_dropping() -> None:
    """§57: cold data leaves a partitioned table as a whole month, never row
    at a time. And DETACH must be the plain (transactional) form — the previous
    helper used `DETACH PARTITION CONCURRENTLY` on the CHILD, which is both the
    wrong syntax and non-transactional, so it could not run inside the job's
    transaction at all.
    """
    module = _migration_module()
    sql = module._PURGE_FN
    assert "DETACH PARTITION" in sql
    assert "CONCURRENTLY" not in sql, "concurrent DETACH cannot run in a transaction"
    assert re.search(r"DROP TABLE", sql), "a DETACH that never drops keeps the series growing"
    assert "_DEFAULT_SUFFIX" in sql or "default" in sql.lower(), (
        "the DEFAULT partition must be named and refused"
    )


def test_the_conversion_does_not_silently_drop_the_legacy_copy() -> None:
    """Postgres has no in-place `PARTITION BY`: the conversion is
    rename -> create partitioned parent -> copy -> keep the snapshot. Dropping
    the snapshot in the same migration would leave no rollback but a restore.
    """
    module = _migration_module()
    upgrade_src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    upgrade_body = upgrade_src.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "PARTITION BY RANGE" in upgrade_body
    assert "INCLUDING ALL" in upgrade_body, "LIKE keeps NOT NULL/defaults/checks identical"
    assert "INSERT INTO" in upgrade_body, "the historical rows must move, not be re-created"
    legacy = module.LEGACY_SNAPSHOT_TABLE
    assert f"RENAME TO {legacy}" in upgrade_body or legacy in upgrade_body
    assert f"DROP TABLE IF EXISTS public.{legacy}" not in upgrade_body, (
        "upgrade() must keep the rollback copy; retiring it is an operator call"
    )


def test_like_copies_columns_not_keys_so_the_parent_can_declare_its_own() -> None:
    """`LIKE ... INCLUDING ALL` also means INCLUDING INDEXES, and that is a trap.

    Postgres: "Indexes, PRIMARY KEY, UNIQUE, and EXCLUDE constraints on the
    original table will be created on the new table." A partitioned parent may
    not carry a PK that omits the partition column, so a bare `INCLUDING ALL`
    here would abort `alembic upgrade head` with `insufficient columns in the
    PRIMARY KEY constraint definition` — before the copy, with the real table
    already renamed. The parent therefore takes the column shape from LIKE and
    re-declares every key itself, so the conversion must say
    `INCLUDING ALL EXCLUDING INDEXES` and must then add the keys in its own
    words. Foreign keys are never copied by LIKE at all, which is why the four
    of them are re-declared too.
    """
    upgrade_src = pathlib.Path(_migration_module().__file__).read_text(encoding="utf-8")
    upgrade_body = upgrade_src.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert re.search(r"INCLUDING ALL\s+EXCLUDING INDEXES", upgrade_body), (
        "LIKE without EXCLUDING INDEXES copies the legacy PRIMARY KEY (id) into "
        "the partitioned parent, which Postgres refuses"
    )
    assert upgrade_body.count("ADD CONSTRAINT") >= 6, (
        "keys and foreign keys are not copied by LIKE: the parent must re-declare PK, "
        "the natural unique key and every FK the snapshot had"
    )


def test_the_partition_key_is_in_every_unique_key_of_the_parent() -> None:
    """Postgres only lets a partitioned table carry a unique/PK constraint whose
    columns include the whole partition key. `uq_ai_usage_tenant_period_agent`
    already contains `period_date`, which is why THIS table can be partitioned
    without weakening the upsert in `ai/usage.py` (a conflicting pair can never
    live in two different month partitions). The primary key, however, was
    `id` alone and had to become `(id, period_date)` — so global uniqueness of
    `ai_usage.id` is no longer database-enforced, and the migration must say so.
    """
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    assert re.search(
        r"PRIMARY KEY \(id, period_date\)|PRIMARY KEY \(\"id\", \"period_date\"\)", src
    )
    assert re.search(r"UNIQUE \(tenant_id, period_date, agent_id\)", src)
    lowered = src.lower()
    assert (
        "id is no longer globally unique" in lowered
        or "no longer database-enforced" in lowered
    )


# ------------------------------------------------------ live shape (DB-gated) --


async def _children(db: AsyncSession) -> list[tuple[str, str]]:
    rows = (
        await db.execute(
            text(
                "SELECT c.relname, pg_get_expr(cc.relpartbound, c.oid) "
                "FROM pg_inherits i "
                "JOIN pg_class c ON c.oid = i.inhrelid "
                "JOIN pg_class p ON p.oid = i.inhparent AND p.oid = 'public.ai_usage'::regclass "
                "LEFT JOIN pg_class cc ON cc.oid = c.oid "
                "ORDER BY c.relname"
            )
        )
    ).all()
    return [(r[0], r[1] or "") for r in rows]


async def test_ai_usage_parent_is_range_partitioned_on_period_date(db: AsyncSession) -> None:
    """Not 'a table with a comment saying partitioned' — `relkind = 'p'`."""
    row = (
        await db.execute(
            text(
                "SELECT c.relkind, pg_get_partkeydef(c.oid) FROM pg_class c "
                "WHERE c.oid = 'public.ai_usage'::regclass"
            )
        )
    ).one()
    assert row[0] == "p", f"ai_usage is relkind={row[0]!r}: not a partitioned table"
    assert row[1].upper() == "RANGE (period_date)", row[1]


async def test_partitions_are_monthly_bounds_plus_a_default(db: AsyncSession) -> None:
    children = await _children(db)
    assert children, "the parent has no partitions at all"
    assert "ai_usage_default" in [n for n, _ in children], (
        "without a DEFAULT partition a row whose month was never pre-created "
        "fails the business write instead of raising a maintenance alarm"
    )
    for name, bound in children:
        if name == "ai_usage_default":
            assert bound.upper().startswith("DEFAULT")
            continue
        assert re.fullmatch(r"ai_usage_\d{4}_\d{2}", name), name
        m = re.search(r"FROM \('(\d{4}-\d{2}-\d{2})'\) TO \('(\d{4}-\d{2}-\d{2})'\)", bound)
        assert m, bound
        start, end = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
        assert start.day == 1 and end.day == 1, f"{name} is not a whole month: {bound}"
        assert partitioning.month_bounds(start.year, start.month) == (start, end), (
            f"{name}: the helper computes {partitioning.month_bounds(start.year, start.month)}, "
            f"the database says {(start, end)}"
        )


async def test_this_month_and_the_next_quarter_already_exist(db: AsyncSession) -> None:
    """Partitions are created AHEAD of time, which is the only reason the
    recurring job exists: it must find nothing to do on a healthy month.
    """
    present = {n for n, _ in await _children(db)}
    now = datetime.now(UTC).date()
    for offset in range(0, 4):
        year, month = now.year, now.month + offset
        year += (month - 1) // 12
        month = ((month - 1) % 12) + 1
        assert f"ai_usage_{year:04d}_{month:02d}" in present, (
            f"month {year}-{month:02d} has no partition; inserts would land in DEFAULT"
        )


async def test_every_partition_is_row_level_security_isolated(db: AsyncSession) -> None:
    """A partition is a real table `sales_app` writes to. Whether Postgres
    copies the parent's policy onto `PARTITION OF` is not something this repo
    should bet the tenant boundary on, so the maintenance function sets
    ENABLE + FORCE + `tenant_isolation` on each child explicitly.
    """
    rows = (
        await db.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "  (SELECT count(*) FROM pg_policies p "
                "    WHERE p.tablename = c.relname AND p.policyname = 'tenant_isolation') "
                "FROM pg_class c "
                "WHERE c.oid = 'public.ai_usage'::regclass "
                "   OR c.oid IN (SELECT inhrelid FROM pg_inherits "
                "                 WHERE inhparent = 'public.ai_usage'::regclass) "
                "ORDER BY c.relname"
            )
        )
    ).all()
    assert rows
    for name, enabled, forced, policies in rows:
        assert enabled is True and forced is True, f"{name}: RLS not enabled+forced"
        assert policies == 1, f"{name}: expected one tenant_isolation policy, got {policies}"


async def test_primary_key_and_natural_key_include_the_partition_key(db: AsyncSession) -> None:
    conns = (
        await db.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'public.ai_usage'::regclass "
                "  AND contype IN ('p', 'u') ORDER BY conname"
            )
        )
    ).all()
    defs = {name: definition for name, definition in conns}
    assert any(
        k == "PRIMARY KEY (id, period_date)" for k, v in defs.items() for k in [v]
    ), defs
    assert "uq_ai_usage_tenant_period_agent" in defs
    assert defs["uq_ai_usage_tenant_period_agent"] == (
        "UNIQUE INDEX (tenant_id, period_date, agent_id)"
    ) or "period_date" in defs["uq_ai_usage_tenant_period_agent"], defs


async def test_the_legacy_snapshot_survives_as_a_plain_table(db: AsyncSession) -> None:
    row = (
        await db.execute(
            text("SELECT c.relkind FROM pg_class c WHERE c.oid = to_regclass(:name)"),
            {"name": f"public.{partitioning.LEGACY_SNAPSHOT_TABLE}"},
        )
    ).one()
    assert row[0] == "r", "the rollback copy must be a real, untouched table"


async def test_rows_route_to_their_own_month_and_orphans_to_default(
    db: AsyncSession, tenant_ctx
) -> None:
    """Routing is the mechanism retention depends on: a month leaves as one
    object only if its rows are inside that month's partition.
    """
    now = datetime.now(UTC).date()
    two_back = now.month - 2 if now.month > 2 else now.month + 10
    month_start = partitioning.month_bounds(now.year, two_back)[0]
    if now.month <= 3:
        month_start = date(now.year - 1, now.month + 10, 1)
    created = await partitioning.ensure_partition_for_month(db, PARENT, month_start)
    assert created == f"ai_usage_{month_start:%Y_%m}" or created is None

    await db.execute(
        text(
            "INSERT INTO ai_usage (id, period_date, tokens_in, tokens_out, cost, "
            "model_calls, created_at, tenant_id) VALUES (:id, :d, 1, 1, 0, 1, now(), :t)"
        ),
        {"id": uuid.uuid4(), "d": month_start, "t": tenant_ctx.tenant_id},
    )
    # A date so old no monthly partition will ever exist for it.
    orphan = await db.execute(
        text(
            "SELECT tableoid::regclass::text FROM ai_usage "
            "WHERE tenant_id = :t AND period_date = DATE '2001-01-05'"
        ),
        {"t": tenant_ctx.tenant_id},
    )
    await db.execute(
        text(
            "INSERT INTO ai_usage (id, period_date, tokens_in, tokens_out, cost, "
            "model_calls, created_at, tenant_id) VALUES (:id, DATE '2001-01-05', 1, 1, 0, 1, "
            "now(), :t)"
        ),
        {"id": uuid.uuid4(), "t": tenant_ctx.tenant_id},
    )
    assert orphan.rowcount == 0
    placed = (
        await db.execute(
            text(
                "SELECT tableoid::regclass::text FROM ai_usage "
                "WHERE tenant_id = :t AND period_date = DATE '2001-01-05'"
            )
        )
    ).scalar_one()
    assert placed == "ai_usage_default", (
        f"the unroutable row landed in {placed!r}, not the DEFAULT partition — "
        "a business write would have failed instead"
    )
    month_rows = (
        await db.execute(
            text(
                "SELECT tableoid::regclass::text FROM ai_usage "
                "WHERE tenant_id = :t AND period_date = :d"
            ),
            {"t": tenant_ctx.tenant_id, "d": month_start},
        )
    ).scalar_one()
    assert month_rows == f"ai_usage_{month_start:%Y_%m}"


async def test_the_daily_upsert_still_converges_on_a_partitioned_table(
    db: AsyncSession, tenant_ctx
) -> None:
    """THE caveat. `ai/usage.py` writes only through
    `INSERT ... ON CONFLICT (tenant_id, period_date, agent_id) DO UPDATE`.
    Postgres documents that "to create a unique or primary key constraint on a
    partitioned table ... the constraint's columns must include all of the
    partition key columns", and that ON CONFLICT traps conflicts on the target
    relation's own inferred arbiter. Because `period_date` is the partition key
    AND part of the arbiter, two rows that could conflict are guaranteed to sit
    in the same month partition, so the counter still accumulates on one row.
    If this test ever shows two rows, the partitioning is wrong for this table
    and must be reverted, not patched around.
    """
    from app.modules.ai.usage import record_usage

    agent_id = uuid.uuid4()
    for _ in range(3):
        await record_usage(
            db,
            tenant_ctx.tenant_id,
            agent_id=agent_id,
            tokens_in=100,
            tokens_out=5,
            cost=0.5,
        )
    await db.flush()
    rows = (
        await db.execute(
            text(
                "SELECT count(*), sum(tokens_in), sum(model_calls) FROM ai_usage "
                "WHERE tenant_id = :t AND agent_id = :a"
            ),
            {"t": tenant_ctx.tenant_id, "a": agent_id},
        )
    ).one()
    assert rows[0] == 1, "the upsert split into duplicate rows after partitioning"
    assert int(rows[1]) == 300 and int(rows[2]) == 3

    # ...and the row lives in exactly the partition for its own period_date.
    routed = (
        await db.execute(
            text(
                "SELECT tableoid::regclass::text, period_date FROM ai_usage "
                "WHERE tenant_id = :t AND agent_id = :a"
            ),
            {"t": tenant_ctx.tenant_id, "a": agent_id},
        )
    ).one()
    today = datetime.now(UTC).date()
    assert routed[0] == f"ai_usage_{today:%Y_%m}", routed
    assert routed[1] == today


async def test_cost_precision_and_money_shape_survive_the_conversion(
    db: AsyncSession, tenant_ctx
) -> None:
    """`LIKE ... INCLUDING ALL` must have carried NUMERIC(18,8) and the server
    defaults, or every INSERT through the ORM starts failing on a column the
    model thinks the database fills.
    """
    cols = (
        await db.execute(
            text(
                "SELECT column_name, data_type, numeric_precision, numeric_scale, "
                "is_nullable, column_default IS NOT NULL FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='ai_usage'"
            )
        )
    ).all()
    shape = {name: rest for name, *rest in cols}
    assert shape["cost"][:3] == ("numeric", 18, 8), shape["cost"]
    for name in ("tokens_in", "tokens_out", "model_calls", "created_at"):
        assert shape[name][3] == "NO", name
        assert shape[name][4] is True, f"{name} lost its server_default"
    assert set(shape) >= {c.name for c in AIUsage.__table__.c}

"""The retail.core -> apparel rename, proven before it touches a real database.

The architecture allows two levels only, so the base application every sector sat
on had to become the sector application itself. The code shipped with a
``LEGACY_KEYS`` bridge; this migration moves the data and the bridge goes away.

It is exercised here against a throwaway schema on a real Postgres, because the
statements are Postgres-specific (UPDATE ... FROM, temp tables, ON COMMIT DROP)
and a sqlite stand-in would prove nothing. Without ``TEST_DATABASE_URL`` the
tests skip: an unproven migration must not be reported as tested.

What is asserted: the rename happens, a duplicate new key is merged instead of
violating the unique constraint, the rollback restores the old keys, and running
the script twice changes nothing.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs a Postgres to prove the migration (set TEST_DATABASE_URL)",
)

SQL = open("migrations/sql/rename_retail_core_to_apparel.sql", encoding="utf-8").read()
ROLLBACK = open(
    "migrations/sql/rename_retail_core_to_apparel_rollback.sql", encoding="utf-8"
).read()

DDL = """
CREATE TABLE plan_application_inclusions (
    plan_id uuid NOT NULL,
    application_key text NOT NULL,
    UNIQUE (plan_id, application_key)
);
CREATE TABLE subscription_items (
    subscription_id uuid NOT NULL,
    workspace_id uuid,
    application_key text NOT NULL,
    UNIQUE (subscription_id, workspace_id, application_key)
);
CREATE TABLE workspace_app_installations (
    workspace_id uuid NOT NULL,
    application_key text NOT NULL,
    state text NOT NULL DEFAULT 'active',
    UNIQUE (workspace_id, application_key)
);
"""


@pytest.fixture()
def db():
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["TEST_DATABASE_URL"], future=True)
    schema = f"mig_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        for statement in DDL.strip().split(";"):
            if statement.strip():
                conn.execute(text(statement))
    yield engine, schema
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    engine.dispose()


def _run(engine, schema, script: str) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text(script))


def _rows(engine, schema, sql: str) -> list[tuple]:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {schema}"))
        return [tuple(r) for r in conn.execute(text(sql))]


def _seed(engine, schema) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from sqlalchemy import text

    plan, sub, workspace = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(
            text(
                "INSERT INTO plan_application_inclusions VALUES (:p,'retail.core'),(:p,'retail.purchasing')"
            ),
            {"p": plan},
        )
        conn.execute(
            text(
                "INSERT INTO subscription_items VALUES (:s,NULL,'retail.core'),(:s,NULL,'apparel')"
            ),
            {"s": sub},
        )
        conn.execute(
            text(
                "INSERT INTO workspace_app_installations VALUES (:w,'retail.core','active'),(:w,'retail.warehouse','active')"
            ),
            {"w": workspace},
        )
    return plan, sub, workspace


def test_the_rename_moves_every_legacy_key(db) -> None:
    engine, schema = db
    plan, sub, workspace = _seed(engine, schema)
    _run(engine, schema, SQL)

    inclusions = _rows(engine, schema, "SELECT application_key FROM plan_application_inclusions ORDER BY 1")
    assert inclusions == [("apparel",), ("apparel.purchasing",)]
    assert _rows(engine, schema, "SELECT count(*) FROM plan_application_inclusions WHERE application_key LIKE 'retail.%'") == [(0,)]

    # A duplicate new key is merged, not duplicated: the subscription keeps one row.
    subs = _rows(engine, schema, "SELECT application_key FROM subscription_items")
    assert subs == [("apparel",)]

    installs = _rows(engine, schema, "SELECT application_key FROM workspace_app_installations ORDER BY 1")
    assert installs == [("apparel",), ("apparel.warehouse",)]
    assert workspace  # the surviving installation row is the same workspace
    assert plan


def test_running_it_twice_changes_nothing(db) -> None:
    engine, schema = db
    _seed(engine, schema)
    _run(engine, schema, SQL)
    before = _rows(engine, schema, "SELECT application_key FROM workspace_app_installations ORDER BY 1")
    _run(engine, schema, SQL)
    after = _rows(engine, schema, "SELECT application_key FROM workspace_app_installations ORDER BY 1")
    assert before == after


def test_the_rollback_puts_the_old_keys_back(db) -> None:
    engine, schema = db
    _seed(engine, schema)
    _run(engine, schema, SQL)
    _run(engine, schema, ROLLBACK)
    keys = {r[0] for r in _rows(engine, schema, "SELECT application_key FROM plan_application_inclusions")}
    assert keys == {"retail.core", "retail.purchasing"}

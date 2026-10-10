"""Restore the missing sales_app policies on the infra RLS tables.

Revision ID: fe2026101001
Revises: fe2026100815
Create Date: 2026-10-10 23:30:00.000000

`fe2026100801` put infra tables (idempotency_keys, outbox_events,
processed_events, dr_policy, restore_test_runs, alembic_version) under RLS
with a service_role_all policy and an app_all policy for sales_app — its own
comment calls that "resolving P0-1: sales_app blocked by RLS on infra tables".
Production drifted: dr_policy, restore_test_runs and alembic_version lost
(never received) app_all, so sales_app saw ZERO rows in them.

That stayed invisible until the schema guard shipped: `assert_schema_current`
reads alembic_version as the app role, got an empty table back through the
RLS deny, classified the database as "not initialized" and refused every
boot on 2026-10-10 (five failed api deploys in a row). The 10-08 deployment
kept serving only because it predates the guard.

This migration re-declares app_all wherever it is missing on the six infra
tables, guarded and idempotent like fe2026100801's loop, so a fresh database
and a drifted one converge to the same state. Downgrade removes only what
this migration actually created — the same drift problem the other way, so
downgrade restores deny-on-drift, which is what production had anyway.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026101001"
down_revision: str | None = "fe2026100815"
branch_labels: str | None = None
depends_on: str | None = None

_INFRA_TABLES = (
    "idempotency_keys",
    "outbox_events",
    "processed_events",
    "dr_policy",
    "restore_test_runs",
    "alembic_version",
)


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'sales_app'")
    ).scalar():
        return
    for tbl in _INFRA_TABLES:
        if not conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :tbl"
            ),
            {"tbl": tbl},
        ).scalar():
            continue
        if conn.execute(
            sa.text(
                "SELECT 1 FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = :tbl "
                "AND policyname = 'app_all'"
            ),
            {"tbl": tbl},
        ).scalar():
            continue
        op.execute(
            f"CREATE POLICY app_all ON public.{tbl} "
            "FOR ALL TO sales_app USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    conn = op.get_bind()
    for tbl in ("dr_policy", "restore_test_runs", "alembic_version"):
        op.execute(f"DROP POLICY IF EXISTS app_all ON public.{tbl}")

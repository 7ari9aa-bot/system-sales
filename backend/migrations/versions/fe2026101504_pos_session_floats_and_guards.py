"""POS session floats + cashier/registry guards (§189 phase 1).

Three ERPNext-derived shifts in one migration:

- ``pos_session_floats`` — the drawer opens with a float PER PAYMENT METHOD
  (ERPNext ``POS Opening Entry Detail``), not one cash number. The session's
  ``opening_float`` column stays as the cash leg for compatibility and is
  mirrored into this table on open.
- ``pos_profiles.default_payment_method`` / ``returns_allowed_methods`` — the
  till's preselected tender (ERPNext ``set_grand_total_to_default_mop``) and
  the methods a refund may travel through (ERPNext ``allow_in_returns``).
- ``uq_pos_sessions_open_per_user`` — one OPEN session per cashier
  (ERPNext ``check_user_already_assigned``): a user cannot hold two drawers.

Every new table carries tenant_id, so RLS is enabled FORCED with the same
``tenant_isolation`` policy and ``sales_app`` grants as fe2026101501.

Revision ID: fe2026101504
Revises: fe2026101503
Create Date: 2026-10-15 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026101504"
down_revision: str | None = "fe2026101503"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _scope_fks(table: str) -> None:
    op.create_foreign_key(
        f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        f"fk_{table}_location_id", table, "locations", ["location_id"], ["id"],
        ondelete="SET NULL",
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def upgrade() -> None:
    op.create_table(
        "pos_session_floats",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("pos_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.String(31), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "session_id", "method", name="uq_pos_floats_session_method"
        ),
        sa.CheckConstraint(
            "method IN ('cash', 'card', 'wallet', 'bank_transfer')",
            name="ck_pos_floats_method",
        ),
    )
    _scope_fks("pos_session_floats")

    op.add_column(
        "pos_profiles", sa.Column("default_payment_method", sa.String(31), nullable=True)
    )
    op.add_column(
        "pos_profiles",
        sa.Column(
            "returns_allowed_methods",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
    )

    # One OPEN drawer per cashier. NULL cashier (legacy sessions) never matches.
    op.create_index(
        "uq_pos_sessions_open_per_user",
        "pos_sessions",
        ["tenant_id", "cashier_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    _enable_rls("pos_session_floats")
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE pos_session_floats TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.drop_index("uq_pos_sessions_open_per_user", table_name="pos_sessions")
    op.drop_column("pos_profiles", "returns_allowed_methods")
    op.drop_column("pos_profiles", "default_payment_method")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON pos_session_floats")
    op.drop_table("pos_session_floats")

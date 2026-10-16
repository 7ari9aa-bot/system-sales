"""POS profiles + per-method reconciliation + tender/change (§189 expansion).

Adds the ERPNext-inspired terminal layer to the POS adapter:
- ``pos_profiles`` / ``pos_profile_users`` — a preconfigured cashier station
  (default warehouse, walk-in customer, allowed payment methods, discount
  ceiling) and who may operate it.
- ``pos_registers.profile_id`` — a register optionally inherits a profile.
- ``pos_sessions.profile_id`` / ``cashier_user_id`` — the shift records the
  config it ran under and who held the drawer.
- ``pos_receipts.tendered_amount`` / ``change_amount`` — tender vs owed.
- ``pos_session_reconciliations`` — per-payment-method expected/counted/variance
  at close, replacing the cash-only single pair.

Every new table carries tenant_id, so RLS is enabled FORCED with the same
``tenant_isolation`` policy and ``sales_app`` grants as fd2026100406.

Revision ID: fe2026101501
Revises: fe2026101401
Create Date: 2026-10-15 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026101501"
down_revision: str | None = "fe2026101401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_NEW_TABLES = (
    "pos_profiles",
    "pos_profile_users",
    "pos_session_reconciliations",
)


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
        "pos_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(127), nullable=False),
        sa.Column("code", sa.String(31), nullable=False),
        sa.Column(
            "warehouse_id",
            sa.Uuid(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "default_customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "allowed_payment_methods",
            postgresql.JSONB(),
            server_default='["cash", "card", "wallet", "bank_transfer"]',
            nullable=False,
        ),
        sa.Column(
            "discount_ceiling_pct", sa.Numeric(5, 2), server_default="0", nullable=False
        ),
        sa.Column("require_customer", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "code", name="uq_pos_profiles_tenant_code"),
        sa.CheckConstraint(
            "discount_ceiling_pct >= 0 AND discount_ceiling_pct <= 100",
            name="ck_pos_profiles_discount_ceiling",
        ),
    )
    _scope_fks("pos_profiles")

    op.create_table(
        "pos_profile_users",
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
            "profile_id",
            sa.Uuid(),
            sa.ForeignKey("pos_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "profile_id", "user_id", name="uq_pos_profile_users"),
    )
    _scope_fks("pos_profile_users")

    op.create_table(
        "pos_session_reconciliations",
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
        sa.Column("expected_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("counted_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("variance", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "session_id", "method", name="uq_pos_recon_session_method"
        ),
        sa.CheckConstraint(
            "method IN ('cash', 'card', 'wallet', 'bank_transfer')",
            name="ck_pos_recon_method",
        ),
    )
    _scope_fks("pos_session_reconciliations")

    # --- columns added to existing POS tables -----------------------------
    op.add_column("pos_registers", sa.Column("profile_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_pos_registers_profile",
        "pos_registers",
        "pos_profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("pos_sessions", sa.Column("profile_id", sa.Uuid(), nullable=True))
    op.add_column("pos_sessions", sa.Column("cashier_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_pos_sessions_profile",
        "pos_sessions",
        "pos_profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_pos_sessions_cashier",
        "pos_sessions",
        "users",
        ["cashier_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "pos_receipts", sa.Column("tendered_amount", sa.Numeric(14, 2), nullable=True)
    )
    op.add_column(
        "pos_receipts", sa.Column("change_amount", sa.Numeric(14, 2), nullable=True)
    )

    for table in _NEW_TABLES:
        _enable_rls(table)

    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
              pos_profiles, pos_profile_users, pos_session_reconciliations
              TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.drop_column("pos_receipts", "change_amount")
    op.drop_column("pos_receipts", "tendered_amount")

    op.drop_constraint("fk_pos_sessions_cashier", "pos_sessions", type_="foreignkey")
    op.drop_constraint("fk_pos_sessions_profile", "pos_sessions", type_="foreignkey")
    op.drop_column("pos_sessions", "cashier_user_id")
    op.drop_column("pos_sessions", "profile_id")

    op.drop_constraint("fk_pos_registers_profile", "pos_registers", type_="foreignkey")
    op.drop_column("pos_registers", "profile_id")

    for table in reversed(_NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)

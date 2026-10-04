"""POS domain tables — registers, sessions, cash movements, receipts (§189).

Four POS-owned tables. The one-OPEN-session-per-register rule is a PARTIAL
unique index (status = 'OPEN'), so closed history coexists with the live
constraint. Cash movements are append-only; receipts are unique per tenant.
RLS follows the a1b2c3d4e5f6 pattern.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "fd2026100406"
down_revision: str | None = "fd2026100405"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_TABLES = ("pos_registers", "pos_sessions", "pos_cash_movements", "pos_receipts")


def _scope_fks(table: str) -> None:
    op.create_foreign_key(
        f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        f"fk_{table}_location_id", table, "locations", ["location_id"], ["id"],
        ondelete="SET NULL",
    )


def upgrade() -> None:
    op.create_table(
        "pos_registers",
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
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "code", name="uq_pos_registers_tenant_code"),
    )
    _scope_fks("pos_registers")

    op.create_table(
        "pos_sessions",
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
            "register_id",
            sa.Uuid(),
            sa.ForeignKey("pos_registers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(15), server_default="OPEN", nullable=False),
        sa.Column("opened_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("opening_float", sa.Numeric(14, 2), nullable=False),
        sa.Column("counted_cash", sa.Numeric(14, 2), nullable=True),
        sa.Column("expected_cash", sa.Numeric(14, 2), nullable=True),
        sa.Column("variance", sa.Numeric(14, 2), nullable=True),
        sa.Column("closed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED')", name="ck_pos_sessions_status"
        ),
    )
    _scope_fks("pos_sessions")
    op.create_foreign_key(
        "fk_pos_sessions_opened_by",
        "pos_sessions",
        "users",
        ["opened_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_pos_sessions_closed_by",
        "pos_sessions",
        "users",
        ["closed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # One OPEN session per register — a partial index, so closed history is
    # exempt from the constraint it would otherwise collide with.
    op.create_index(
        "uq_pos_sessions_open_per_register",
        "pos_sessions",
        ["tenant_id", "register_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    op.create_table(
        "pos_cash_movements",
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
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("reason", sa.String(31), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("reference_type", sa.String(31), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('in', 'out')", name="ck_pos_cash_direction"
        ),
        sa.CheckConstraint(
            "reason IN ('cash_sale', 'cash_refund', 'pay_in', 'pay_out',"
            " 'cash_drop', 'float_adjust')",
            name="ck_pos_cash_reason",
        ),
    )
    _scope_fks("pos_cash_movements")
    op.create_foreign_key(
        "fk_pos_cash_created_by",
        "pos_cash_movements",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_pos_cash_tenant_session",
        "pos_cash_movements",
        ["tenant_id", "session_id"],
    )

    op.create_table(
        "pos_receipts",
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
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("pos_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.String(31), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "number", name="uq_pos_receipts_tenant_number"),
    )
    _scope_fks("pos_receipts")

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )

    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
              pos_registers, pos_sessions, pos_cash_movements, pos_receipts
              TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)

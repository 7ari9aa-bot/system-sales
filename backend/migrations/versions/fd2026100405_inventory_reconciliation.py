"""inventory_reconciliation — ledger replay order + §188 findings table.

Part 1 adds ``ledger_seq`` (identity) to ``inventory_movements``: created_at
is the TRANSACTION time and the uuid4 id is not an order, so rows written in
one transaction had no defined replay order. Part 2 creates
``inventory_reconciliation_findings`` — a discrepancy becomes an explicit
record, never a silent fix (§188).

Historical rows receive arbitrary seq values (PG assigns them on the table
rewrite); they are consistent by their own balance_after chain as written.
New rows get a true write order.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "fd2026100405"
down_revision: str | None = "fd2026100404"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column(
        "inventory_movements",
        sa.Column(
            "ledger_seq",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
    )

    op.create_table(
        "inventory_reconciliation_findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("warehouse_id", sa.Uuid(), nullable=True),
        sa.Column("variant_id", sa.Uuid(), nullable=True),
        sa.Column("check_kind", sa.String(15), nullable=False),
        sa.Column("movement_id", sa.Uuid(), nullable=True),
        sa.Column("expected", sa.BigInteger(), nullable=False),
        sa.Column("actual", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(15), server_default="OPEN", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "check_kind IN ('chain', 'projection')", name="ck_inv_rec_check_kind"
        ),
        sa.CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_inv_rec_status"),
    )
    op.create_foreign_key(
        "fk_inv_rec_workspace_id",
        "inventory_reconciliation_findings",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inv_rec_location_id",
        "inventory_reconciliation_findings",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inv_rec_warehouse_id",
        "inventory_reconciliation_findings",
        "warehouses",
        ["warehouse_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inv_rec_variant_id",
        "inventory_reconciliation_findings",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_inv_rec_resolved_by",
        "inventory_reconciliation_findings",
        "users",
        ["resolved_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_inv_rec_tenant_status_created",
        "inventory_reconciliation_findings",
        ["tenant_id", "status", "created_at"],
    )

    op.execute(
        "ALTER TABLE inventory_reconciliation_findings ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE inventory_reconciliation_findings FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON inventory_reconciliation_findings"
    )
    op.execute(
        f"""CREATE POLICY tenant_isolation ON inventory_reconciliation_findings
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )

    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
              inventory_reconciliation_findings TO sales_app;
            -- The runtime role inserts ledger rows without ledger_seq, which
            -- draws from the identity sequence; resolve its name, don't guess.
            EXECUTE 'GRANT USAGE ON SEQUENCE '
              || pg_get_serial_sequence('inventory_movements', 'ledger_seq')
              || ' TO sales_app';
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON inventory_reconciliation_findings"
    )
    op.drop_table("inventory_reconciliation_findings")
    op.drop_column("inventory_movements", "ledger_seq")

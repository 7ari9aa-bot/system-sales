"""purchasing: suppliers, purchase orders, supplier payments/returns and moving-average cost.

Revision ID: fe2026102101
Revises: fe2026102001
Create Date: 2026-10-21 02:00:00.000000

Receiving and paying are separate facts: a purchase order stores only its receipt state, the
payment state is derived from supplier_payments. The database itself refuses a line whose total
is not quantity x cost, a cash payment without a drawer, a non-cash payment with one, a received
order without a received_at, and a decided return without a decision time.

Append-only tables (order lines, supplier payments, return lines, cost history) are granted
INSERT + SELECT ONLY, like inventory_movements: the audit trail cannot be edited even by a bug.
Every table is tenant-scoped with ENABLE + FORCE + tenant_isolation from day one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102101"
down_revision: str | None = "fe2026102001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_MONEY = sa.Numeric(14, 2)
_COST = sa.Numeric(14, 4)

# Mutable tables get full DML; append-only ones get INSERT + SELECT.
_MUTABLE = ("suppliers", "purchase_orders", "supplier_returns", "variant_costs")
_APPEND_ONLY = (
    "purchase_order_lines",
    "supplier_payments",
    "supplier_return_lines",
    "variant_cost_history",
)


def _scope_indexes(table: str) -> None:
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
    op.create_index(f"ix_{table}_location_id", table, ["location_id"])


def _secure(table: str, privileges: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        f"""DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            -- ALTER DEFAULT PRIVILEGES already handed sales_app every right on a new table, so a
            -- narrow GRANT alone narrows nothing: take everything back, then give exactly
            -- what is meant.
            REVOKE ALL ON TABLE {table} FROM sales_app;
            GRANT {privileges} ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(31), nullable=True),
        sa.Column("city", sa.String(80), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(15), server_default="active", nullable=False),
        sa.CheckConstraint("status IN ('active','inactive')", name="ck_suppliers_status"),
    )
    _scope_indexes("suppliers")
    op.create_index("ix_suppliers_tenant_status", "suppliers", ["tenant_id", "status"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("number", sa.String(31), nullable=False),
        sa.Column(
            "supplier_id",
            sa.Uuid(),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            sa.Uuid(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(15), server_default="draft", nullable=False),
        sa.Column("total", _MONEY, server_default="0", nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("tenant_id", "number", name="uq_purchase_orders_tenant_number"),
        sa.CheckConstraint(
            "status IN ('draft','received','cancelled')", name="ck_purchase_orders_status"
        ),
        sa.CheckConstraint("total >= 0", name="ck_purchase_orders_total"),
        sa.CheckConstraint(
            "(status = 'received') = (received_at IS NOT NULL)",
            name="ck_purchase_orders_received_at",
        ),
    )
    _scope_indexes("purchase_orders")
    op.create_index(
        "ix_purchase_orders_tenant_supplier", "purchase_orders", ["tenant_id", "supplier_id"]
    )
    op.create_index(
        "ix_purchase_orders_tenant_date", "purchase_orders", ["tenant_id", "order_date"]
    )

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "purchase_order_id",
            sa.Uuid(),
            sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", _MONEY, nullable=False),
        sa.Column("line_total", _MONEY, nullable=False),
        # The line's place on the document (1, 2, 3...). created_at is the transaction's now(),
        # identical for every
        # line of one document, so ordering by it would shuffle the lines differently on each read.
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "purchase_order_id", "position", name="uq_po_lines_position"
        ),
        sa.CheckConstraint("position > 0", name="ck_po_lines_position"),
        sa.CheckConstraint("quantity > 0", name="ck_po_lines_quantity"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_po_lines_unit_cost"),
        sa.CheckConstraint("line_total = quantity * unit_cost", name="ck_po_lines_total"),
    )
    _scope_indexes("purchase_order_lines")
    op.create_index("ix_po_lines_order", "purchase_order_lines", ["tenant_id", "purchase_order_id"])
    op.create_index("ix_po_lines_variant", "purchase_order_lines", ["tenant_id", "variant_id"])

    op.create_table(
        "supplier_payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "supplier_id",
            sa.Uuid(),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_id",
            sa.Uuid(),
            sa.ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("method", sa.String(15), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("pos_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reverses_payment_id",
            sa.Uuid(),
            sa.ForeignKey("supplier_payments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("amount > 0", name="ck_supplier_payments_amount"),
        sa.CheckConstraint(
            "method IN ('cash','card','wallet','bank_transfer')", name="ck_supplier_payments_method"
        ),
        sa.CheckConstraint(
            "(method = 'cash') = (session_id IS NOT NULL)",
            name="ck_supplier_payments_cash_has_session",
        ),
        sa.UniqueConstraint(
            "tenant_id", "reverses_payment_id", name="uq_supplier_payments_reversal"
        ),
    )
    _scope_indexes("supplier_payments")
    op.create_index(
        "ix_supplier_payments_tenant_supplier", "supplier_payments", ["tenant_id", "supplier_id"]
    )
    op.create_index(
        "ix_supplier_payments_tenant_order", "supplier_payments", ["tenant_id", "purchase_order_id"]
    )

    op.create_table(
        "supplier_returns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("number", sa.String(31), nullable=False),
        sa.Column(
            "supplier_id",
            sa.Uuid(),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_id",
            sa.Uuid(),
            sa.ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "warehouse_id",
            sa.Uuid(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(31), nullable=False),
        sa.Column("settlement", sa.String(15), nullable=False),
        sa.Column("status", sa.String(15), server_default="review", nullable=False),
        sa.Column("total", _MONEY, server_default="0", nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "refund_session_id",
            sa.Uuid(),
            sa.ForeignKey("pos_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("tenant_id", "number", name="uq_supplier_returns_tenant_number"),
        sa.CheckConstraint(
            "status IN ('review','accepted','rejected')", name="ck_supplier_returns_status"
        ),
        sa.CheckConstraint(
            "settlement IN ('cash','credit','replace')", name="ck_supplier_returns_settlement"
        ),
        sa.CheckConstraint("total >= 0", name="ck_supplier_returns_total"),
        sa.CheckConstraint(
            "(status = 'review') = (decided_at IS NULL)", name="ck_supplier_returns_decided_at"
        ),
    )
    _scope_indexes("supplier_returns")
    op.create_index(
        "ix_supplier_returns_tenant_supplier", "supplier_returns", ["tenant_id", "supplier_id"]
    )

    op.create_table(
        "supplier_return_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "supplier_return_id",
            sa.Uuid(),
            sa.ForeignKey("supplier_returns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", _MONEY, nullable=False),
        sa.Column("line_total", _MONEY, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "supplier_return_id", "position", name="uq_sr_lines_position"
        ),
        sa.CheckConstraint("position > 0", name="ck_sr_lines_position"),
        sa.CheckConstraint("quantity > 0", name="ck_sr_lines_quantity"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_sr_lines_unit_cost"),
        sa.CheckConstraint("line_total = quantity * unit_cost", name="ck_sr_lines_total"),
    )
    _scope_indexes("supplier_return_lines")
    op.create_index(
        "ix_sr_lines_return", "supplier_return_lines", ["tenant_id", "supplier_return_id"]
    )

    op.create_table(
        "variant_costs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL = the cost is UNKNOWN (stock that was on the shelf before any purchase was recorded).
        # It is not 0:
        # averaging unknown stock as "free" would understate every cost after the first delivery.
        sa.Column("avg_cost", _COST, nullable=True),
        sa.UniqueConstraint("tenant_id", "variant_id", name="uq_variant_costs_tenant_variant"),
        sa.CheckConstraint("avg_cost >= 0", name="ck_variant_costs_avg"),
    )
    _scope_indexes("variant_costs")

    op.create_table(
        "variant_cost_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_avg_cost", _COST, nullable=True),
        sa.Column("new_avg_cost", _COST, nullable=False),
        sa.Column("on_hand_before", sa.Integer(), nullable=False),
        sa.Column("received_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", _MONEY, nullable=False),
        sa.Column(
            "purchase_order_id",
            sa.Uuid(),
            sa.ForeignKey("purchase_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    _scope_indexes("variant_cost_history")
    op.create_index(
        "ix_variant_cost_history_variant",
        "variant_cost_history",
        ["tenant_id", "variant_id", "created_at"],
    )

    for table in _MUTABLE:
        _secure(table, "SELECT, INSERT, UPDATE, DELETE")
    for table in _APPEND_ONLY:
        _secure(table, "SELECT, INSERT")


def downgrade() -> None:
    for table in (
        "variant_cost_history",
        "variant_costs",
        "supplier_return_lines",
        "supplier_returns",
        "supplier_payments",
        "purchase_order_lines",
        "purchase_orders",
        "suppliers",
    ):
        op.drop_table(table)

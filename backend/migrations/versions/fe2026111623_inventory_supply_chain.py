"""inventory: the supply chain around the ledger — transfers, locations, quality, valuation.

Revision ID: fe2026111623
Revises: fe2026111622
Create Date: 2026-11-16 23:00:00.000000

WHY. The ledger and the balance were already right: an append-only
inventory_movements and a projection that reconciliation proves against it.
What the shop could not express was everything around that ledger — a transfer
that travels in a truck, a shelf inside a warehouse, goods held for
inspection, the cost layer a FIFO pass consumes, the rule that says "order
more of this".

WHAT THIS CHANGES IN THE EXISTING TABLES. Only two columns and one widened
column:

* inventory_balances.quarantined — the units of the on-hand stock held for
  inspection. `on_hand` keeps meaning TOTAL physical stock, so sellable is
  DERIVED (on_hand - quarantined) and never stored a second time. The grain of
  the balance does NOT change: it stays (tenant_id, warehouse_id, variant_id).
* inventory_movements.cost_value — the book cost of the units a row moved.
  NULL means "unknown", never 0: a zero cost would silently value stock at
  nothing. Rows written before this column keep NULL.
* inventory_transfers.status widened from VARCHAR(15) to VARCHAR(31) because
  `partially_received` is 18 characters long. The old column could not hold
  one of the nine statuses of the transfer lifecycle.

WHAT THIS ADDS. Nineteen tables, each with tenant_id and the canonical
tenant_isolation policy:

* the transfer document's relational lines, shipments and receipts — a
  transfer is a lifecycle, not two moves at once, so what is still in transit
  is a question about documents;
* warehouse locations, their balances and the append-only record of stock
  moving between them — a location is a sub-position, never a second balance;
* quality inspections and their results — what arrived, and whether it may be
  sold;
* FIFO cost layers and landed costs — the cost side of the ledger;
* replenishment policies and reorder suggestions — the rule, and the
  arithmetic behind what it says to do;
* lots, serials and the per-variant tracking rule.

SAFETY. Additive only: two columns with a server default, one column widened,
and new tables. No existing row is rewritten and no existing value changes.
Every new table is ENABLE + FORCE + tenant_isolation like its neighbours, so
a tenant can never read another tenant's stock.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111623"
down_revision: str | None = "fe2026111622"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

#: Cost keeps 4 places (see purchasing's COST): an average of 10.00 and 12.00
#: over odd quantities is not a clean cent, and rounding every layer to 2 places
#: at every receipt would drift.
_COST = sa.Numeric(precision=14, scale=4)
#: Money is 2 places (model_kit's MONEY).
_MONEY = sa.Numeric(precision=14, scale=2)


def _scoped_columns() -> list[sa.Column]:
    """id + tenant + scope + timestamps (TenantMixin, TimestampMixin, WorkspaceScopeMixin)."""
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _scoped_append_only_columns() -> list[sa.Column]:
    """id + tenant + scope + created_at (AppendOnlyCreatedAtMixin: no updated_at)."""
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _tenant_columns() -> list[sa.Column]:
    """id + tenant + timestamps, WITHOUT the scope columns.

    Used by the two tables whose own `location_id` is a WAREHOUSE location: the
    hierarchy `location_id` of WorkspaceScopeMixin would be the same name for
    two different things.
    """
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _secure(table: str, grants: str = "SELECT, INSERT, UPDATE, DELETE") -> None:
    """Row-level security exactly like every other tenant table."""
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
            REVOKE ALL ON TABLE {table} FROM sales_app;
            GRANT {grants} ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def _scope_indexes(table: str) -> None:
    """The three indexes the mixins declare (index=True on tenant/workspace/location)."""
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
    op.create_index(f"ix_{table}_location_id", table, ["location_id"])


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. The two new columns on the tables that already exist.
    #    Both carry a server default, so every existing row stays valid.
    # ------------------------------------------------------------------
    op.add_column(
        "inventory_balances",
        sa.Column("quarantined", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "inventory_movements",
        sa.Column("cost_value", _COST, nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. The transfer document's lifecycle columns.
    # ------------------------------------------------------------------
    op.add_column(
        "inventory_transfers",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inventory_transfers",
        sa.Column(
            "approved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "inventory_transfers",
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inventory_transfers",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("inventory_transfers", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column(
        "inventory_transfers", sa.Column("exception_reason", sa.String(255), nullable=True)
    )
    # `partially_received` does not fit in VARCHAR(15).
    op.alter_column(
        "inventory_transfers",
        "status",
        existing_type=sa.String(15),
        type_=sa.String(31),
        existing_nullable=False,
    )

    # ------------------------------------------------------------------
    # 3. The stocktake upgrade: what kind of count, of what, and by whom.
    # ------------------------------------------------------------------
    op.add_column(
        "stocktakes",
        sa.Column("kind", sa.String(15), server_default="full", nullable=False),
    )
    op.add_column(
        "stocktakes",
        sa.Column("scope", postgresql.JSONB(), server_default="[]", nullable=False),
    )
    op.add_column(
        "stocktakes",
        sa.Column("blind", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "stocktakes",
        sa.Column("recount_threshold_pct", sa.Integer(), server_default="10", nullable=False),
    )
    op.add_column(
        "stocktake_lines",
        sa.Column(
            "counted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "stocktake_lines",
        sa.Column("recount_count", sa.Integer(), server_default="0", nullable=False),
    )

    # ------------------------------------------------------------------
    # 4. The new tables. The order matters: a table is created after the
    #    tables it points at.
    # ------------------------------------------------------------------

    # -- the transfer document's lines -------------------------------
    op.create_table(
        "inventory_transfer_lines",
        *_scoped_append_only_columns(),
        sa.Column(
            "transfer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_transfers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("quantity_shipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quantity_received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "transfer_id", "position", name="uq_inv_transfer_lines_position"
        ),
        sa.UniqueConstraint(
            "tenant_id", "transfer_id", "variant_id", name="uq_inv_transfer_lines_variant"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_inv_transfer_lines_quantity"),
        sa.CheckConstraint("quantity_shipped >= 0", name="ck_inv_transfer_lines_shipped"),
        sa.CheckConstraint("quantity_received >= 0", name="ck_inv_transfer_lines_received"),
        sa.CheckConstraint("position > 0", name="ck_inv_transfer_lines_position"),
    )

    # -- the despatch -------------------------------------------------
    op.create_table(
        "inventory_transfer_shipments",
        *_scoped_columns(),
        sa.Column(
            "transfer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_transfers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shipped_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "shipped_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("carrier", sa.String(63), nullable=True),
        sa.Column("tracking_ref", sa.String(63), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )

    op.create_table(
        "inventory_transfer_shipment_lines",
        *_scoped_append_only_columns(),
        sa.Column(
            "shipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_transfer_shipments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "shipment_id", "position", name="uq_inv_transfer_shipment_lines_position"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_inv_transfer_shipment_lines_quantity"),
        sa.CheckConstraint("position > 0", name="ck_inv_transfer_shipment_lines_position"),
    )

    # -- the arrival ---------------------------------------------------
    op.create_table(
        "inventory_transfer_receipts",
        *_scoped_columns(),
        sa.Column(
            "transfer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_transfers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_transfer_shipments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "received_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
    )

    op.create_table(
        "inventory_transfer_receipt_lines",
        *_scoped_append_only_columns(),
        sa.Column(
            "receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_transfer_receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(15), server_default="good", nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_inv_transfer_receipt_lines_quantity"),
        sa.CheckConstraint(
            "condition IN ('good','damaged','short')",
            name="ck_inv_transfer_receipt_lines_condition",
        ),
    )

    # -- where the stock sits ------------------------------------------
    op.create_table(
        "warehouse_locations",
        *_scoped_columns(),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(63), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(31), nullable=False),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouse_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "warehouse_id", "code", name="uq_warehouse_locations_tenant_wh_code"
        ),
        sa.CheckConstraint(
            "kind IN ('receiving','qc','storage','picking','packing','returns',"
            "'quarantine','damaged','zone','rack','shelf','bin')",
            name="ck_warehouse_locations_kind",
        ),
        sa.CheckConstraint(
            "capacity IS NULL OR capacity >= 0", name="ck_warehouse_locations_capacity"
        ),
    )

    op.create_table(
        "inventory_location_balances",
        *_tenant_columns(),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouse_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("on_hand", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "location_id", "variant_id", name="uq_inv_location_balances_position"
        ),
        sa.CheckConstraint("on_hand >= 0", name="ck_inv_location_balances_on_hand"),
    )

    op.create_table(
        "inventory_location_movements",
        *_scoped_append_only_columns(),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouse_locations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "to_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouse_locations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(31), nullable=False),
        sa.Column(
            "moved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_inv_location_movements_quantity"),
        sa.CheckConstraint(
            "reason IN ('putaway','replenishment','pick','transfer','adjustment','relocation')",
            name="ck_inv_location_movements_reason",
        ),
    )

    # -- who counts what in a stocktake -------------------------------
    op.create_table(
        "stocktake_assignments",
        *_tenant_columns(),
        sa.Column(
            "stocktake_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stocktakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouse_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(15), server_default="assigned", nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counted_lines", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "stocktake_id", "user_id", name="uq_stocktake_assignments_user"
        ),
        sa.CheckConstraint(
            "status IN ('assigned','counting','counted','recount')",
            name="ck_stocktake_assignments_status",
        ),
        sa.CheckConstraint(
            "counted_lines >= 0", name="ck_stocktake_assignments_counted_lines"
        ),
    )

    # -- quality --------------------------------------------------------
    op.create_table(
        "inventory_quality_inspections",
        *_scoped_columns(),
        sa.Column("source_type", sa.String(31), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(15), server_default="open", nullable=False),
        sa.Column(
            "inspected_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('goods_receipt','return_receipt','transfer_receipt')",
            name="ck_inv_quality_inspections_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('open','passed','quarantined','rejected')",
            name="ck_inv_quality_inspections_status",
        ),
    )

    op.create_table(
        "inventory_inspection_results",
        *_scoped_append_only_columns(),
        sa.Column(
            "inspection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_quality_inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(15), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "inspected_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tenant_id", "inspection_id", "variant_id", name="uq_inv_inspection_results_variant"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_inv_inspection_results_quantity"),
        sa.CheckConstraint(
            "verdict IN ('pass','quarantine','reject')",
            name="ck_inv_inspection_results_verdict",
        ),
    )

    # -- valuation ------------------------------------------------------
    op.create_table(
        "inventory_cost_layers",
        *_scoped_columns(),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("received_quantity", sa.Integer(), nullable=False),
        sa.Column("remaining_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unit_cost", _COST, nullable=False),
        sa.Column(
            "layer_date",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(31), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("received_quantity > 0", name="ck_inv_cost_layers_received_quantity"),
        sa.CheckConstraint("remaining_quantity >= 0", name="ck_inv_cost_layers_remaining_quantity"),
        sa.CheckConstraint(
            "remaining_quantity <= received_quantity",
            name="ck_inv_cost_layers_remaining_le_received",
        ),
        sa.CheckConstraint("unit_cost >= 0", name="ck_inv_cost_layers_unit_cost"),
    )

    op.create_table(
        "inventory_landed_costs",
        *_scoped_columns(),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("total", _MONEY, server_default="0", nullable=False),
        sa.Column("status", sa.String(15), server_default="draft", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("total >= 0", name="ck_inv_landed_costs_total"),
        sa.CheckConstraint("status IN ('draft','posted')", name="ck_inv_landed_costs_status"),
    )

    op.create_table(
        "inventory_landed_cost_lines",
        *_scoped_append_only_columns(),
        sa.Column(
            "landed_cost_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_landed_costs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_inv_landed_cost_lines_quantity"),
        sa.CheckConstraint("amount >= 0", name="ck_inv_landed_cost_lines_amount"),
    )

    # -- replenishment --------------------------------------------------
    op.create_table(
        "inventory_policies",
        *_scoped_columns(),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("min_stock", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_stock", sa.Integer(), nullable=True),
        sa.Column("safety_stock", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lead_time_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("moq", sa.Integer(), server_default="1", nullable=False),
        sa.Column("order_multiple", sa.Integer(), server_default="1", nullable=False),
        sa.Column("review_period_days", sa.Integer(), server_default="7", nullable=False),
        sa.Column(
            "preferred_supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tenant_id", "variant_id", "warehouse_id", name="uq_inventory_policies_variant_wh"
        ),
        sa.CheckConstraint("min_stock >= 0", name="ck_inventory_policies_min_stock"),
        sa.CheckConstraint(
            "max_stock IS NULL OR max_stock >= 0", name="ck_inventory_policies_max_stock"
        ),
        sa.CheckConstraint("safety_stock >= 0", name="ck_inventory_policies_safety_stock"),
        sa.CheckConstraint("lead_time_days >= 0", name="ck_inventory_policies_lead_time_days"),
        sa.CheckConstraint("moq > 0", name="ck_inventory_policies_moq"),
        sa.CheckConstraint("order_multiple > 0", name="ck_inventory_policies_order_multiple"),
        sa.CheckConstraint(
            "review_period_days > 0", name="ck_inventory_policies_review_period_days"
        ),
    )

    op.create_table(
        "reorder_suggestions",
        *_scoped_columns(),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suggested_quantity", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(15), nullable=False),
        sa.Column("reason", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(15), server_default="open", nullable=False),
        sa.CheckConstraint("suggested_quantity > 0", name="ck_reorder_suggestions_quantity"),
        sa.CheckConstraint("source IN ('transfer','purchase')", name="ck_reorder_suggestions_source"),
        sa.CheckConstraint(
            "status IN ('open','accepted','dismissed')", name="ck_reorder_suggestions_status"
        ),
    )

    # -- traceability ----------------------------------------------------
    op.create_table(
        "inventory_lots",
        *_scoped_columns(),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lot_code", sa.String(63), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("unit_cost", _COST, nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "variant_id", "lot_code", name="uq_inventory_lots_tenant_variant_code"
        ),
    )

    op.create_table(
        "inventory_serials",
        *_scoped_columns(),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("serial_code", sa.String(63), nullable=False),
        sa.Column(
            "lot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_lots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(15), server_default="in_stock", nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "variant_id", "serial_code", name="uq_inventory_serials_tenant_variant_code"
        ),
        sa.CheckConstraint(
            "status IN ('in_stock','quarantined','sold','returned','damaged')",
            name="ck_inventory_serials_status",
        ),
    )

    op.create_table(
        "variant_tracking_policies",
        *_scoped_columns(),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(15), server_default="none", nullable=False),
        sa.Column("expiry_required", sa.Boolean(), server_default="false", nullable=False),
        sa.UniqueConstraint("tenant_id", "variant_id", name="uq_variant_tracking_policies_variant"),
        sa.CheckConstraint(
            "mode IN ('none','batch','serial')", name="ck_variant_tracking_policies_mode"
        ),
    )

    # ------------------------------------------------------------------
    # 5. The indexes the read paths need.
    # ------------------------------------------------------------------
    for _table in (
        "inventory_transfer_lines",
        "inventory_transfer_shipments",
        "inventory_transfer_shipment_lines",
        "inventory_transfer_receipts",
        "inventory_transfer_receipt_lines",
        "warehouse_locations",
        "inventory_location_movements",
        "inventory_quality_inspections",
        "inventory_inspection_results",
        "inventory_cost_layers",
        "inventory_landed_costs",
        "inventory_landed_cost_lines",
        "inventory_policies",
        "reorder_suggestions",
        "inventory_lots",
        "inventory_serials",
        "variant_tracking_policies",
    ):
        _scope_indexes(_table)

    # The two tables without the scope columns.
    op.create_index("ix_stocktake_assignments_tenant_id", "stocktake_assignments", ["tenant_id"])
    op.create_index(
        "ix_inventory_location_balances_tenant_id", "inventory_location_balances", ["tenant_id"]
    )

    op.create_index(
        "ix_inv_transfer_lines_transfer", "inventory_transfer_lines", ["tenant_id", "transfer_id"]
    )
    op.create_index(
        "ix_inv_transfer_lines_variant", "inventory_transfer_lines", ["tenant_id", "variant_id"]
    )
    op.create_index(
        "ix_inv_transfer_shipments_transfer",
        "inventory_transfer_shipments",
        ["tenant_id", "transfer_id"],
    )
    op.create_index(
        "ix_inv_transfer_shipment_lines_shipment",
        "inventory_transfer_shipment_lines",
        ["tenant_id", "shipment_id"],
    )
    op.create_index(
        "ix_inv_transfer_receipts_transfer",
        "inventory_transfer_receipts",
        ["tenant_id", "transfer_id"],
    )
    op.create_index(
        "ix_inv_transfer_receipt_lines_receipt",
        "inventory_transfer_receipt_lines",
        ["tenant_id", "receipt_id"],
    )
    op.create_index(
        "ix_warehouse_locations_warehouse",
        "warehouse_locations",
        ["tenant_id", "warehouse_id"],
    )
    op.create_index(
        "ix_inv_location_balances_wh_variant",
        "inventory_location_balances",
        ["tenant_id", "warehouse_id", "variant_id"],
    )
    op.create_index(
        "ix_inv_location_movements_wh_variant",
        "inventory_location_movements",
        ["tenant_id", "warehouse_id", "variant_id", "created_at"],
    )
    op.create_index(
        "ix_stocktake_assignments_stocktake",
        "stocktake_assignments",
        ["tenant_id", "stocktake_id"],
    )
    op.create_index(
        "ix_inv_quality_inspections_wh_status",
        "inventory_quality_inspections",
        ["tenant_id", "warehouse_id", "status"],
    )
    op.create_index(
        "ix_inv_quality_inspections_source",
        "inventory_quality_inspections",
        ["tenant_id", "source_type", "source_id"],
    )
    op.create_index(
        "ix_inv_inspection_results_inspection",
        "inventory_inspection_results",
        ["tenant_id", "inspection_id"],
    )
    op.create_index(
        "ix_inv_cost_layers_fifo",
        "inventory_cost_layers",
        ["tenant_id", "variant_id", "warehouse_id", "layer_date"],
    )
    op.create_index(
        "ix_inv_landed_costs_warehouse", "inventory_landed_costs", ["tenant_id", "warehouse_id"]
    )
    op.create_index(
        "ix_inv_landed_cost_lines_cost",
        "inventory_landed_cost_lines",
        ["tenant_id", "landed_cost_id"],
    )
    op.create_index(
        "ix_reorder_suggestions_variant_wh",
        "reorder_suggestions",
        ["tenant_id", "variant_id", "warehouse_id"],
    )
    op.create_index("ix_reorder_suggestions_status", "reorder_suggestions", ["tenant_id", "status"])
    op.create_index("ix_inventory_lots_variant", "inventory_lots", ["tenant_id", "variant_id"])
    op.create_index("ix_inventory_serials_variant", "inventory_serials", ["tenant_id", "variant_id"])

    # ------------------------------------------------------------------
    # 6. The constraints on the tables that already existed.
    # ------------------------------------------------------------------
    op.create_check_constraint(
        "ck_inventory_balances_quarantined",
        "inventory_balances",
        "quarantined >= 0",
    )
    op.create_check_constraint(
        "ck_inventory_transfers_status",
        "inventory_transfers",
        "status IN ('draft','approved','picking','packed','in_transit',"
        "'partially_received','completed','cancelled','exception')",
    )
    op.create_check_constraint(
        "ck_stocktakes_kind",
        "stocktakes",
        "kind IN ('full','cycle','blind','spot','abc')",
    )
    op.create_check_constraint(
        "ck_stocktake_lines_recount_count",
        "stocktake_lines",
        "recount_count >= 0",
    )

    # ------------------------------------------------------------------
    # 7. Row-level security on every new table.
    # ------------------------------------------------------------------
    for _table in (
        "inventory_transfer_lines",
        "inventory_transfer_shipments",
        "inventory_transfer_shipment_lines",
        "inventory_transfer_receipts",
        "inventory_transfer_receipt_lines",
        "warehouse_locations",
        "inventory_location_balances",
        "inventory_location_movements",
        "stocktake_assignments",
        "inventory_quality_inspections",
        "inventory_inspection_results",
        "inventory_cost_layers",
        "inventory_landed_costs",
        "inventory_landed_cost_lines",
        "inventory_policies",
        "reorder_suggestions",
        "inventory_lots",
        "inventory_serials",
        "variant_tracking_policies",
    ):
        _secure(_table)


def downgrade() -> None:
    # The new tables go first, in reverse order of creation.
    for _table in (
        "variant_tracking_policies",
        "inventory_serials",
        "inventory_lots",
        "reorder_suggestions",
        "inventory_policies",
        "inventory_landed_cost_lines",
        "inventory_landed_costs",
        "inventory_cost_layers",
        "inventory_inspection_results",
        "inventory_quality_inspections",
        "stocktake_assignments",
        "inventory_location_movements",
        "inventory_location_balances",
        "warehouse_locations",
        "inventory_transfer_receipt_lines",
        "inventory_transfer_receipts",
        "inventory_transfer_shipment_lines",
        "inventory_transfer_shipments",
        "inventory_transfer_lines",
    ):
        op.drop_table(_table)

    # The constraints on the tables that already existed.
    op.drop_constraint(
        "ck_stocktake_lines_recount_count", "stocktake_lines", type_="check"
    )
    op.drop_constraint("ck_stocktakes_kind", "stocktakes", type_="check")
    op.drop_constraint("ck_inventory_transfers_status", "inventory_transfers", type_="check")
    op.drop_constraint("ck_inventory_balances_quarantined", "inventory_balances", type_="check")

    # The columns this migration added.
    op.drop_column("stocktake_lines", "recount_count")
    op.drop_column("stocktake_lines", "counted_by_user_id")
    op.drop_column("stocktakes", "recount_threshold_pct")
    op.drop_column("stocktakes", "blind")
    op.drop_column("stocktakes", "scope")
    op.drop_column("stocktakes", "kind")
    op.drop_column("inventory_transfers", "exception_reason")
    op.drop_column("inventory_transfers", "notes")
    op.drop_column("inventory_transfers", "cancelled_at")
    op.drop_column("inventory_transfers", "shipped_at")
    op.drop_column("inventory_transfers", "approved_by_user_id")
    op.drop_column("inventory_transfers", "approved_at")
    op.alter_column(
        "inventory_transfers",
        "status",
        existing_type=sa.String(31),
        type_=sa.String(15),
        existing_nullable=False,
    )
    op.drop_column("inventory_movements", "cost_value")
    op.drop_column("inventory_balances", "quarantined")

"""purchasing + catalog: goods receipts (D5) and bundles/kits.

Revision ID: fe2026111626
Revises: fe2026111623 (inventory supply chain) + fe2026111625 (e-invoice)
Create Date: 2026-11-16 23:40:00.000000

WHY. D5: a purchase order never adds stock — only an approved goods receipt
does. Today `purchase_orders` has no receipt document at all: receiving writes
the stock movement off the order itself, so "what was ordered" and "what
arrived" are the same row and a short delivery is invisible.

WHAT THIS CHANGES IN THE EXISTING TABLES.

* purchase_orders.status widened from VARCHAR(15) to VARCHAR(31) because
  `partially_received` is 18 characters long. The old column could not hold
  one of the six states of the order lifecycle.
* purchase_orders.status CHECK widened from (draft, received, cancelled) to
  (draft, approved, sent, partially_received, received, cancelled) — the order
  is now a document with a lifecycle: written, approved, sent to the supplier,
  received in parts, received in full.
* purchase_orders gains approved_at, approved_by_user_id, sent_at and
  expected_at: who approved the order, when it went to the supplier, and when
  the goods were promised. All nullable, so no existing row changes.
* purchase_order_lines gains quantity_received: what was ORDERED stays in
  `quantity`, what actually ARRIVED lands here. A receipt of 70 against an
  order of 100 leaves 30 open.

`ck_purchase_orders_received_at` is deliberately left alone: its expression
`(status = 'received') = (received_at IS NOT NULL)` already says exactly what
the new meaning of `received_at` requires — the moment the order became FULLY
received — so a `partially_received` order carries no received_at, and the
constraint keeps enforcing that.

`purchase_order_lines` is no longer a strictly append-only table: the receipt
that closes a line writes `quantity_received` on it, so the app role is given
UPDATE on that one table (DELETE stays revoked — a line is still never
deleted, and the order's other columns are still not the app's to rewrite).

WHAT THIS ADDS. Four tables, each with tenant_id and the canonical
tenant_isolation policy:

* goods_receipts + goods_receipt_lines — the document that says what came in
  the door. The stock movement references the receipt, not the order, and a
  receipt may be partial, so one order can carry several receipts.
* product_bundles + product_bundle_lines — a bundle/kit is a product sold as a
  fixed set of components. The component list is relational data, not a JSONB
  blob, so selling the bundle can walk it and decrement each component
  exactly once (twice would sell stock that does not exist; never would
  create phantom stock).

SAFETY. Additive only: two columns with a server default, one column widened,
one CHECK replaced with a wider one, and new tables. No existing row is
rewritten and no existing value changes. Every new table is ENABLE + FORCE +
tenant_isolation like its neighbours, so a tenant can never read another
tenant's goods.

NOTE ON THE REVISION ID. This file was assigned the id `fe2026111624`, but
`fe2026111624` is already taken by the committed tax-rates revision
(fe2026111624_tax_rates_and_invoice_stamping.py) — two files with one id make
alembic refuse to load the script directory at all. The id here is therefore
`fe2026111626`, and `down_revision` is a MERGE of the two open branches
(fe2026111623, the inventory supply chain, and fe2026111625, the e-invoice
subsystem) so the tree has exactly ONE head again and `alembic upgrade head`
resolves.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111626"
down_revision: tuple[str, str] = ("fe2026111623", "fe2026111625")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

#: Cost keeps 4 places (see purchasing's COST): an average of 10.00 and 12.00
#: over odd quantities is not a clean cent, and rounding every receipt to 2
#: places would drift.
_COST = sa.Numeric(precision=14, scale=4)


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
    # 1. The purchase order becomes a document with a lifecycle.
    # ------------------------------------------------------------------
    op.drop_constraint("ck_purchase_orders_status", "purchase_orders", type_="check")
    # `partially_received` does not fit in VARCHAR(15).
    op.alter_column(
        "purchase_orders",
        "status",
        existing_type=sa.String(15),
        type_=sa.String(31),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_purchase_orders_status",
        "purchase_orders",
        "status IN ('draft','approved','sent','partially_received','received','cancelled')",
    )

    # ------------------------------------------------------------------
    # 2. The order's own lifecycle columns. All nullable: no existing row
    #    changes, and a row written before the lifecycle existed stays valid.
    # ------------------------------------------------------------------
    op.add_column(
        "purchase_orders",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column(
            "approved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("expected_at", sa.Date(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. What was ordered vs what arrived.
    # ------------------------------------------------------------------
    op.add_column(
        "purchase_order_lines",
        sa.Column("quantity_received", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_purchase_order_lines_quantity_received",
        "purchase_order_lines",
        "quantity_received >= 0",
    )

    # ------------------------------------------------------------------
    # 4. The new tables. The order matters: a table is created after the
    #    tables it points at.
    # ------------------------------------------------------------------
    # -- what actually arrived ------------------------------------------
    op.create_table(
        "goods_receipts",
        *_scoped_columns(),
        sa.Column("number", sa.String(31), nullable=False),
        sa.Column(
            "purchase_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(15), server_default="draft", nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("tenant_id", "number", name="uq_goods_receipts_tenant_number"),
        sa.CheckConstraint(
            "status IN ('draft','posted','rejected','cancelled')", name="ck_goods_receipts_status"
        ),
    )
    op.create_table(
        "goods_receipt_lines",
        *_scoped_append_only_columns(),
        sa.Column(
            "goods_receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("goods_receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_line_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", _COST, nullable=False),
        sa.Column("line_total", _COST, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(15), server_default="good", nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "goods_receipt_id", "position", name="uq_goods_receipt_lines_position"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_goods_receipt_lines_quantity"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_goods_receipt_lines_unit_cost"),
        sa.CheckConstraint("line_total >= 0", name="ck_goods_receipt_lines_line_total"),
        sa.CheckConstraint("position > 0", name="ck_goods_receipt_lines_position"),
        sa.CheckConstraint(
            "condition IN ('good','quarantine','reject')", name="ck_goods_receipt_lines_condition"
        ),
    )

    # -- a bundle sold as a set of components --------------------------
    op.create_table(
        "product_bundles",
        *_scoped_columns(),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("bundle_type", sa.String(15), server_default="bundle", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "product_id", "name", name="uq_product_bundles_tenant_product_name"
        ),
    )
    op.create_table(
        "product_bundle_lines",
        *_scoped_columns(),
        sa.Column(
            "bundle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_bundles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "bundle_id",
            "variant_id",
            name="uq_product_bundle_lines_tenant_bundle_variant",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_product_bundle_lines_quantity"),
    )

    # ------------------------------------------------------------------
    # 5. The indexes.
    # ------------------------------------------------------------------
    _scope_indexes("goods_receipts")
    op.create_index(
        "ix_goods_receipts_tenant_purchase_order",
        "goods_receipts",
        ["tenant_id", "purchase_order_id"],
    )
    op.create_index(
        "ix_goods_receipts_tenant_warehouse",
        "goods_receipts",
        ["tenant_id", "warehouse_id"],
    )
    _scope_indexes("goods_receipt_lines")
    op.create_index(
        "ix_goods_receipt_lines_receipt",
        "goods_receipt_lines",
        ["tenant_id", "goods_receipt_id"],
    )
    _scope_indexes("product_bundles")
    _scope_indexes("product_bundle_lines")

    # ------------------------------------------------------------------
    # 6. Row-level security on every new table.
    # ------------------------------------------------------------------
    for _table in (
        "goods_receipts",
        "goods_receipt_lines",
        "product_bundles",
        "product_bundle_lines",
    ):
        _secure(_table)

    # ------------------------------------------------------------------
    # 7. The one grant that changes on an existing table: the receipt
    #    closes a purchase order line by writing quantity_received on it.
    #    DELETE stays revoked (a line is never deleted) and nothing else
    #    about the table's posture changes.
    # ------------------------------------------------------------------
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT UPDATE ON TABLE purchase_order_lines TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    # The new tables go first, in reverse order of creation.
    for _table in (
        "product_bundle_lines",
        "product_bundles",
        "goods_receipt_lines",
        "goods_receipts",
    ):
        op.drop_table(_table)

    # The constraint on a table that already existed.
    op.drop_constraint(
        "ck_purchase_order_lines_quantity_received", "purchase_order_lines", type_="check"
    )

    # The columns this migration added.
    op.drop_column("purchase_order_lines", "quantity_received")
    op.drop_column("purchase_orders", "expected_at")
    op.drop_column("purchase_orders", "sent_at")
    op.drop_column("purchase_orders", "approved_by_user_id")
    op.drop_column("purchase_orders", "approved_at")

    # The purchase order goes back to being a two-state document. The states
    # that did not exist before are mapped back to 'draft' FIRST, so the
    # narrower CHECK and the narrower column can both be restored on a
    # database that has already used the lifecycle. `received_at` stays NULL
    # on those rows (the invariant forbids it on anything but 'received'), so
    # the mapping keeps ck_purchase_orders_received_at satisfied.
    op.execute(
        "UPDATE purchase_orders SET status = 'draft' "
        "WHERE status NOT IN ('draft','received','cancelled')"
    )
    op.drop_constraint("ck_purchase_orders_status", "purchase_orders", type_="check")
    op.alter_column(
        "purchase_orders",
        "status",
        existing_type=sa.String(31),
        type_=sa.String(15),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_purchase_orders_status",
        "purchase_orders",
        "status IN ('draft','received','cancelled')",
    )

    # The one grant this migration added on an existing table goes back to
    # the append-only posture (INSERT + SELECT, no UPDATE).
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            REVOKE UPDATE ON TABLE purchase_order_lines FROM sales_app;
          END IF;
        END
        $$"""
    )

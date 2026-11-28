"""The apparel application gets its own schema.

The architecture says one database with a schema per application, and until this
revision every trading table lived in ``public`` next to the platform's own. That
is not a naming preference: it is the thing that lets a second sector arrive
without a shared product model. The ``platform`` schema already holds the control
plane; this moves the apparel trading tables into ``apparel`` beside it.

Why a plain move is safe here:

* the tables keep their data, indexes, constraints, grants and RLS policies -
  ``ALTER TABLE ... SET SCHEMA`` is a catalogue change, not a rewrite;
* foreign keys, views and policies are stored by object identity, so they follow
  the table instead of breaking;
* the application resolves unqualified names through ``search_path``, which this
  revision sets on the application role as ``apparel, platform, public``. The
  database-level default is set by ops for the same reason, so a session that
  skips the role setting still finds its tables.

The move is written to be idempotent: a table already in ``apparel`` is skipped,
so this runs unchanged on a database where the split was applied by hand (this
production database) and on a fresh one built from migrations.

Scope is deliberately the trading modules only - catalog, inventory, purchasing,
pos, orders, customers, segments and customer accounts. Analytics, marketing,
conversations, AI and settings stay in ``public`` until their ownership is
settled, because moving a table whose owner is undecided would only move the
argument.
"""

from __future__ import annotations

from alembic import op

revision = "fe2026112801"
down_revision = "fe2026112708"
branch_labels = None
depends_on = None

#: The trading tables that belong to the apparel application.
APPAREL_TABLES: tuple[str, ...] = (
    "addresses",
    "brands",
    "categories",
    "customer_accounts",
    "customer_events",
    "customer_identities",
    "customer_ledger",
    "customers",
    "deposit_policies",
    "goods_receipt_lines",
    "goods_receipts",
    "identity_merge_candidates",
    "identity_merge_events",
    "inventory_balances",
    "inventory_channel_allocations",
    "inventory_cost_layers",
    "inventory_inspection_results",
    "inventory_landed_cost_lines",
    "inventory_landed_costs",
    "inventory_location_balances",
    "inventory_location_movements",
    "inventory_lots",
    "inventory_movements",
    "inventory_policies",
    "inventory_quality_inspections",
    "inventory_reconciliation_findings",
    "inventory_reservations",
    "inventory_serials",
    "inventory_transfer_lines",
    "inventory_transfer_receipt_lines",
    "inventory_transfer_receipts",
    "inventory_transfer_shipment_lines",
    "inventory_transfer_shipments",
    "inventory_transfers",
    "notes",
    "order_items",
    "order_payments",
    "order_status_history",
    "orders",
    "pos_cash_movements",
    "pos_daily_sales",
    "pos_held_carts",
    "pos_profile_users",
    "pos_profiles",
    "pos_receipts",
    "pos_registers",
    "pos_return_lines",
    "pos_session_floats",
    "pos_session_handovers",
    "pos_session_reconciliations",
    "pos_sessions",
    "product_bundle_lines",
    "product_bundles",
    "product_identifiers",
    "product_images",
    "product_option_values",
    "product_options",
    "product_prices",
    "product_variant_option_values",
    "product_variants",
    "products",
    "purchase_order_lines",
    "purchase_orders",
    "refunds",
    "reorder_suggestions",
    "segments",
    "shipments",
    "shop_colours",
    "shop_size_sets",
    "sku_counters",
    "source_of_truth_policies",
    "stocktake_assignments",
    "stocktake_lines",
    "stocktakes",
    "supplier_payments",
    "supplier_return_lines",
    "supplier_returns",
    "suppliers",
    "tags",
    "variant_cost_history",
    "variant_costs",
    "variant_stock_settings",
    "variant_tracking_policies",
    "warehouse_locations",
    "warehouses",
)

APP_ROLE = "sales_app"


def _move(source: str, target: str) -> None:
    """Move every listed table from ``source`` to ``target``, skipping absent ones.

    ``to_regclass`` is the guard: it answers NULL instead of raising for a table
    that is already where it should be, which is what makes the revision safe to
    re-run.
    """
    for table in APPAREL_TABLES:
        op.execute(
            "DO $$ BEGIN "
            "IF to_regclass('" + source + "." + table + "') IS NOT NULL "
            "AND to_regclass('" + target + "." + table + "') IS NULL THEN "
            "EXECUTE 'ALTER TABLE " + source + "." + table + " SET SCHEMA " + target + "'; "
            "END IF; END $$;"
        )


def _best_effort(statement: str) -> None:
    """Run a privilege statement, but never fail the deploy over one.

    The role setting is what makes unqualified names resolve, so it matters; it is
    also already applied on a database that was split by hand. Where the migration
    runs as a role that may not grant or alter, the statement is skipped with a
    notice instead of aborting a container start - the tables still move, and ops
    sets the default out of band.
    """
    op.execute(
        "DO $$ BEGIN "
        + statement
        + " EXCEPTION WHEN insufficient_privilege THEN RAISE NOTICE 'skipped: "
        + statement.replace("'", "''")
        + "'; END $$;"
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS apparel")
    _best_effort("GRANT USAGE ON SCHEMA apparel TO " + APP_ROLE + ";")
    _best_effort("ALTER ROLE " + APP_ROLE + " SET search_path TO apparel, platform, public;")
    _move("public", "apparel")


def downgrade() -> None:
    _move("apparel", "public")

"""product option graph — relational Options/OptionValues (Commerce Core §179).

Replaces the unqueryable JSONB-only variant options (gap CC2): a variant now
has at most one value per option, enforced by UNIQUE (tenant, variant, option)
on the link table. The variant's JSONB stays as the denormalized read model —
CatalogService writes both in the same transaction.

The backfill derives the graph from the existing JSONB blobs; it is idempotent
(ON CONFLICT DO NOTHING) so a rerun can never double-create rows.

RLS follows the a1b2c3d4e5f6 pattern — tenant_isolation policies plus grants
guarded by a sales_app role-exists DO block.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "fd2026100403"
down_revision: str | None = "fd2026100402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_TABLES = ("product_options", "product_option_values", "product_variant_option_values")


def _tenant_table(name: str) -> None:
    op.create_table(
        name,
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
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        f"fk_{name}_workspace_id", name, "workspaces", ["workspace_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        f"fk_{name}_location_id", name, "locations", ["location_id"], ["id"],
        ondelete="SET NULL",
    )


def upgrade() -> None:
    _tenant_table("product_options")
    op.add_column(
        "product_options",
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.add_column("product_options", sa.Column("name", sa.String(63), nullable=False))
    op.create_unique_constraint(
        "uq_product_options_tenant_product_name",
        "product_options",
        ["tenant_id", "product_id", "name"],
    )
    op.create_index(
        "ix_product_options_tenant_product",
        "product_options",
        ["tenant_id", "product_id"],
    )

    _tenant_table("product_option_values")
    op.add_column(
        "product_option_values",
        sa.Column(
            "option_id",
            sa.Uuid(),
            sa.ForeignKey("product_options.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.add_column(
        "product_option_values", sa.Column("value", sa.String(127), nullable=False)
    )
    op.create_unique_constraint(
        "uq_product_option_values_tenant_option_value",
        "product_option_values",
        ["tenant_id", "option_id", "value"],
    )

    _tenant_table("product_variant_option_values")
    op.add_column(
        "product_variant_option_values",
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.add_column(
        "product_variant_option_values",
        sa.Column(
            "option_id",
            sa.Uuid(),
            sa.ForeignKey("product_options.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.add_column(
        "product_variant_option_values",
        sa.Column(
            "option_value_id",
            sa.Uuid(),
            sa.ForeignKey("product_option_values.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    # A variant carries at most one value per option — size=M and size=L on one
    # sellable unit is a catalog defect, not a preference.
    op.create_unique_constraint(
        "uq_product_variant_option_values_tenant_variant_option",
        "product_variant_option_values",
        ["tenant_id", "variant_id", "option_id"],
    )
    op.create_index(
        "ix_product_variant_option_values_value",
        "product_variant_option_values",
        ["tenant_id", "option_value_id"],
    )

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
              product_options, product_option_values, product_variant_option_values
              TO sales_app;
          END IF;
        END
        $$"""
    )

    # Backfill: derive the graph from the JSONB the variants already carry.
    op.execute(
        """DO $$
        DECLARE
          v record;
          k text;
          val text;
          v_option uuid;
          v_value uuid;
        BEGIN
          FOR v IN
            SELECT id, tenant_id, product_id, option_values
            FROM product_variants
            WHERE option_values IS NOT NULL AND option_values <> '{}'::jsonb
          LOOP
            FOR k, val IN SELECT * FROM jsonb_each_text(v.option_values)
            LOOP
              SELECT id INTO v_option FROM product_options
                WHERE tenant_id = v.tenant_id
                  AND product_id = v.product_id
                  AND name = k;
              IF v_option IS NULL THEN
                INSERT INTO product_options (id, tenant_id, product_id, name)
                VALUES (gen_random_uuid(), v.tenant_id, v.product_id, k)
                RETURNING id INTO v_option;
              END IF;
              SELECT id INTO v_value FROM product_option_values
                WHERE tenant_id = v.tenant_id
                  AND option_id = v_option
                  AND value = val;
              IF v_value IS NULL THEN
                INSERT INTO product_option_values (id, tenant_id, option_id, value)
                VALUES (gen_random_uuid(), v.tenant_id, v_option, val)
                RETURNING id INTO v_value;
              END IF;
              INSERT INTO product_variant_option_values
                (id, tenant_id, variant_id, option_id, option_value_id)
              VALUES (gen_random_uuid(), v.tenant_id, v.id, v_option, v_value)
              ON CONFLICT (tenant_id, variant_id, option_id) DO NOTHING;
            END LOOP;
          END LOOP;
        END
        $$"""
    )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)

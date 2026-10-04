"""product_images.variant_id — media binds to a sellable unit (§179, gap CC3).

A color-accurate shot belongs to the variant, not just the product. Nullable:
a product-level image keeps NULL. SET NULL so deleting a variant never
deletes the product's gallery.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "fd2026100404"
down_revision: str | None = "fd2026100403"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_images", sa.Column("variant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_product_images_variant_id",
        "product_images",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_product_images_tenant_variant",
        "product_images",
        ["tenant_id", "variant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_images_tenant_variant", table_name="product_images")
    op.drop_constraint(
        "fk_product_images_variant_id", "product_images", type_="foreignkey"
    )
    op.drop_column("product_images", "variant_id")

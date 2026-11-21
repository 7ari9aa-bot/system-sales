"""a product may carry its fabric (cotton, linen, polyester...).

Revision ID: fe2026112015
Revises: fe2026112014
Create Date: 2026-11-21 13:00:00.000000

Additive and inert: one nullable column and one partial index. Nothing reads the column unless a
caller sets or filters by it, so every existing product and every shop that does not record a
fabric behaves exactly as before. The products table already carries forced row level security
with the tenant_isolation policy, which a new column inherits, so no policy is added here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112015"
down_revision: str | None = "fe2026112014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("material", sa.String(60), nullable=True))
    op.create_index(
        "ix_products_tenant_material",
        "products",
        ["tenant_id", "material"],
        postgresql_where=sa.text("material IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_products_tenant_material", table_name="products")
    op.drop_column("products", "material")

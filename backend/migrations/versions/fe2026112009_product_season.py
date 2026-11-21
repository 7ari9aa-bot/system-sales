"""a product may carry a season label (SS26, AW26...).

Revision ID: fe2026112009
Revises: fe2026112008
Create Date: 2026-11-20 16:00:00.000000

Additive and inert: one nullable column and one partial index. Nothing reads the column unless a
caller sets or filters by it, so every existing product and every shop that is not seasonal
behaves exactly as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112009"
down_revision: str | None = "fe2026112008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("season", sa.String(40), nullable=True))
    op.create_index(
        "ix_products_tenant_season",
        "products",
        ["tenant_id", "season"],
        postgresql_where=sa.text("season IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_products_tenant_season", table_name="products")
    op.drop_column("products", "season")

"""pg_trgm for the customer catalog search — near-match across spelling.

Revision ID: fe2026101714
Revises: fe2026101713
Create Date: 2026-10-19 00:00:00.000000

Egyptian customers type "تيشرت"; catalogs say "تيشيرت" — a one-letter
mid-word insertion that prefix, substring and article-stripping arms
structurally cannot bridge. pg_trgm's similarity operator can, at a
loosened threshold (the query sets 0.2 transaction-locally: Arabic
trigram overlap across a one-letter insertion lands ~0.29, under the
0.3 default). The GIN trgm indexes keep the arms index-backed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026101714"
down_revision: str | None = "fe2026101713"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_title_trgm "
        "ON products USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_product_variants_title_trgm "
        "ON product_variants USING gin (title gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_product_variants_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_title_trgm")
    # The extension itself stays — dropping it could break anything else
    # that started using it while it was installed.

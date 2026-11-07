"""website site identity: category, whatsapp, social links, logo URL.

Revision ID: fe2026110506
Revises: fe2026110505
Create Date: 2026-11-07 14:00:00.000000

The purchase flow now collects the merchant's site identity (category,
WhatsApp number, social links) and the activation copies it onto the
Website, which carries it into the published snapshot — so the public
site renders the merchant's own WhatsApp button and social links from
day one, and the Website Dashboard can edit them later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "fe2026110506"
down_revision: str | None = "fe2026110505"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTITY_COLUMNS = [
    sa.Column("site_category", sa.String(50), nullable=True),
    sa.Column("whatsapp_number", sa.String(30), nullable=True),
    sa.Column("social_links", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column("logo_url", sa.Text(), nullable=True),
]

_TABLES = ("websites", "website_purchases", "website_published_sites")


def upgrade() -> None:
    for table in _TABLES:
        for col in _IDENTITY_COLUMNS:
            kwargs = dict(nullable=col.nullable)
            if col.server_default is not None:
                kwargs["server_default"] = col.server_default
            op.add_column(table, sa.Column(col.name, col.type, **kwargs))
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE websites TO sales_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE website_purchases TO sales_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE website_published_sites TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    for table in reversed(_TABLES):
        for col in reversed(_IDENTITY_COLUMNS):
            op.drop_column(table, col.name)
    op.drop_column("website_purchases", "logo_url")

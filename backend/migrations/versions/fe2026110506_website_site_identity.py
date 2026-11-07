"""website site identity: category, whatsapp, social links, logo URL.

Revision ID: fe2026110506
Revises: fe2026110505
Create Date: 2026-11-07 14:00:00.000000

The purchase flow now collects the merchant's site identity (category,
WhatsApp number, social links) and the activation copies it onto the
Website, which carries it into the published snapshot — so the public
site renders the merchant's own WhatsApp button and social links from
day one, and the Website Dashboard can edit them later.

The add_column calls are written out literally per table (no loops) so
the model/migration drift audit can see each column statically.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "fe2026110506"
down_revision: str | None = "fe2026110505"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("websites", sa.Column("site_category", sa.String(50), nullable=True))
    op.add_column("websites", sa.Column("whatsapp_number", sa.String(30), nullable=True))
    op.add_column(
        "websites",
        sa.Column("social_links", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column("websites", sa.Column("logo_url", sa.Text(), nullable=True))
    op.add_column("website_purchases", sa.Column("site_category", sa.String(50), nullable=True))
    op.add_column("website_purchases", sa.Column("whatsapp_number", sa.String(30), nullable=True))
    op.add_column(
        "website_purchases",
        sa.Column("social_links", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column("website_purchases", sa.Column("logo_url", sa.Text(), nullable=True))
    op.add_column("website_published_sites", sa.Column("site_category", sa.String(50), nullable=True))
    op.add_column("website_published_sites", sa.Column("whatsapp_number", sa.String(30), nullable=True))
    op.add_column(
        "website_published_sites",
        sa.Column("social_links", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column("website_published_sites", sa.Column("logo_url", sa.Text(), nullable=True))
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
    op.drop_column("website_published_sites", "logo_url")
    op.drop_column("website_published_sites", "social_links")
    op.drop_column("website_published_sites", "whatsapp_number")
    op.drop_column("website_published_sites", "site_category")
    op.drop_column("website_purchases", "logo_url")
    op.drop_column("website_purchases", "social_links")
    op.drop_column("website_purchases", "whatsapp_number")
    op.drop_column("website_purchases", "site_category")
    op.drop_column("websites", "logo_url")
    op.drop_column("websites", "social_links")
    op.drop_column("websites", "whatsapp_number")
    op.drop_column("websites", "site_category")

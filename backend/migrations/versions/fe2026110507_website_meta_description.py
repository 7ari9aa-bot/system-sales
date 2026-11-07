"""website meta_description: the Settings tab's site description.

Revision ID: fe2026110507
Revises: fe2026110506
Create Date: 2026-11-07 20:00:00.000000

The Website Dashboard's Settings tab collects a site description alongside
the other identity fields (category, WhatsApp, socials, logo). It lives on
the website row and on the public snapshot (head SEO tag for the published
site), so both tables get the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026110507"
down_revision: str | None = "fe2026110506"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("websites", sa.Column("meta_description", sa.Text(), nullable=True))
    op.add_column("website_published_sites", sa.Column("meta_description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("website_published_sites", "meta_description")
    op.drop_column("websites", "meta_description")

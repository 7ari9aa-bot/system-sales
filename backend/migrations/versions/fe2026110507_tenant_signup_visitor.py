"""tenants.signup_visitor_id: which website visitor became this merchant.

Revision ID: fe2026110507
Revises: fe2026110506
Create Date: 2026-11-07 19:30:00.000000

``visitor_events`` is platform-level telemetry with no tenant column and no RLS,
on purpose: an anonymous visitor belongs to nobody. The link between a visitor
and the merchant they became therefore lives on the *tenant* (which already
owns its origin), not on the telemetry table. The owner console joins the two
through ``visitor_events.visitor_id``.

The value is the client-generated random id the website tracker already keeps
in localStorage. It is optional (API signups, invitations and old accounts
have none) and is validated against the same pattern the telemetry ingest uses
before it is stored. Adding a nullable column rewrites nothing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026110507"
down_revision: str | None = "fe2026110506"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("signup_visitor_id", sa.String(64), nullable=True))
    # Partial: most tenants will never have one, and the only lookup is "which
    # tenant did this visitor become".
    op.create_index(
        "ix_tenants_signup_visitor_id",
        "tenants",
        ["signup_visitor_id"],
        postgresql_where=sa.text("signup_visitor_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_signup_visitor_id", table_name="tenants")
    op.drop_column("tenants", "signup_visitor_id")

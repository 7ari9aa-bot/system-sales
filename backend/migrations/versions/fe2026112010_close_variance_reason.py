"""a closed shift keeps why the drawer was off and who approved a large gap.

Revision ID: fe2026112010
Revises: fe2026112009
Create Date: 2026-11-21 04:00:00.000000

Additive and inert: three nullable columns on pos_sessions. Nothing reads them until a till that
counts its drawer closes with a variance, so every existing row and every till that does not count
is untouched. pos_sessions already has row-level security; adding columns does not change it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112010"
down_revision: str | None = "fe2026112009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pos_sessions", sa.Column("variance_reason", sa.String(500), nullable=True))
    op.add_column(
        "pos_sessions",
        sa.Column(
            "variance_approved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "pos_sessions",
        sa.Column("variance_approved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pos_sessions", "variance_approved_at")
    op.drop_column("pos_sessions", "variance_approved_by_user_id")
    op.drop_column("pos_sessions", "variance_reason")

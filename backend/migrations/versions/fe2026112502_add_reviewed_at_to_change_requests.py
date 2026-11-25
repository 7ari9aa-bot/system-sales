"""Add reviewed_at timestamp column to setting_change_requests.

The model declared reviewed_at as a UUID (a bug — it should be a timestamp),
and the original migration that created the table never included it. This
migration adds the column as a proper timezone-aware timestamp and is paired
with the model fix that changed the column type from UUID to TIMESTAMP.

Revision ID: fe2026112502
Revises: fe2026112501
Create Date: 2026-11-25 09:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision: str = "fe2026112502"
down_revision: str | None = "fe2026112501"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "setting_change_requests",
        op.Column("reviewed_at", TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("setting_change_requests", "reviewed_at")

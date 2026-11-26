"""A change request can propose a clear, not only a value.

Restoring a snapshot, or resetting a setting whose stored value is an override, needs to
propose "remove this override". That was expressed as ``{key: None}``, which the per-type
validator rejects for boolean, number and enum settings — so the approval path for a clear
could not even create its request, and ``restore_to_snapshot`` skipped the case entirely.

A clear is an operation, so it gets its own column: ``resets`` holds the keys the request
will remove, alongside ``changes`` which holds the values it will write.

Revision ID: fe2026112605
Revises: fe2026112604
Create Date: 2026-11-26 12:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112605"
down_revision: str | None = "fe2026112604"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "setting_change_requests",
        sa.Column(
            "resets",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("setting_change_requests", "resets")

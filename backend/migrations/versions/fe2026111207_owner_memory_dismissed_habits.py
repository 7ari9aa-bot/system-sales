"""owner_memory_settings.dismissed_habits: the suggestions an owner said no to.

Revision ID: fe2026111207
Revises: fe2026111206
Create Date: 2026-11-13 03:00:00.000000

A habit suggestion the owner dismissed must stay dismissed, on every device, or the same question
comes back each visit. The keys are the fixed period names (``last_7_days``...), never text the
owner or a customer wrote, so the column cannot carry words into the assistant. It lives on the
existing per-user settings row, which already sits under FORCE row level security.

The upgrade is additive and every existing row takes the default. The downgrade drops only this
column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111207"
down_revision: str | None = "fe2026111206"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "owner_memory_settings",
        sa.Column(
            "dismissed_habits",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_owner_memory_settings_dismissed_is_array",
        "owner_memory_settings",
        "jsonb_typeof(dismissed_habits) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_owner_memory_settings_dismissed_is_array", "owner_memory_settings", type_="check"
    )
    op.drop_column("owner_memory_settings", "dismissed_habits")

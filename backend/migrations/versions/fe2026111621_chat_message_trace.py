"""ai_chat_messages.trace: where an answer's time went and what the model thought.

Revision ID: fe2026111621
Revises: fe2026111220
Create Date: 2026-11-16 17:40:00.000000

The owner asked to see how long the assistant thinks, to open each step and read the model's own
thinking, and to know what took the time and why. Each model call and tool is timed where it
happens and appended here as start/end events, plus one summary with plain reasons.

NULL means not traced. Existing rows stay NULL: there is NO backfill, because timings that were
never measured cannot be invented. Nothing needs the column to be present: the writer never raises,
so a deploy that runs the code before the migration cannot break an answer.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111621"
down_revision: str | None = "fe2026111220"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_chat_messages",
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_chat_messages", "trace")

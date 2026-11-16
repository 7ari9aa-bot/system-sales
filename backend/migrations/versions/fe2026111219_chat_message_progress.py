"""ai_chat_messages.progress: the steps the assistant has really started on an answer.

Revision ID: fe2026111219
Revises: fe2026111218
Create Date: 2026-11-16 02:00:00.000000

While a question runs the owner saw three bouncing dots for about fifteen seconds. The assistant now
writes each step as it really begins ("reading your sales", "checking stock", "writing the reply")
so the page can show them. ``progress`` is a JSON list of those short Arabic lines, in order.

NULL is a meaningful value: no step was written. Every existing row, and every answer that came
from a memory command or a guard hold, stays NULL, so there is NO backfill and NO server default.
Inventing steps for answers that already happened would be the fake the feature exists to avoid.

Nothing reads this column except the message listing, and nothing needs it to be present, so a
deploy that runs the code before the migration cannot break an answer: the writer never raises.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111219"
down_revision: str | None = "fe2026111218"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_chat_messages",
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_chat_messages", "progress")

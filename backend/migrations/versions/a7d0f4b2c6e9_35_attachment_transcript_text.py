"""§35 — attachments gain transcript_text.

`VoiceService.transcribe` guarded its write with `hasattr(attachment,
"transcript_text")`, and the column did not exist: a successful transcription
reported "completed" while the text it paid for was dropped on the floor. The
transcript has to live on the row it describes — it is metadata on the voice
message, not a message of its own (§36) — so the agent context can be rebuilt
from it later.

`transcript_id` stays as the pointer for a dedicated transcripts table; that
table is not what closes §35, this column is.

Revision ID: a7d0f4b2c6e9
Revises: f6c9e3a1b5d8
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d0f4b2c6e9"
down_revision: str | None = "f6c9e3a1b5d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("transcript_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "transcript_text")

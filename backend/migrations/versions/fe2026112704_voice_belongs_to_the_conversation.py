"""A voice session belongs to the conversation, it does not replace it.

The two voice tables were built as a durable control plane, but they pointed at nothing: a call
could not name the thread it was part of, a turn could not name the messages it became, and a
message could not say it was spoken. That left "same assistant, two ways to talk to it" as a
promise in the code rather than a fact in the schema — the transcript had nowhere to land and a
reconnect could not find the conversation it was resuming.

Nothing here creates a second conversation. ``ai_chat_threads``/``ai_chat_messages`` stay the
single record; these columns only let the voice rows point INTO it:

* ``voice_sessions.ai_chat_thread_id`` — the thread this call talks in (SET NULL, never CASCADE:
  deleting a thread must not erase the evidence that a paid call happened).
* ``voice_turns.user_message_id`` / ``assistant_message_id`` — the two messages the turn became.
* ``ai_chat_messages.input_modality`` / ``output_modality`` / ``voice_session_id`` /
  ``transcript_status`` — how the message arrived and how it was answered. The raw audio stays in
  media storage under its own retention and consent policy; the row keeps the reference, not the
  bytes.

Every column is nullable: the 165 existing text conversations and every already-closed call keep
working untouched, and a text message is simply a message with no voice session.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "fe2026112704"
down_revision = "fe2026112703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "voice_sessions",
        sa.Column("ai_chat_thread_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_voice_sessions_ai_chat_thread_id",
        "voice_sessions",
        "ai_chat_threads",
        ["ai_chat_thread_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_voice_sessions_thread", "voice_sessions", ["tenant_id", "ai_chat_thread_id"]
    )

    # Written out rather than looped: the model/migration drift check reads this file with the
    # AST and only sees literal add_column arguments, so a loop hid these two columns from it and
    # the guard reported real columns as drift. The DDL is identical.
    op.add_column(
        "voice_turns",
        sa.Column("user_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_voice_turns_user_message_id",
        "voice_turns",
        "ai_chat_messages",
        ["user_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "voice_turns",
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_voice_turns_assistant_message_id",
        "voice_turns",
        "ai_chat_messages",
        ["assistant_message_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("ai_chat_messages", sa.Column("input_modality", sa.String(16), nullable=True))
    op.add_column("ai_chat_messages", sa.Column("output_modality", sa.String(16), nullable=True))
    op.add_column(
        "ai_chat_messages",
        sa.Column("voice_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("ai_chat_messages", sa.Column("transcript_status", sa.String(15), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_chat_messages", "transcript_status")
    op.drop_column("ai_chat_messages", "voice_session_id")
    op.drop_column("ai_chat_messages", "output_modality")
    op.drop_column("ai_chat_messages", "input_modality")

    for column in ("assistant_message_id", "user_message_id"):
        op.drop_constraint(f"fk_voice_turns_{column}", "voice_turns", type_="foreignkey")
        op.drop_column("voice_turns", column)

    op.drop_index("ix_voice_sessions_thread", table_name="voice_sessions")
    op.drop_constraint("fk_voice_sessions_ai_chat_thread_id", "voice_sessions", type_="foreignkey")
    op.drop_column("voice_sessions", "ai_chat_thread_id")

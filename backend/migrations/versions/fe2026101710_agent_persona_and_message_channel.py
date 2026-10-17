"""Two-prompt agents (base + persona) and the per-message channel source.

Two console-facing primitives the owner dashboard will wire:

* ``agents.persona_prompt`` / ``agent_versions.persona_prompt`` — the store's
  persona (agent name, tone, store name), merchant-owned. The BASE prompt
  (canonical instructions and prohibitions) stays in ``system_prompt``; the
  runtime composes base first, persona last, so editing the store's voice can
  never touch the rules.
* ``messages.channel`` — the SOURCE of each message (whatsapp / instagram /
  messenger / telegram / webchat), stamped server-side from the conversation
  by add_message. Backfilled once from the conversation so per-channel
  message analytics work over history; new rows are always stamped.

Revision ID: fe2026101710
Revises: fe2026101701
Create Date: 2026-10-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026101710"
down_revision: str | None = "fe2026101701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("persona_prompt", sa.Text(), nullable=True))
    op.add_column("agent_versions", sa.Column("persona_prompt", sa.Text(), nullable=True))

    op.add_column("messages", sa.Column("channel", sa.String(31), nullable=True))
    # One-time backfill: history was channel-less per message; the conversation
    # is the authoritative source it was recorded under.
    op.execute(
        "UPDATE messages SET channel = conversations.channel "
        "FROM conversations WHERE conversations.id = messages.conversation_id "
        "AND messages.channel IS NULL"
    )
    op.create_index(
        "ix_messages_tenant_channel_created",
        "messages",
        ["tenant_id", "channel", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_tenant_channel_created", table_name="messages")
    op.drop_column("messages", "channel")
    op.drop_column("agent_versions", "persona_prompt")
    op.drop_column("agents", "persona_prompt")

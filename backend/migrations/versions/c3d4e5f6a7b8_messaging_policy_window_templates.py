"""messaging policy: 24h customer-service window + template provenance

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-19

Closes spec §30-31 (the last mile that makes the product commercially usable).

Before this, nothing in the system knew that WhatsApp/Messenger/Instagram only
allow a FREE-FORM reply inside a 24-hour customer-service window — every
outbound message was treated as sendable at any time, so replies outside the
window would be silently rejected by the provider (or, worse, a human/AI would
believe the customer had been answered).

- conversations.last_customer_message_at is the anchor for that window. It is
  distinct from last_message_at, which also moves on OUTBOUND messages and
  therefore cannot be used to decide anything about the window.
- conversations.messaging_policy_state records the conversation's standing
  (§30) so the UI and the policy engine agree.
- messages.template_name / template_vars record that an outbound message was
  sent AS an approved template, so the decision is auditable and the worker can
  actually deliver it (it previously never passed a template to the adapter).

All four are additive and nullable/defaulted, so the change is safe on a live
database and needs no backfill beyond the window anchor.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("last_customer_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "messaging_policy_state",
            sa.String(length=31),
            nullable=False,
            server_default="open",
        ),
    )
    op.add_column(
        "messages", sa.Column("template_name", sa.String(length=127), nullable=True)
    )
    op.add_column(
        "messages",
        sa.Column(
            "template_vars",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    # Backfill the window anchor from the inbound history we already have.
    # Runs as the migration role (postgres/BYPASSRLS) so RLS does not apply.
    op.execute(
        """
        UPDATE conversations c
           SET last_customer_message_at = sub.last_inbound
          FROM (
                SELECT conversation_id, max(created_at) AS last_inbound
                  FROM messages
                 WHERE direction = 'inbound'
                 GROUP BY conversation_id
               ) sub
         WHERE sub.conversation_id = c.id
        """
    )


def downgrade() -> None:
    op.drop_column("messages", "template_vars")
    op.drop_column("messages", "template_name")
    op.drop_column("conversations", "messaging_policy_state")
    op.drop_column("conversations", "last_customer_message_at")

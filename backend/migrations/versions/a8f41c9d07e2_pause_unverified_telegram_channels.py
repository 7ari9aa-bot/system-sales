"""pause legacy Telegram channels until each bot identity is verified

Revision ID: a8f41c9d07e2
Revises: fbc2a817d901
Create Date: 2026-10-02 19:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a8f41c9d07e2"
down_revision: str | None = "fbc2a817d901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Previous clients stored a random routing key but no Telegram bot ID.
    # Pause these rows until their owner verifies the saved bot token. Without
    # this, the same Telegram bot could be connected to a second workspace and
    # its single Bot API webhook would silently retarget incoming messages.
    op.execute(
        """
        UPDATE public.integrations
           SET status = 'reauth_required'
         WHERE provider = 'telegram'
           AND kind = 'channel'
           AND status IN ('active', 'connected')
           AND config->>'bot_id' IS NULL
        """
    )


def downgrade() -> None:
    # Deliberately keep the fail-closed status: restoring an unverified bot to
    # active could reintroduce cross-workspace webhook routing.
    pass

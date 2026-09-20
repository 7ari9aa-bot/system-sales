"""notifications.channel needs the server default the model declares

The model declares::

    channel: Mapped[str] = mapped_column(String(15), server_default="inapp")

but the table was created as ``channel VARCHAR(15) NOT NULL`` with **no**
default (0b79f7470c1a), and e1f2a3b4c5d6 only added the newer in-app columns.
SQLAlchemy trusts a declared server_default and omits the column from the
INSERT, so every ``NotificationService.create()`` call died with::

    NotNullViolationError: null value in column "channel"

Setting the default makes the database match the model, which is the declared
source of truth. Callers that pass a channel explicitly (the outbound delivery
path in platform/service.py) are unaffected.
"""
from __future__ import annotations

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: one statement per op.execute() — asyncpg's extended-query protocol
    # rejects multiple commands in a single execute().
    op.execute("ALTER TABLE notifications ALTER COLUMN channel SET DEFAULT 'inapp'")


def downgrade() -> None:
    op.execute("ALTER TABLE notifications ALTER COLUMN channel DROP DEFAULT")

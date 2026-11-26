"""One notification-preference row per person, read in the person's own clock.

Revision ID: fe2026112607
Revises: fe2026112606

``notification_preferences`` was created (f9b0c1d2e3f4) as one row per person with
``in_app_enabled``/``email_enabled``/``push_enabled`` and a ``quiet_start``/``quiet_end``
window, and the dispatcher and the digest aggregator were written against exactly
that. A later migration (bb22cc33dd44) added a per-channel ``channel``/``enabled``
pair that nothing writes, and the SQLAlchemy model was pointed at THOSE columns —
so the aggregator, which reads ``quiet_start``, raised AttributeError the moment a
preference row existed. Nothing could create one, so the bug was invisible.

This migration finishes the correction the model makes:

- A unique index on ``(tenant_id, user_id)`` makes "one row per person" a fact the
  database enforces. The older unique constraint is keyed on ``channel``, whose
  values are NULL on these rows, and NULLs never collide.
- ``timezone`` is DROPPED. The window is a local time-of-day, and the local clock is
  already stored once, on ``users.timezone`` (fe2026112606), falling back to the
  workspace's zone. Keeping a second copy on every preference row is how the same
  person ends up with two clocks that disagree, and a quiet hour read in the wrong
  zone is a notification at 03:00.
- A CHECK makes the window all-or-nothing: a start with no end is not a window.

The unused per-channel columns are left in place (nullable, unwritten) rather than
dropped in the same breath: removing them is a separate, noisier change, and
nothing reads them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112611"
down_revision: str | None = "fe2026112610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per person. Duplicates could only exist if something had written the
    # per-channel rows, which nothing ever did; the index is created plainly and a
    # collision here would be a real finding, not something to paper over.
    op.create_index(
        "uq_notif_prefs_tenant_user_one",
        "notification_preferences",
        ["tenant_id", "user_id"],
        unique=True,
    )
    op.create_check_constraint(
        "ck_notif_prefs_quiet_window",
        "notification_preferences",
        "(quiet_start IS NULL) = (quiet_end IS NULL)",
    )
    op.drop_column("notification_preferences", "timezone")


def downgrade() -> None:
    op.add_column(
        "notification_preferences",
        sa.Column("timezone", sa.String(length=63), server_default="Africa/Cairo", nullable=False),
    )
    op.drop_constraint("ck_notif_prefs_quiet_window", "notification_preferences", type_="check")
    op.drop_index("uq_notif_prefs_tenant_user_one", table_name="notification_preferences")

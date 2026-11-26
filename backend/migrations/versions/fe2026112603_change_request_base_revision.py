"""Remember which revision a change request was proposed against.

An approval could land on top of a newer value: the request was created while
``pos.max_discount_pct`` was 10, someone else set it to 20, and approving the old
proposal wrote 15 over it. ``base_history_ids`` pins the revision each key stood at
when the request was submitted, so approval can close the request as ``stale``
instead of silently undoing the newer change.

Nullable: requests created before this migration have no pinned revision, and the
guard treats "no base" as "nothing to compare" rather than refusing them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "fe2026112603"
down_revision = "fe2026112602"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "setting_change_requests",
        sa.Column("base_history_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("setting_change_requests", "base_history_ids")

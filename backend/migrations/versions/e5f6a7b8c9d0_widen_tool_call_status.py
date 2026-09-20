"""widen tool_calls.status so the approval path can record its audit row

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-20

`tool_calls.status` is varchar(15) and documented as "ok | error | denied",
but the §135 gate writes "awaiting_approval" (17 chars) for a gated call. The
insert raised StringDataRightTruncationError, so the FIRST high-risk tool call
failed outright — the approval path could not even record what it had parked.

agent_runs.status was already widened to 31 for exactly this reason; this is
the same fix for the sibling column. Widening is safe and non-destructive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tool_calls", "status", type_=sa.String(length=31))


def downgrade() -> None:
    op.alter_column("tool_calls", "status", type_=sa.String(length=15))

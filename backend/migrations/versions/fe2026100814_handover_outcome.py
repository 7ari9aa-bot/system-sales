"""§150 outcome half for ai_handovers: who resolved it, when, with what result.

Revision ID: fe2026100814
Revises: fe2026100813
Create Date: 2026-10-10 04:20:00.000000

The handover queue recorded the intake but not the outcome: the resolve route
flipped ``status`` to ``resolved`` and left no trace of who did it, when, or
what the result was, so "handover outcome" could not be computed from the
table at all. Four nullable columns, no backfill — a row resolved before this
migration stays NULL, which is the honest answer ("we do not know who closed
it"), not a fabricated one.

No RLS work here: `ai_handovers` is tenant-scoped and already carries
ENABLE + FORCE + tenant_isolation from the sweep; new columns ride the
existing policy.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026100814"
down_revision: str | None = "fe2026100813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_handovers",
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "ai_handovers",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("ai_handovers", sa.Column("outcome", sa.String(31), nullable=True))
    op.add_column("ai_handovers", sa.Column("outcome_note", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_ai_handovers_resolved_by",
        "ai_handovers",
        "users",
        ["resolved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_ai_handovers_resolved_by", "ai_handovers", type_="foreignkey")
    op.drop_column("ai_handovers", "outcome_note")
    op.drop_column("ai_handovers", "outcome")
    op.drop_column("ai_handovers", "resolved_at")
    op.drop_column("ai_handovers", "resolved_by_user_id")

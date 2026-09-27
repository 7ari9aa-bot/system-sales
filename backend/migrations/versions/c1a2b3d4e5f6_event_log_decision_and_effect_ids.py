"""V12 Wave A — event_log expansion (decision_id and effect_id lineage)

Revision ID: c1a2b3d4e5f6
Revises: b7c9d2e4f6a1
Create Date: 2026-09-27

Expands event_log with two nullable UUID columns and indexes:
1. ``decision_id`` — links the event back to the Decision Plane proposal
2. ``effect_id``   — links the event to the downstream Effect Ledger row
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1a2b3d4e5f6"
down_revision: str | None = "b7c9d2e4f6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_log",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "event_log",
        sa.Column("effect_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_event_log_decision_id",
        "event_log",
        ["decision_id"],
        unique=False,
    )
    op.create_index(
        "ix_event_log_effect_id",
        "event_log",
        ["effect_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_event_log_effect_id", table_name="event_log")
    op.drop_index("ix_event_log_decision_id", table_name="event_log")
    op.drop_column("event_log", "effect_id")
    op.drop_column("event_log", "decision_id")

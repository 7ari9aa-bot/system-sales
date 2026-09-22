"""§158 — memories gain actor_id, status and invalidated_at.

A memory claim must own its full provenance (source, actor, created_at,
verified_at, confidence) and staff must be able to invalidate it. The first
governance pass (c5c6fc1ae836) added source/verified_at/confidence; actor and
lifecycle were still missing, so "who wrote this" had no answer and a wrong
claim could only be deleted (losing the audit trail) — never taken out of
service.

Rows already stored stay ``active`` with no actor (they predate attribution);
search_memory only surfaces active, unexpired rows, so invalidation and
retention take effect at recall time without touching old data.

Revision ID: e5b8d2f0a1c3
Revises: d4a7c1e9f0b5
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b8d2f0a1c3"
down_revision: str | None = "d4a7c1e9f0b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("actor_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "memories",
        sa.Column("status", sa.String(length=15), server_default="active", nullable=False),
    )
    op.add_column(
        "memories",
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        None, "memories", "users", ["actor_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(op.f("ix_memories_actor_id"), "memories", ["actor_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_memories_actor_id"), table_name="memories")
    op.drop_column("memories", "invalidated_at")
    op.drop_column("memories", "status")
    op.drop_column("memories", "actor_id")

"""add tool_calls.idempotency_key for AI tool-call idempotency (§15-16)

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-09-21

A retried agent run or replayed event that re-issues the same tool call
found no dedupe mechanism — the handler ran again, producing duplicate
side-effects (double orders, double tags, double tasks). §15-16 requires
an idempotency_key = f"{run_id}:{tool_call_id}" with a unique constraint
so the check-then-insert is atomic under concurrent retries.

This migration adds the nullable column and the unique index. Existing
rows get NULL (they predate the column) and are never matched — the
unique constraint treats NULLs as distinct, so there is no conflict.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "aa11bb22cc33"
down_revision: str | None = "f9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_calls",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "uq_tool_calls_tenant_idempotency",
        "tool_calls",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tool_calls_tenant_idempotency", table_name="tool_calls")
    op.drop_column("tool_calls", "idempotency_key")

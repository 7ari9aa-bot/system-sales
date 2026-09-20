"""approval consumption: an approved action may execute exactly once

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-20

Closes the §135 loop. An ApprovalRequest is the authorization for ONE action:
once the gated tool has actually run, the approval must not authorize it again.
Without this, resuming a suspended run re-runs the gate and the same approval
would silently authorize every subsequent attempt.

- approval_requests.consumed_at marks the moment the approved action executed.
- The lookup index supports the gate's hot query (is there an unconsumed
  APPROVED approval for this conversation + action?).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "approval_requests",
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_approvals_gate_lookup",
        "approval_requests",
        ["tenant_id", "conversation_id", "action", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_gate_lookup", table_name="approval_requests")
    op.drop_column("approval_requests", "consumed_at")

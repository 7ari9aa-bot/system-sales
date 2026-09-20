"""approval_requests.payload_hash — bind an approval to its exact arguments

Review G-02, the most dangerous logical gap in the audit.

`ApprovalService.find_granted` matched a granted approval on
`(tenant, conversation_id, action, status='APPROVED', consumed_at IS NULL)` —
the ACTION NAME only. The approved arguments were stored in `payload` but
nothing ever compared them, and the resume path then executed
`spec.handler(**kwargs)` with whatever arguments the run had computed *this*
time.

So a human could approve `create_order({variant_id: X, quantity: 1})` and the
resumed run could execute `create_order({variant_id: Y, quantity: 100})` against
the same approval. The human approved one action and a different one ran.

`payload_hash` is the SHA-256 of the canonicalised arguments the human saw. The
resume path recomputes it and refuses to match unless it is identical.

Existing rows get NULL. That is deliberate: SQL `= NULL` never matches, so every
approval predating this column fails closed and requires a fresh decision rather
than being honoured on the old, weaker check.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: one statement per op.execute() — asyncpg's extended-query protocol
    # rejects multiple commands in a single execute().
    op.add_column(
        "approval_requests",
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approval_requests", "payload_hash")

"""tenant lifecycle state machine (§48)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-20

`tenants` had only `is_active` — a two-state flag for a lifecycle with eight
states. There was no way to suspend for non-payment, no grace period and no
record of WHY a tenant was disabled, so the only lever was a blunt on/off
switch. This adds the detailed state plus the timestamps that make each phase
operable (when it was suspended, when grace ends, when deletion is scheduled).

All columns are additive and safe:
- `lifecycle_state` carries a server_default of 'active', so every existing row
  is valid the moment the column appears (existing tenants are live tenants).
- the timestamps and `status_reason` are nullable.

One statement per op.execute() — none here; op.add_column is used throughout,
so asyncpg's one-command-per-call rule is respected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "lifecycle_state",
            sa.String(length=31),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("grace_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("deletion_scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("status_reason", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "status_reason")
    op.drop_column("tenants", "deletion_scheduled_at")
    op.drop_column("tenants", "grace_ends_at")
    op.drop_column("tenants", "suspended_at")
    op.drop_column("tenants", "lifecycle_state")

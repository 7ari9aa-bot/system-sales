"""One physical call, one row: a unique provider call id per tenant.

Telephony providers retry webhooks, and `calls` had no uniqueness on `provider_call_id`, so the
same ring could be stored twice and billed twice. The handler already returns the existing call on
a repeat delivery; this index is what makes that hold when two deliveries race.

Rows that already share a provider id keep the earliest one and have the duplicate's column
cleared (the call row itself is kept: its legs and transcript still belong to a real conversation).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112702"
down_revision: str | None = "fe2026112701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_calls_tenant_provider_call_id"


def upgrade() -> None:
    op.execute(
        """
        UPDATE calls AS dup
           SET provider_call_id = NULL
          FROM calls AS keep
         WHERE dup.provider_call_id IS NOT NULL
           AND dup.provider_call_id = keep.provider_call_id
           AND dup.tenant_id = keep.tenant_id
           AND dup.id > keep.id
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX} ON calls (tenant_id, provider_call_id) "
        "WHERE provider_call_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")

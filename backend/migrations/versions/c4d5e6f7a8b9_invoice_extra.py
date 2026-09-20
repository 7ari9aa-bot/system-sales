"""invoices.extra — the frozen per-feature breakdown

`BillingSnapshotService` has always passed `extra=` to the Invoice constructor,
but the column never existed, so the service was not merely dead code — it was
never runnable and a TypeError was waiting for the first caller.

The column was first added to `b3c4d5e6f7a8`, which was WRONG: that revision had
already been applied to production by the time the omission was noticed, so
editing it in place would mean production never gets the column (Alembic sees
the revision stamped and does not re-run it) while a fresh database would. A
migration that has been applied anywhere is immutable — the fix goes in a new
revision, which is what this is.

`extra` is JSONB holding [{"feature": ..., "quantity": "12.00"}]. Quantities are
STRINGS: every Python JSON path decodes a number to an IEEE float, so a
Numeric(14,2) total would be silently degraded on the way into JSONB.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: one statement per op.execute()/op call — asyncpg's extended-query
    # protocol rejects multiple commands in a single execute().
    op.add_column(
        "invoices",
        sa.Column(
            "extra",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("invoices", "extra")

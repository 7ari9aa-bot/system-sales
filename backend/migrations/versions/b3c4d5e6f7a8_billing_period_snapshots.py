"""invoices.period_start / period_end + one snapshot per (tenant, period)

Spec §53–54: billing metering and immutable period snapshots.

`invoices` had no period columns at all — the period was buried in the `extra`
JSONB blob, where it can neither be constrained nor indexed. So the "immutable
snapshot" was only a convention: nothing prevented a second invoice being
written for a period that had already been closed, and nothing could look a
snapshot up by period without scanning and parsing JSON.

Two changes, both needed:

* `period_start` / `period_end` (DATE) — the period a row is the snapshot OF.
  DATE rather than TIMESTAMP because `usage_records.period_date` is a DATE, and
  a timestamp boundary would reintroduce the timezone bucketing bug the AI
  usage rollup already had to fix. Nullable: rows created before this migration
  have no period, and NULLs are distinct under a UNIQUE constraint, so legacy
  invoices never collide with each other.

* `uq_invoices_tenant_period` — the enforcement point for immutability. A
  service-level "is this period already closed?" check is a check-then-insert
  race; two concurrent closes both pass it and both insert. The database is the
  only thing that can serialise them, so the guarantee has to live here.

`tenant_id` leads the constraint so a tenant can later be sharded out with its
constraints intact (model_kit convention).

Plain `op.add_column` / `op.create_unique_constraint` — no raw SQL, nothing
Supabase-specific, so plain Postgres CI runs it unchanged.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("invoices", sa.Column("period_end", sa.Date(), nullable=True))
    # The frozen per-feature breakdown. The model's constructor has always
    # accepted `extra=`, but the column never existed — so the original
    # BillingSnapshotService was not just dead code, it was never runnable.
    op.add_column(
        "invoices",
        sa.Column(
            "extra",
            sa.dialects.postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_invoices_tenant_period",
        "invoices",
        ["tenant_id", "period_start", "period_end"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_invoices_tenant_period", "invoices", type_="unique")
    op.drop_column("invoices", "extra")
    op.drop_column("invoices", "period_end")
    op.drop_column("invoices", "period_start")

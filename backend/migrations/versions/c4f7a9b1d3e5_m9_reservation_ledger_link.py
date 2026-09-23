"""M9 — the reservation ledger linkage.

`reserve()`/`release()` moved `inventory_balances.reserved` and wrote NO ledger
row, so nothing explained the gap between on-hand and available: a `sale` row
was the only stock event the ledger recorded, and a hold that was never released
was invisible. Both operations now append a row (direction `hold`/`release`,
reason `reservation`/`reservation_release`), which raises two linkage problems
this migration solves:

* A hold is written BEFORE the durable reservation row exists — Orders takes the
  balance hold first so an out-of-stock cart aborts before an order row is
  inserted — so the pointer lives on the reservation (`hold_movement_id`), which
  is the mutable side. Deliberately no FK: the ledger is append-only, the
  reference is one-way, and an FK would make a variant/warehouse cascade able to
  refuse a ledger delete it has no business ordering.
* A release names the reservation it freed through the EXISTING polymorphic
  `reference_type`/`reference_id` pair, so the lookup that answers
  `GET /inventory/movements?reservation_id=...` needs a reference index — the
  table only had (tenant, variant, created) and (tenant, warehouse, created).

No CHECK constraint on `inventory_movements.reason`: the vocabulary is enforced
in the domain (`check_movement_shape`) and at the request model, which is this
schema's convention for enum-like columns, and a CHECK would make
`alembic upgrade head` depend on what free text legacy rows happen to hold.

Revision ID: c4f7a9b1d3e5
Revises: c9f2a6b1d4e8
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f7a9b1d3e5"
# Was b8e1c4d5a7f2, the head when M9 started; c9f2a6b1d4e8 landed on that same
# parent meanwhile, so this revision moves behind it rather than branching.
down_revision: str | None = "c9f2a6b1d4e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inventory_reservations",
        sa.Column("hold_movement_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        "ix_inventory_movements_reference",
        "inventory_movements",
        ["tenant_id", "reference_type", "reference_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_movements_reference", table_name="inventory_movements"
    )
    op.drop_column("inventory_reservations", "hold_movement_id")

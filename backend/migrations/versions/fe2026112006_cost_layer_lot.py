"""cost layers may name the batch they came from.

Revision ID: fe2026112006
Revises: fe2026112005
Create Date: 2026-11-20 14:00:00.000000

Additive and inert: ``lot_id`` is nullable and nothing reads it unless a shop turns the
``lot_expiry`` capability on, so every existing layer and every shop behaves exactly as before.
A batch's remaining quantity is the sum of its layers' ``remaining_quantity``: stock stays in one
place, the batch is only a label on it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112006"
down_revision: str | None = "fe2026112005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "inventory_cost_layers",
        sa.Column(
            "lot_id",
            sa.Uuid(),
            sa.ForeignKey("inventory_lots.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_inventory_cost_layers_lot",
        "inventory_cost_layers",
        ["tenant_id", "lot_id"],
        postgresql_where=sa.text("lot_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_cost_layers_lot", table_name="inventory_cost_layers")
    op.drop_column("inventory_cost_layers", "lot_id")

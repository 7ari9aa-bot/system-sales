"""inventory: record who made a stock movement.

Revision ID: fe2026102109
Revises: fe2026102108
Create Date: 2026-10-21 14:30:00.000000

The ledger said what moved but not who moved it, so a shortage could not be traced to a person.
`actor_user_id` is nullable: rows already on file keep NULL (nobody is invented for them), and
system-made rows (a worker, an import) have no person. It deliberately has no foreign key, like
`reference_id`: the ledger is append-only (the app role holds INSERT and SELECT only), and a FK
with ON DELETE SET NULL would rewrite history rows when a user is removed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026102109"
down_revision: str | None = "fe2026102108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("inventory_movements", sa.Column("actor_user_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_inv_mov_tenant_actor_created",
        "inventory_movements",
        ["tenant_id", "actor_user_id", "created_at"],
        postgresql_where=sa.text("actor_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_inv_mov_tenant_actor_created", table_name="inventory_movements")
    op.drop_column("inventory_movements", "actor_user_id")

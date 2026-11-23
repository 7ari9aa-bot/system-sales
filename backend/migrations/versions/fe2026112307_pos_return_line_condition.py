"""A returned garment carries its CONDITION, and the condition decides where it goes.

A returned dress is not automatically stock again. It may be sellable, waiting for inspection,
damaged, fit only for write-off, or on its way back to the supplier. Without that distinction
every return went back on the sellable shelf, so a torn dress counted as available and could be
sold again — and the shop's shrinkage numbers never showed it.

``condition`` is nullable for returns recorded before this column existed (they restocked, which
is what happened). New returns default to ``sellable``, and the API lets the cashier say otherwise
per line.

Revision ID: fe2026112307
Revises: fe2026112306
Create Date: 2026-11-23 23:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112307"
down_revision: str | None = "fe2026112306"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONDITIONS = ("sellable", "quarantine", "damaged", "writeoff", "supplier")


def upgrade() -> None:
    op.add_column(
        "pos_return_lines",
        sa.Column("condition", sa.String(15), nullable=True),
    )
    op.create_check_constraint(
        "ck_pos_return_lines_condition",
        "pos_return_lines",
        "condition IS NULL OR condition IN "
        + "(" + ", ".join(f"'{c}'" for c in CONDITIONS) + ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_pos_return_lines_condition", "pos_return_lines", type_="check")
    op.drop_column("pos_return_lines", "condition")

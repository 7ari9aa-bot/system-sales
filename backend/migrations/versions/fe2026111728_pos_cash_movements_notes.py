"""Add notes column to pos_cash_movements

Revision ID: fe2026111728
Revises: fe2026111627
Create Date: 2026-11-17 17:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "fe2026111728"
down_revision = "fe2026111627"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pos_cash_movements", sa.Column("notes", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("pos_cash_movements", "notes")

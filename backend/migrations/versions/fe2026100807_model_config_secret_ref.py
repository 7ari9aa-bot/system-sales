"""Add secret_ref to model_configs so API keys leave the JSONB column.

Revision ID: fe2026100807
Revises: fe2026100806
Create Date: 2026-10-09 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "fe2026100807"
down_revision: str | None = "fe2026100806"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_configs",
        sa.Column("secret_ref", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_model_configs_secret_ref",
        "model_configs",
        ["secret_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_model_configs_secret_ref", table_name="model_configs")
    op.drop_column("model_configs", "secret_ref")

"""Link agent_runs and ai_evaluations to the immutable agent_version.

Revision ID: fe2026100809
Revises: fe2026100808
Create Date: 2026-10-09 14:30:00.000000

Every run and evaluation now records which agent_version snapshot it used,
so replay or audit can reconstruct the exact prompt, model and tools.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "fe2026100809"
down_revision: str | None = "fe2026100808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("agent_version_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_agent_version_id",
        "agent_runs",
        "agent_versions",
        ["agent_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_runs_agent_version_id",
        "agent_runs",
        ["agent_version_id"],
        unique=False,
    )

    op.add_column(
        "ai_evaluations",
        sa.Column("agent_version_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ai_evaluations_agent_version_id",
        "ai_evaluations",
        "agent_versions",
        ["agent_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ai_evaluations_agent_version_id",
        "ai_evaluations",
        ["agent_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_evaluations_agent_version_id", table_name="ai_evaluations")
    op.drop_constraint("fk_ai_evaluations_agent_version_id", "ai_evaluations", type_="foreignkey")
    op.drop_column("ai_evaluations", "agent_version_id")

    op.drop_index("ix_agent_runs_agent_version_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_agent_version_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "agent_version_id")

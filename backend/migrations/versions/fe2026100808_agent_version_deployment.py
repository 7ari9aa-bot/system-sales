"""Add agent_versions and agent_deployments for immutable versioning and canary.

Revision ID: fe2026100808
Revises: fe2026100807
Create Date: 2026-10-09 14:15:00.000000

`agent_versions` stores an immutable snapshot of every published agent
configuration.  `agent_deployments` tracks which version is stable and which
is the canary candidate, along with the traffic split.  Together they let the
runtime deterministically choose a version and record exactly which snapshot
ran.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "fe2026100808"
down_revision: str | None = "fe2026100807"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("model", sa.String(127), nullable=True),
        sa.Column("temperature", sa.Numeric(3, 2), nullable=False, server_default=sa.text("0.7")),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("run_limits", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("tool_policy", JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(15), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "agent_id", "version", name="uq_agent_versions_tenant_agent_version"),
    )
    op.create_index("ix_agent_versions_tenant_agent", "agent_versions", ["tenant_id", "agent_id"])
    op.create_index("ix_agent_versions_status", "agent_versions", ["status"])

    op.create_table(
        "agent_deployments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("stable_version_id", UUID(as_uuid=True), sa.ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("candidate_version_id", UUID(as_uuid=True), sa.ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("canary_percent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(15), nullable=False, server_default=sa.text("'active'")),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "agent_id", name="uq_agent_deployments_tenant_agent"),
    )
    op.create_index("ix_agent_deployments_tenant_agent", "agent_deployments", ["tenant_id", "agent_id"])
    op.create_index("ix_agent_deployments_status", "agent_deployments", ["status"])


def downgrade() -> None:
    op.drop_table("agent_deployments")
    op.drop_table("agent_versions")

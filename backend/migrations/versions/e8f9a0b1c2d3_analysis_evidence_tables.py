"""Analysis evidence tables (spec §12.4) — the durable analysis record.

analysis_evidence: one immutable, content-hashed snapshot per published
analysis, chained to its agent run. analysis_findings: the graded claims
published with it. Both tenant-scoped with the standard RLS + guarded
grants (the a1b2c3d4e5f6 pattern), so CI and production stay valid in
either deploy order.

Revision ID: e8f9a0b1c2d3
Revises: c0a2026f0199
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "c0a2026f0199"
branch_labels = None
depends_on = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_TABLES = ("analysis_evidence", "analysis_findings")


def upgrade() -> None:
    op.create_table(
        "analysis_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(31), nullable=False),
        sa.Column("pack", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(127)),
        sa.Column("prompt_version", sa.String(31)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["agent_runs.id"], ondelete="SET NULL"
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_analysis_evidence_tenant_created",
        "analysis_evidence",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "analysis_findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_evidence.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("finding_type", sa.String(15), nullable=False),
        sa.Column("relationship", sa.String(31), nullable=False),
        sa.Column("confidence", sa.String(15), nullable=False),
        sa.Column("confidence_reasons", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("materiality", sa.Numeric(18, 8), server_default="0", nullable=False),
        sa.Column("evidence_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_analysis_findings_tenant_evidence",
        "analysis_findings",
        ["tenant_id", "evidence_id"],
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )

    op.create_foreign_key(
        None, "analysis_evidence", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        None, "analysis_evidence", "locations", ["location_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        None, "analysis_findings", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        None, "analysis_findings", "locations", ["location_id"], ["id"], ondelete="SET NULL"
    )
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
              analysis_evidence, analysis_findings
              TO sales_app;
          END IF;
        END
        $$;"""
    )


def downgrade() -> None:
    # Dropping the columns drops their FKs too on Postgres.
    op.drop_table("analysis_findings")
    op.drop_table("analysis_evidence")

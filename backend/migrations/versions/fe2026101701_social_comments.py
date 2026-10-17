"""Public social comments storage (facebook/instagram post comments).

A comment is public interaction data, NOT a conversation turn: it never
pages anyone and never triggers an AI reply. The table gives the merchant's
Sales Intelligence agent a durable, tenant-scoped read surface for what the
public says about the store — per platform, per post, with replies threaded
by parent_comment_id. Idempotent by (tenant, platform, comment_id), so a
provider redelivery edits instead of duplicating.

Revision ID: fe2026101701
Revises: fe2026101507
Create Date: 2026-10-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026101701"
down_revision: str | None = "fe2026101507"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _scope_fks(table: str) -> None:
    op.create_foreign_key(
        f"fk_{table}_workspace_id", table, "workspaces", ["workspace_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        f"fk_{table}_location_id", table, "locations", ["location_id"], ["id"],
        ondelete="SET NULL",
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def upgrade() -> None:
    op.create_table(
        "social_comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("platform", sa.String(31), nullable=False),
        sa.Column("comment_id", sa.String(127), nullable=False),
        sa.Column("post_id", sa.String(127), nullable=True),
        sa.Column("parent_comment_id", sa.String(127), nullable=True),
        sa.Column("author_ref", sa.String(127), nullable=True),
        sa.Column("author_name", sa.String(255), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("permalink", sa.Text(), nullable=True),
        sa.Column("like_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("commented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(15), server_default="visible", nullable=False),
        sa.Column(
            "customer_id",
            sa.Uuid(),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "platform", "comment_id",
            name="uq_social_comments_tenant_platform_comment",
        ),
        sa.CheckConstraint(
            "status IN ('visible', 'hidden', 'removed')",
            name="ck_social_comments_status",
        ),
    )
    _scope_fks("social_comments")
    op.create_index(
        "ix_social_comments_tenant_platform_time",
        "social_comments",
        ["tenant_id", "platform", "commented_at"],
    )
    op.create_index(
        "ix_social_comments_tenant_post",
        "social_comments",
        ["tenant_id", "post_id"],
    )

    _enable_rls("social_comments")
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE social_comments TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON social_comments")
    op.drop_index("ix_social_comments_tenant_post", table_name="social_comments")
    op.drop_index(
        "ix_social_comments_tenant_platform_time", table_name="social_comments"
    )
    op.drop_table("social_comments")

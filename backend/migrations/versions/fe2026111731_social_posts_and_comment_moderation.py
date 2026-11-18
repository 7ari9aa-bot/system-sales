"""Social posts and comment moderation (facebook/instagram).

`social_posts` stores the store's own posts (synced from the platform or
published from the inbox) so a comment always has its post beside it.
`social_comments` gains what moderation needs: who wrote it (the page itself
or the public), when the merchant replied, hid it, or answered it privately.

Revision ID: fe2026111731
Revises: fe2026111730
Create Date: 2026-11-18 02:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026111731"
down_revision: str | None = "fe2026111730"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column(
        "social_comments",
        sa.Column("is_page_reply", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("social_comments", sa.Column("replied_at", sa.DateTime(timezone=True)))
    op.add_column("social_comments", sa.Column("private_replied_at", sa.DateTime(timezone=True)))
    op.add_column("social_comments", sa.Column("hidden_at", sa.DateTime(timezone=True)))
    op.add_column("social_comments", sa.Column("moderated_by", sa.Uuid()))
    op.add_column("social_comments", sa.Column("username", sa.String(255)))

    op.create_table(
        "social_posts",
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
        sa.Column("post_id", sa.String(127), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("media_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        # IMAGE | VIDEO | CAROUSEL_ALBUM | REELS | STORY | TEXT
        sa.Column("media_type", sa.String(24), nullable=True),
        sa.Column("permalink", sa.Text(), nullable=True),
        sa.Column("like_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("comments_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("comments_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        # published here (draft | publishing | published | failed) vs only synced (NULL)
        sa.Column("publish_status", sa.String(15), nullable=True),
        sa.Column("publish_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "platform", "post_id", name="uq_social_posts_tenant_platform_post"
        ),
        sa.CheckConstraint(
            "publish_status IS NULL OR publish_status IN "
            "('draft', 'publishing', 'published', 'failed')",
            name="ck_social_posts_publish_status",
        ),
    )
    op.create_foreign_key(
        "fk_social_posts_workspace_id",
        "social_posts",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_social_posts_location_id",
        "social_posts",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_social_posts_tenant_platform_time",
        "social_posts",
        ["tenant_id", "platform", "posted_at"],
    )
    op.create_index(
        "ix_social_comments_tenant_post_status",
        "social_comments",
        ["tenant_id", "platform", "post_id", "status"],
    )

    op.execute("ALTER TABLE social_posts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE social_posts FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON social_posts")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON social_posts
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE social_posts TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.drop_index("ix_social_comments_tenant_post_status", table_name="social_comments")
    op.drop_table("social_posts")
    for col in (
        "username",
        "moderated_by",
        "hidden_at",
        "private_replied_at",
        "replied_at",
        "is_page_reply",
    ):
        op.drop_column("social_comments", col)

"""password reset tokens and durable email delivery state

Revision ID: fd2026100401
Revises: e8f9a0b1c2d3
Create Date: 2026-10-04 00:00:00.000000

Password reset is account-global: it runs before any tenant scope is bound.
The table therefore has no tenant_id/RLS policy, is inaccessible to Supabase's
public roles, and is granted only to the backend runtime role.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "fd2026100401"
down_revision: str | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id",
        "password_reset_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_user_requested",
        "password_reset_tokens",
        ["user_id", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_delivery_due",
        "password_reset_tokens",
        ["next_attempt_at", "lease_expires_at"],
        unique=False,
        postgresql_where=sa.text(
            "sent_at IS NULL AND consumed_at IS NULL AND delivery_failed_at IS NULL"
        ),
    )

    # Keep credentials out of PostgREST's public roles; only the direct backend
    # connection may read or mutate reset rows. CI can run before sales_app is
    # provisioned, so the grant is conditional.
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE
              ON TABLE public.password_reset_tokens TO sales_app;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON TABLE public.password_reset_tokens FROM anon;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON TABLE public.password_reset_tokens FROM authenticated;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            REVOKE SELECT, INSERT, UPDATE, DELETE
              ON TABLE public.password_reset_tokens FROM sales_app;
          END IF;
        END
        $$"""
    )
    op.drop_index("ix_password_reset_delivery_due", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_user_requested", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "auth_version")

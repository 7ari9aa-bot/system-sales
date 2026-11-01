"""Owner console: per-user channel access and anonymous visitor telemetry.

Revision ID: fe2026103001
Revises: fe2026102204
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026103001"
down_revision: str | None = "fe2026102204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# CI runs `alembic upgrade head` BEFORE scripts/provision.py creates the
# `sales_app` role, so a bare GRANT fails with UndefinedObjectError on a
# fresh database (the same reason f7a2c9d4e8b1 wraps its grants in a DO
# block). asyncpg allows exactly one statement per op.execute(), so each
# guarded grant is a single DO block.
_GRANT_SALES_APP = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        {grant}
    END IF;
END
$$;"""


def _grant_sales_app(grant: str) -> str:
    return _GRANT_SALES_APP.format(grant=grant)


def upgrade() -> None:
    op.create_table(
        "channel_user_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=63), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("can_send", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "user_id", "provider", name="uq_channel_user_access"),
    )
    op.create_index(
        "ix_channel_user_access_tenant_provider",
        "channel_user_access",
        ["tenant_id", "provider"],
    )
    op.execute("ALTER TABLE channel_user_access ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE channel_user_access FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON channel_user_access")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON channel_user_access
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(_grant_sales_app("GRANT SELECT, INSERT, UPDATE, DELETE ON channel_user_access TO sales_app"))

    op.create_table(
        "visitor_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("visitor_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=31), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("element", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_visitor_events_created", "visitor_events", ["created_at"])
    op.create_index("ix_visitor_events_visitor", "visitor_events", ["visitor_id", "created_at"])
    op.create_index("ix_visitor_events_type", "visitor_events", ["event_type", "created_at"])
    op.create_index("ix_visitor_events_path", "visitor_events", ["path", "created_at"])
    op.execute(_grant_sales_app("GRANT SELECT, INSERT ON visitor_events TO sales_app"))


def downgrade() -> None:
    op.drop_table("visitor_events")
    op.drop_table("channel_user_access")

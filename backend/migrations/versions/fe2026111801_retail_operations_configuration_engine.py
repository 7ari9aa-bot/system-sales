"""Retail Operations Configuration Engine: tenant_settings and tenant_settings_history.

Revision ID: fe2026111801
Revises: fe2026111730
Create Date: 2026-11-18 14:00:00.000000

Adds the centralized configuration engine tables with full tenant isolation (RLS)
and audit history for the FIHRIST retail operations settings.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111801"
down_revision: str | None = "fe2026111730"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # 1. tenant_settings (overrides table)
    op.create_table(
        "tenant_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("key", sa.String(127), nullable=False),
        sa.Column("scope", sa.String(31), server_default="tenant", nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "key",
            "scope",
            "scope_id",
            name="uq_tenant_settings_key_scope",
        ),
    )
    op.create_index(
        "ix_tenant_settings_tenant_key",
        "tenant_settings",
        ["tenant_id", "key"],
    )
    op.create_index(
        "ix_tenant_settings_tenant_scope",
        "tenant_settings",
        ["tenant_id", "scope", "scope_id"],
    )

    # 2. tenant_settings_history (append-only audit)
    op.create_table(
        "tenant_settings_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "setting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenant_settings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("key", sa.String(127), nullable=False),
        sa.Column("scope", sa.String(31), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("action", sa.String(15), server_default="set", nullable=False),
        sa.Column(
            "changed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("change_reason", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tenant_settings_history_tenant_key",
        "tenant_settings_history",
        ["tenant_id", "key", "created_at"],
    )
    op.create_index(
        "ix_tenant_settings_history_tenant_time",
        "tenant_settings_history",
        ["tenant_id", "created_at"],
    )

    # 3. Invariant 13: Tenant Isolation (RLS) on both tables
    for table in ("tenant_settings", "tenant_settings_history"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )


def downgrade() -> None:
    for table in ("tenant_settings_history", "tenant_settings"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("tenant_settings_history")
    op.drop_table("tenant_settings")

"""Setting change requests table for approval-gated settings (§28).

Change requests hold proposed setting changes that require a second person's
approval before they reach the runtime. The lifecycle is:
draft → submitted → validating → pending_approval → approved → applying → applied,
with terminal alternatives rejected / cancelled / failed / expired.

Revision ID: fe2026112501
Revises: fe2026112403
Create Date: 2026-11-25 07:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "fe2026112501"
down_revision: str | None = "fe2026112403"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "setting_change_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changes", JSONB, nullable=False),
        sa.Column("applied_changes", JSONB, nullable=True),
        sa.Column("status", sa.String(31), nullable=False, server_default="draft"),
        sa.Column("scope", sa.String(31), nullable=False, server_default="tenant"),
        sa.Column("scope_id", UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("review_note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_setting_change_requests_tenant_status", "setting_change_requests", ["tenant_id", "status"])
    op.create_index("ix_setting_change_requests_tenant_submitted", "setting_change_requests", ["tenant_id", "submitted_by"])

    # RLS: every tenant sees only its own change requests.
    op.execute("ALTER TABLE setting_change_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE setting_change_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY setting_change_requests_isolation ON setting_change_requests "
        "USING (tenant_id = current_setting('app.tenant_id')::uuid)"
    )


def downgrade() -> None:
    op.drop_table("setting_change_requests")

"""ai_chat_threads / ai_chat_messages — merchant-side sales-intelligence chat.

Revision ID: fe2026100816
Revises: fe2026101001
Create Date: 2026-10-10 23:45:00.000000

Spec §SI-chat: a persistent, multi-turn merchant conversation with the
sales_intelligence agent. Deliberately NOT the customer-messaging
`conversations` table — this is an analysis thread owned by the merchant
user who opened it. Both tables ship with ENABLE + FORCE + tenant_isolation
from day one (the fe2026100801/0810 lesson: a tenant-scoped table without
RLS from birth is a gap waiting for its incident).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "fe2026100816"
down_revision: str | None = "fe2026101001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "ai_chat_threads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(200), server_default="", nullable=False),
        sa.Column("status", sa.String(15), server_default="active", nullable=False),
        sa.Column("context", pg.JSONB(), server_default="{}", nullable=False),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("summary_through_seq", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
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
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_ai_chat_threads_tenant_user_updated",
        "ai_chat_threads",
        ["tenant_id", "created_by_user_id", "updated_at"],
    )
    op.create_index("ix_ai_chat_threads_workspace_id", "ai_chat_threads", ["workspace_id"])
    op.create_index("ix_ai_chat_threads_location_id", "ai_chat_threads", ["location_id"])

    op.create_table(
        "ai_chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.Uuid(),
            sa.ForeignKey("ai_chat_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(15), nullable=False),
        sa.Column("status", sa.String(15), server_default="pending", nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("structured_content", pg.JSONB(), nullable=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("analysis_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(63), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "thread_id", "sequence_no", name="uq_ai_chat_messages_thread_seq"
        ),
    )
    op.create_index(
        "uq_ai_chat_messages_thread_key",
        "ai_chat_messages",
        ["tenant_id", "thread_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_ai_chat_messages_thread_seq", "ai_chat_messages", ["thread_id", "sequence_no"]
    )

    for _tbl in ("ai_chat_threads", "ai_chat_messages"):
        op.execute(f"ALTER TABLE {_tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {_tbl} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_tbl}")
        op.execute(
            f"""CREATE POLICY tenant_isolation ON {_tbl}
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD})"""
        )
    # CI provisions sales_app after Alembic, while production already has it.
    # Guard the grants so both deploy orders remain valid (fe2026100813).
    op.execute(
        """DO $chat$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ai_chat_threads TO sales_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ai_chat_messages TO sales_app;
          END IF;
        END
        $chat$"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_chat_messages")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_chat_threads")
    op.drop_table("ai_chat_messages")
    op.drop_table("ai_chat_threads")

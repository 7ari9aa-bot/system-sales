"""jobs + saved_views (spec §84, §95)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-20

Two tenant-scoped tables the API needs and nothing created yet:

1. ``jobs`` — the user-facing record of a long-running operation (§84). It is
   deliberately NOT ``scheduled_jobs``: that table is the scheduler's internal
   wake-up list (``run_at``/``next_attempt_at``/``idempotency_key``), consumed
   by the worker loop to decide *when* to run something. This one carries what
   a UI shows and controls — ``progress``, ``result``, ``correlation_id``,
   ``actor_user_id`` — and is the surface retry/cancel act on. Publishing the
   scheduler's table as the public Job API would leak its retry machinery into
   the UI.

2. ``saved_views`` — a named list layout with a visibility (§95).

Both are tenant-scoped, so each gets the same RLS treatment as every other
tenant table: ENABLE + FORCE + a ``tenant_isolation`` policy keyed on the
``app.tenant_id`` GUC. RLS was applied to the tables that existed at the time,
so a table created afterwards would otherwise be unprotected.

One statement per ``op.execute()`` — asyncpg's extended-query protocol rejects
multiple commands in a single call, so each ALTER/CREATE POLICY is its own
execute.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _enable_rls(table: str) -> None:
    """ENABLE + FORCE + the standard tenant_isolation policy for one table."""
    op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON public.{table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON public.{table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=63), nullable=False),
        # allowed: queued | processing | completed | failed | retrying | cancelled
        sa.Column(
            "status", sa.String(length=15), nullable=False, server_default="queued"
        ),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_jobs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_jobs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jobs_tenant_status_created",
        "jobs",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index("ix_jobs_tenant_kind", "jobs", ["tenant_id", "kind"])

    op.create_table(
        "saved_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("entity", sa.String(length=63), nullable=False),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        # allowed: private | team | workspace
        sa.Column(
            "visibility", sa.String(length=15), nullable=False, server_default="private"
        ),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_saved_views_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_saved_views_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_saved_views_tenant_entity", "saved_views", ["tenant_id", "entity"]
    )

    # A table created after the RLS migration has no policy of its own.
    _enable_rls("jobs")
    _enable_rls("saved_views")


def downgrade() -> None:
    op.drop_index("ix_saved_views_tenant_entity", table_name="saved_views")
    op.drop_table("saved_views")
    op.drop_index("ix_jobs_tenant_kind", table_name="jobs")
    op.drop_index("ix_jobs_tenant_status_created", table_name="jobs")
    op.drop_table("jobs")

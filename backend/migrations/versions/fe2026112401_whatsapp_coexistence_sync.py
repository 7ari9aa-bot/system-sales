"""``whatsapp_sync_runs``: the contacts/history transfer a coexistence number is owed.

Coexistence moves the merchant's own data into FIHRIST — the WhatsApp Business app's contacts and
up to 180 days of chat history — and Meta allows each of those requests ONCE per connection, inside
24 hours of onboarding. Nothing durable recorded that, so a retried webhook, a restarted worker or
a second click could burn the only request the merchant gets, and there was nowhere to keep the
``request_id`` that every incoming chunk is attributed to.

One row per (tenant, number, sync kind, onboarding epoch): the epoch is stamped when the number
proved coexistence, so a re-linked number starts new runs while a retry in the same connection hits
the same row.

Revision ID: fe2026112401
Revises: fe2026112308
Create Date: 2026-11-24 03:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112401"
down_revision: str | None = "fe2026112308"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical tenant guard (same shape as c156cc156cc1 / provision.py): the NULLIF keeps an
# UNSET app.tenant_id from casting '' to uuid, so an unbound session matches ZERO rows.
_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "whatsapp_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phone_number_id", sa.String(length=32), nullable=False),
        sa.Column("waba_id", sa.String(length=32), nullable=True),
        sa.Column("sync_type", sa.String(length=31), nullable=False),
        sa.Column("onboarding_epoch", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=31), server_default="pending", nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "phases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("chunks_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("messages_stored", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "tenant_id",
            "phone_number_id",
            "sync_type",
            "onboarding_epoch",
            name="uq_whatsapp_sync_runs_tenant_number_type_epoch",
        ),
    )
    op.create_index(
        "ix_whatsapp_sync_runs_tenant_number",
        "whatsapp_sync_runs",
        ["tenant_id", "phone_number_id", "sync_type"],
    )
    op.create_index("ix_whatsapp_sync_runs_tenant_id", "whatsapp_sync_runs", ["tenant_id"])

    # Tenant isolation is defence in depth: the app scopes every query AND Postgres refuses
    # rows outside app.tenant_id. FORCE makes it hold for the table owner too, so a service
    # that forgets bind_tenant cannot read another shop's sync runs.
    op.execute("ALTER TABLE public.whatsapp_sync_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.whatsapp_sync_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'whatsapp_sync_runs' AND policyname = 'tenant_isolation'
            ) THEN
                CREATE POLICY tenant_isolation ON public.whatsapp_sync_runs
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD});
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.whatsapp_sync_runs")
    op.drop_index("ix_whatsapp_sync_runs_tenant_id", table_name="whatsapp_sync_runs")
    op.drop_index("ix_whatsapp_sync_runs_tenant_number", table_name="whatsapp_sync_runs")
    op.drop_table("whatsapp_sync_runs")

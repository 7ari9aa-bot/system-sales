"""``whatsapp_contact_tombstones``: a contact removal that outlives the contact.

Coexistence delivers the WhatsApp Business app's contacts through ``smb_app_state_sync``, which
carries the initial snapshot AND every later add/update/remove, in batches that arrive out of
order. A removal for a handle we had never stored was dropped, so the add it referred to — arriving
a second later — created a contact the merchant had already deleted.

One row per (tenant, number, handle) holding the latest ``removed_at``: an add older than that is
ignored, a newer add clears the row. Tenant scoped and RLS-forced like every other coexistence
table, because a removal is customer data from one shop only.

Revision ID: fe2026112402
Revises: fe2026112401
Create Date: 2026-11-24 06:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112402"
down_revision: str | None = "fe2026112401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "whatsapp_contact_tombstones",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phone_number_id", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=False),
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
            "external_id",
            name="uq_whatsapp_contact_tombstones_tenant_number_handle",
        ),
    )
    op.create_index(
        "ix_whatsapp_contact_tombstones_tenant_id",
        "whatsapp_contact_tombstones",
        ["tenant_id"],
    )

    op.execute("ALTER TABLE public.whatsapp_contact_tombstones ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.whatsapp_contact_tombstones FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'whatsapp_contact_tombstones'
                  AND policyname = 'tenant_isolation'
            ) THEN
                CREATE POLICY tenant_isolation ON public.whatsapp_contact_tombstones
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD});
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.whatsapp_contact_tombstones")
    op.drop_index(
        "ix_whatsapp_contact_tombstones_tenant_id", table_name="whatsapp_contact_tombstones"
    )
    op.drop_table("whatsapp_contact_tombstones")

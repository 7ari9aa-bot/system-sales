"""ETA e-receipts: delivery tracking, a notification ledger, and a callback key lookup.

* ``einvoice_documents`` learns how a receipt travels: the batch id, the authority's long id,
  the receipt it replaces (``reference_old_uuid``), attempt count and next retry time, plus the
  indexes the sender and the callbacks use. The status check gains ``cancelled`` (the authority
  can void a receipt; hiding that under another name would misreport the legal state).
* ``einvoice_devices.notification_key_hash`` holds the SHA-256 of the shared key the authority
  sends with each callback. Only the hash is stored.
* ``einvoice_notifications`` records every callback so a repeated delivery is recognised and
  answered without being applied twice. FORCE-RLS like the other e-invoice tables.
* ``resolve_eta_notification_device`` finds the store behind a callback key. The authority calls
  one URL before any store is bound, and the device table is FORCE-RLS, so the lookup is a
  SECURITY DEFINER function that returns only ids (never credentials) and answers nothing when
  the key is unknown, the same posture as ``resolve_whatsapp_waba_tenant``.

Revision ID: fe2026112011
Revises: fe2026112010
Create Date: 2026-11-20 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112011"
down_revision: str | None = "fe2026112010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_OLD_STATUS = (
    "status IN ('draft', 'signed', 'submitted', 'cleared', 'reported', 'rejected', 'failed')"
)
_NEW_STATUS = (
    "status IN ('draft', 'signed', 'submitted', 'cleared', 'reported', 'rejected', 'failed', "
    "'cancelled')"
)

_RESOLVE_FN = """
CREATE OR REPLACE FUNCTION public.resolve_eta_notification_device(p_key_hash text)
RETURNS TABLE (tenant_id uuid, device_id uuid, device_serial text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
    SELECT d.tenant_id, d.id, d.device_serial::text
      FROM public.einvoice_devices d
     WHERE p_key_hash IS NOT NULL
       AND length(p_key_hash) = 64
       AND d.notification_key_hash = p_key_hash
       AND d.provider_type = 'eta'
       AND d.status <> 'revoked'
$fn$
"""


def upgrade() -> None:
    # --- documents ---------------------------------------------------------------
    op.add_column("einvoice_documents", sa.Column("submission_uuid", sa.String(127)))
    op.add_column("einvoice_documents", sa.Column("authority_long_id", sa.String(255)))
    op.add_column("einvoice_documents", sa.Column("reference_old_uuid", sa.String(127)))
    op.add_column(
        "einvoice_documents",
        sa.Column("delivery_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("einvoice_documents", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_einvoice_documents_status", "einvoice_documents", type_="check")
    op.create_check_constraint("ck_einvoice_documents_status", "einvoice_documents", _NEW_STATUS)
    op.create_index(
        "ix_einvoice_docs_device_queue",
        "einvoice_documents",
        ["tenant_id", "device_id", "status", "issued_at"],
    )
    op.create_index(
        "ix_einvoice_docs_tenant_authority_uuid",
        "einvoice_documents",
        ["tenant_id", "authority_uuid"],
    )

    # --- devices -----------------------------------------------------------------
    op.add_column("einvoice_devices", sa.Column("notification_key_hash", sa.String(64)))
    op.create_index(
        "uq_einvoice_devices_notification_key",
        "einvoice_devices",
        ["notification_key_hash"],
        unique=True,
        postgresql_where=sa.text("notification_key_hash IS NOT NULL"),
    )

    # --- notification ledger -----------------------------------------------------
    op.create_table(
        "einvoice_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("einvoice_devices.id", ondelete="SET NULL"),
        ),
        sa.Column("kind", sa.String(15), nullable=False),
        sa.Column("delivery_id", sa.String(127), nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "kind", "delivery_id", name="uq_einvoice_notifications_delivery"
        ),
        sa.CheckConstraint("kind IN ('receipt', 'general')", name="ck_einvoice_notifications_kind"),
    )
    op.create_index("ix_einvoice_notifications_tenant_id", "einvoice_notifications", ["tenant_id"])
    op.execute("ALTER TABLE einvoice_notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE einvoice_notifications FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON einvoice_notifications
        USING (tenant_id = {_TENANT_GUARD})
        WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )

    # --- callback key -> store ---------------------------------------------------
    op.execute(_RESOLVE_FN)
    op.execute("REVOKE ALL ON FUNCTION public.resolve_eta_notification_device(text) FROM PUBLIC")
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                GRANT EXECUTE ON FUNCTION public.resolve_eta_notification_device(text)
                    TO sales_app;
            END IF;
        END $$"""
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.resolve_eta_notification_device(text)")
    op.drop_table("einvoice_notifications")
    op.drop_index("uq_einvoice_devices_notification_key", table_name="einvoice_devices")
    op.drop_column("einvoice_devices", "notification_key_hash")
    op.drop_index("ix_einvoice_docs_tenant_authority_uuid", table_name="einvoice_documents")
    op.drop_index("ix_einvoice_docs_device_queue", table_name="einvoice_documents")
    # A 'cancelled' row would violate the narrower check, so refuse silently losing that state.
    op.execute("UPDATE einvoice_documents SET status = 'rejected' WHERE status = 'cancelled'")
    op.drop_constraint("ck_einvoice_documents_status", "einvoice_documents", type_="check")
    op.create_check_constraint("ck_einvoice_documents_status", "einvoice_documents", _OLD_STATUS)
    for col in (
        "next_attempt_at",
        "delivery_attempts",
        "reference_old_uuid",
        "authority_long_id",
        "submission_uuid",
    ):
        op.drop_column("einvoice_documents", col)

"""Create einvoice_devices and einvoice_documents tables.

Revision ID: fe2026111625
Revises: fe2026111624
Create Date: 2026-11-17 00:45:00.000000

- einvoice_devices: POS/cashier fiscal registers tracking monotonic sequential
  numbering (ICV) and cryptographic Previous Invoice Hash (PIH) chains.
- einvoice_documents: Immutable audit trail for electronic invoices, simplified
  invoices (B2C receipts), return receipts, digital signatures, and QR codes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111625"
down_revision: str | None = "fe2026111624"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create einvoice_devices table
    op.create_table(
        "einvoice_devices",
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
        ),
        sa.Column("device_name", sa.String(length=127), nullable=False),
        sa.Column("device_serial", sa.String(length=127), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column(
            "provider_type", sa.String(length=31), server_default="sandbox", nullable=False
        ),
        sa.Column("status", sa.String(length=31), server_default="active", nullable=False),
        sa.Column("icv_counter", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_pih", sa.String(length=127), nullable=True),
        sa.Column(
            "credentials", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        sa.Column(
            "metadata_info", postgresql.JSONB(), server_default="{}", nullable=False
        ),
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
        sa.UniqueConstraint(
            "tenant_id", "device_serial", name="uq_einvoice_devices_tenant_serial"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'onboarding', 'suspended', 'revoked')",
            name="ck_einvoice_devices_status",
        ),
        sa.CheckConstraint("icv_counter >= 0", name="ck_einvoice_devices_icv_counter"),
    )
    op.create_index(
        "ix_einvoice_devices_tenant_id", "einvoice_devices", ["tenant_id"]
    )
    op.create_index(
        "ix_einvoice_devices_country_code", "einvoice_devices", ["country_code"]
    )

    # 2. Create einvoice_documents table
    op.create_table(
        "einvoice_documents",
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
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("einvoice_devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("provider_type", sa.String(length=31), nullable=False),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pos_receipts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("invoice_number", sa.String(length=63), nullable=False),
        sa.Column("document_type", sa.String(length=31), nullable=False),
        sa.Column("status", sa.String(length=31), server_default="draft", nullable=False),
        sa.Column("icv", sa.Integer(), server_default="1", nullable=False),
        sa.Column("invoice_hash", sa.String(length=127), nullable=False),
        sa.Column("pih", sa.String(length=127), nullable=False),
        sa.Column("qr_code", sa.Text(), nullable=True),
        sa.Column("cryptographic_stamp", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("authority_uuid", sa.String(length=127), nullable=True),
        sa.Column(
            "authority_response", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        sa.Column("errors", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "tenant_id", "invoice_number", name="uq_einvoice_documents_tenant_number"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'signed', 'submitted', 'cleared', 'reported', 'rejected', 'failed')",
            name="ck_einvoice_documents_status",
        ),
    )
    op.create_index(
        "ix_einvoice_docs_tenant_order", "einvoice_documents", ["tenant_id", "order_id"]
    )
    op.create_index(
        "ix_einvoice_docs_tenant_receipt",
        "einvoice_documents",
        ["tenant_id", "receipt_id"],
    )
    op.create_index(
        "ix_einvoice_docs_tenant_status",
        "einvoice_documents",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("einvoice_documents")
    op.drop_table("einvoice_devices")

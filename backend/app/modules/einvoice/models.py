"""E-invoicing models — devices, certificates, cryptographic counters, and documents.

Supports:
- ZATCA (Saudi Arabia): UBL 2.1, ECDSA signing, PIH hash chain, ICV monotonic counter.
- ETA (Egypt): E-Receipt (B2C) for POS and E-Invoice (B2B), return receipts (R).
- Peppol (UAE): PINT AE XML transmission via accredited ASP.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    IdMixin,
    TenantMixin,
    TimestampMixin,
)


class EInvoiceDevice(TenantMixin, TimestampMixin, IdMixin, Base):
    """A registered POS till or e-invoicing billing unit for a tenant.

    Tracks monotonic sequential numbering (ICV) and the cryptographic hash chain
    (Previous Invoice Hash - PIH) mandated by fiscal authorities (e.g. ZATCA).
    """

    __tablename__ = "einvoice_devices"

    device_name: Mapped[str] = mapped_column(String(127))
    device_serial: Mapped[str] = mapped_column(String(127))
    country_code: Mapped[str] = mapped_column(String(2), index=True)
    # provider_type: zatca | eta | peppol_ae | sandbox
    provider_type: Mapped[str] = mapped_column(
        String(31), default="sandbox", server_default="sandbox"
    )
    # status: active | onboarding | suspended | revoked
    status: Mapped[str] = mapped_column(String(31), default="active", server_default="active")
    # Monotonically increasing sequential invoice counter for this device
    icv_counter: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Previous Invoice Hash (PIH) in Base64 (initial invoice uses sha256('0'))
    last_pih: Mapped[str | None] = mapped_column(String(127), nullable=True)
    # Encrypted credentials / CSID / tokens / certificate metadata
    credentials: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    metadata_info: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # SHA-256 (hex) of the shared key the authority sends in ``Authorization: ApiKey``. Only the
    # hash is stored: the plain key lives with the merchant's onboarding, never in this row.
    # Unique so a callback resolves to exactly one store (NULL = no callbacks configured).
    notification_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "device_serial", name="uq_einvoice_devices_tenant_serial"),
        Index(
            "uq_einvoice_devices_notification_key",
            "notification_key_hash",
            unique=True,
            postgresql_where="notification_key_hash IS NOT NULL",
        ),
        CheckConstraint(
            "status IN ('active', 'onboarding', 'suspended', 'revoked')",
            name="ck_einvoice_devices_status",
        ),
        CheckConstraint("icv_counter >= 0", name="ck_einvoice_devices_icv_counter"),
    )


class EInvoiceDocument(TenantMixin, TimestampMixin, IdMixin, Base):
    """An issued electronic invoice, simplified tax invoice, or e-receipt record."""

    __tablename__ = "einvoice_documents"

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("einvoice_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    country_code: Mapped[str] = mapped_column(String(2), index=True)
    provider_type: Mapped[str] = mapped_column(String(31))
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pos_receipts.id", ondelete="SET NULL"),
        nullable=True,
    )
    invoice_number: Mapped[str] = mapped_column(String(63))
    # document_type: tax_invoice | simplified | credit_note | debit_note | return_receipt
    document_type: Mapped[str] = mapped_column(String(31))
    # status: draft | signed | submitted | cleared | reported | rejected | failed | cancelled
    # ETA: signed=stored, not yet delivered | submitted=202 accepted | reported=validated
    #       rejected=invalid | failed=delivery trouble, retryable | cancelled=voided
    status: Mapped[str] = mapped_column(String(31), default="draft", server_default="draft")
    # Invoice Counter Value for this specific document
    icv: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Cryptographic hash of the canonicalized document (SHA-256 Base64)
    invoice_hash: Mapped[str] = mapped_column(String(127))
    # Previous Invoice Hash linked into the chain
    pih: Mapped[str] = mapped_column(String(127))
    # QR Code (e.g. TLV Base64 for ZATCA or verification URL for ETA)
    qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Digital signature / cryptographic stamp
    cryptographic_stamp: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full XML or JSON payload as submitted to the authority
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    # UUID or clearance tracking ID returned by the tax authority (ZATCA, ETA, Peppol)
    authority_uuid: Mapped[str | None] = mapped_column(String(127), nullable=True)
    authority_response: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    errors: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # ETA delivery tracking (unused by the other providers; defaults keep them unaffected).
    # The authority's id for the batch this receipt travelled in (for status follow-up).
    submission_uuid: Mapped[str | None] = mapped_column(String(127), nullable=True)
    # The authority's permanent id for an accepted receipt (``longId``).
    authority_long_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set when this receipt replaces a rejected one (the rejected receipt's uuid).
    reference_old_uuid: Mapped[str | None] = mapped_column(String(127), nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_einvoice_documents_tenant_number"),
        CheckConstraint(
            "status IN ('draft', 'signed', 'submitted', 'cleared', "
            "'reported', 'rejected', 'failed', 'cancelled')",
            name="ck_einvoice_documents_status",
        ),
        Index("ix_einvoice_docs_tenant_order", "tenant_id", "order_id"),
        Index("ix_einvoice_docs_tenant_receipt", "tenant_id", "receipt_id"),
        Index("ix_einvoice_docs_tenant_status", "tenant_id", "status"),
        # the sender walks one device's undelivered receipts oldest first
        Index("ix_einvoice_docs_device_queue", "tenant_id", "device_id", "status", "issued_at"),
        # callbacks find a receipt by the authority uuid
        Index("ix_einvoice_docs_tenant_authority_uuid", "tenant_id", "authority_uuid"),
    )


class EInvoiceNotification(TenantMixin, TimestampMixin, IdMixin, Base):
    """One notification the authority pushed to us, kept for idempotency and audit.

    The authority may deliver the same notification more than once and requires a 200 each time,
    so ``(tenant_id, delivery_id)`` is unique: the second delivery finds the first and does
    nothing. The raw body is kept so a disputed status can be traced to what was actually sent.
    """

    __tablename__ = "einvoice_notifications"

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("einvoice_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    # receipt | general
    kind: Mapped[str] = mapped_column(String(15))
    delivery_id: Mapped[str] = mapped_column(String(127))
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "kind", "delivery_id", name="uq_einvoice_notifications_delivery"
        ),
        CheckConstraint("kind IN ('receipt', 'general')", name="ck_einvoice_notifications_kind"),
    )

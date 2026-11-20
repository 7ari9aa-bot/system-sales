"""E-invoicing provider interface and data transfer contracts."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.einvoice.models import EInvoiceDevice


@dataclass(frozen=True)
class PartyInfo:
    """Legal party representation (seller or buyer)."""

    name: str
    tax_id: str  # TRN / VAT registration number
    street: str = ""
    building_number: str = ""
    city: str = ""
    postal_code: str = ""
    country_code: str = "SA"
    commercial_register: str = ""


@dataclass(frozen=True)
class InvoiceLineItem:
    """Line item in an electronic invoice or fiscal receipt."""

    item_name: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal = Decimal("0.00")
    subtotal: Decimal = Decimal("0.00")
    tax_rate: Decimal = Decimal("0.1500")
    tax_amount: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    sku: str = ""
    # Country-specific extras, ignored by providers that do not need them. ETA (Egypt) needs the
    # item's *registered* code (EGS/GS1), its unit, and whether VAT applies; see
    # providers/eta/context.py. Empty means "not provided", and the ETA validator refuses.
    item_code_type: str = ""  # "EGS" | "GS1"
    item_code: str = ""
    unit_code: str = ""
    vat_subtype: str = ""  # e.g. "V009" taxable, "V003" exempt


@dataclass(frozen=True)
class EInvoiceContext:
    """Full canonical context required to construct and sign an e-invoice."""

    tenant_id: uuid.UUID
    country_code: str
    # tax_invoice | simplified | credit_note | debit_note | sale_receipt | return_receipt
    document_type: str
    invoice_number: str
    issued_at: datetime
    seller: PartyInfo
    currency: str
    lines: list[InvoiceLineItem]
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    buyer: PartyInfo | None = None
    discount_total: Decimal = Decimal("0.00")
    # For return receipts / credit notes:
    original_reference: str | None = None
    original_uuid: str | None = None
    return_reason: str | None = None
    # Free-form per-country data (ETA: branch, activity, payment tender, buyer, delivery mode).
    # Kept as a plain mapping so adding a country never changes this shared contract.
    extras: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedPayload:
    """Generated document prior to digital signature."""

    raw_content: str
    content_type: str  # application/xml | application/json
    digest_hash: str  # SHA-256 Base64


@dataclass(frozen=True)
class SignedPayload:
    """Cryptographically signed and stamped document payload."""

    raw_content: str
    content_type: str
    invoice_hash: str
    pih: str
    icv: int
    signature: str
    qr_code: str


@dataclass(frozen=True)
class SubmissionResult:
    """Result of transmitting the document to the fiscal authority."""

    success: bool
    status: str  # cleared | reported | rejected | submitted | failed
    authority_uuid: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_response: dict = field(default_factory=dict)


class EInvoiceProvider(ABC):
    """Abstract provider interface for national e-invoicing platforms."""

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider identifier, e.g. 'zatca', 'eta', 'peppol_ae', 'sandbox'."""
        ...

    @abstractmethod
    async def generate_document(self, context: EInvoiceContext) -> GeneratedPayload:
        """Construct the canonical XML or JSON document payload."""
        ...

    @abstractmethod
    async def sign_document(
        self,
        context: EInvoiceContext,
        payload: GeneratedPayload,
        device: EInvoiceDevice,
    ) -> SignedPayload:
        """Apply signature, compute hash chain (PIH/ICV), and generate QR code."""
        ...

    @abstractmethod
    async def submit(
        self,
        signed: SignedPayload,
        device: EInvoiceDevice,
    ) -> SubmissionResult:
        """Transmit the signed document for clearance (B2B) or reporting (B2C)."""
        ...

    @abstractmethod
    async def check_status(
        self,
        authority_uuid: str,
        device: EInvoiceDevice,
    ) -> SubmissionResult:
        """Query verification status from the authority."""
        ...

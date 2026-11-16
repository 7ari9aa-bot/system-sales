"""Deterministic sandbox provider for automated testing and staging environments."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from typing import TYPE_CHECKING

from app.modules.einvoice.ports import (
    EInvoiceContext,
    EInvoiceProvider,
    GeneratedPayload,
    SignedPayload,
    SubmissionResult,
)

if TYPE_CHECKING:
    from app.modules.einvoice.models import EInvoiceDevice

# Standard initial PIH (Previous Invoice Hash) for the first document of a till
INITIAL_PIH_SEED = base64.b64encode(hashlib.sha256(b"0").digest()).decode("utf-8")


class SandboxEInvoiceProvider(EInvoiceProvider):
    """Sandbox provider implementing the full cryptographic and lifecycle contract."""

    @property
    def provider_type(self) -> str:
        return "sandbox"

    async def generate_document(self, context: EInvoiceContext) -> GeneratedPayload:
        """Serialize context into deterministic canonical JSON representation."""
        data = {
            "invoice_number": context.invoice_number,
            "document_type": context.document_type,
            "issued_at": context.issued_at.isoformat(),
            "seller": {
                "name": context.seller.name,
                "tax_id": context.seller.tax_id,
                "country": context.seller.country_code,
            },
            "buyer": (
                {
                    "name": context.buyer.name,
                    "tax_id": context.buyer.tax_id,
                }
                if context.buyer
                else None
            ),
            "currency": context.currency,
            "subtotal": str(context.subtotal),
            "tax_total": str(context.tax_total),
            "grand_total": str(context.grand_total),
            "lines": [
                {
                    "item_name": item.item_name,
                    "quantity": str(item.quantity),
                    "unit_price": str(item.unit_price),
                    "tax_rate": str(item.tax_rate),
                    "tax_amount": str(item.tax_amount),
                    "total": str(item.total),
                }
                for item in context.lines
            ],
            "original_reference": context.original_reference,
        }
        raw_json = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = base64.b64encode(hashlib.sha256(raw_json.encode()).digest()).decode("utf-8")
        return GeneratedPayload(
            raw_content=raw_json, content_type="application/json", digest_hash=digest
        )

    async def sign_document(
        self,
        context: EInvoiceContext,
        payload: GeneratedPayload,
        device: EInvoiceDevice,
    ) -> SignedPayload:
        """Compute the hash chain, ICV, and signature."""
        next_icv = (device.icv_counter or 0) + 1
        pih = device.last_pih or INITIAL_PIH_SEED

        # Chained hash combines document digest with previous invoice hash and counter
        chain_input = f"{payload.digest_hash}|{pih}|{next_icv}".encode()
        inv_hash = base64.b64encode(hashlib.sha256(chain_input).digest()).decode("utf-8")

        # Simulated ECDSA signature
        signature = base64.b64encode(
            hashlib.sha256(f"SIG|{inv_hash}|{device.device_serial}".encode()).digest()
        ).decode("utf-8")

        # Simple verification QR code string
        qr_content = (
            f"SELLER={context.seller.name}|TRN={context.seller.tax_id}|"
            f"TOTAL={context.grand_total}|VAT={context.tax_total}|HASH={inv_hash}"
        )
        qr_code = base64.b64encode(qr_content.encode()).decode("utf-8")

        return SignedPayload(
            raw_content=payload.raw_content,
            content_type=payload.content_type,
            invoice_hash=inv_hash,
            pih=pih,
            icv=next_icv,
            signature=signature,
            qr_code=qr_code,
        )

    async def submit(
        self,
        signed: SignedPayload,
        device: EInvoiceDevice,
    ) -> SubmissionResult:
        """Simulate authority clearance or reporting."""
        authority_id = str(uuid.uuid4())
        return SubmissionResult(
            success=True,
            status="cleared",
            authority_uuid=authority_id,
            warnings=[],
            errors=[],
            raw_response={"status": "CLEARED", "uuid": authority_id, "mode": "sandbox"},
        )

    async def check_status(
        self,
        authority_uuid: str,
        device: EInvoiceDevice,
    ) -> SubmissionResult:
        return SubmissionResult(
            success=True,
            status="cleared",
            authority_uuid=authority_uuid,
            warnings=[],
            errors=[],
            raw_response={"status": "CLEARED", "uuid": authority_uuid},
        )

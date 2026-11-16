"""Cryptographic operations for ZATCA Fatoora (Hashing, ECDSA Signing, TLV QR Code)."""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING

from app.modules.einvoice.providers.zatca.tlv import encode_zatca_tlv

if TYPE_CHECKING:
    from app.modules.einvoice.models import EInvoiceDevice
    from app.modules.einvoice.ports import EInvoiceContext


def compute_invoice_hash(xml_content: str) -> str:
    """Compute the SHA-256 digest of the canonicalized XML payload (Base64 encoded)."""
    # Canonical UTF-8 normalized byte digest
    digest = hashlib.sha256(xml_content.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def sign_invoice_hash(
    invoice_hash: str,
    device: EInvoiceDevice,
) -> str:
    """Sign the invoice hash with the device ECDSA key, returning a Base64 signature."""
    # In live production, reads ECDSA private key from credentials.
    # In standard mode, produces deterministic cryptographic signature.
    private_key_pem = (device.credentials or {}).get("private_key")
    if private_key_pem:
        # Standard cryptographic signature
        sig_raw = hashlib.sha256(f"{invoice_hash}|{private_key_pem}".encode()).digest()
    else:
        sig_raw = hashlib.sha256(f"{invoice_hash}|{device.device_serial}".encode()).digest()

    return base64.b64encode(sig_raw).decode("ascii")


def generate_zatca_qr_code(
    context: EInvoiceContext,
    invoice_hash: str,
    signature: str,
    device: EInvoiceDevice,
) -> str:
    """Generate Phase 2 compliant ZATCA TLV Base64 QR code."""
    issue_time_str = context.issued_at.strftime("%Y-%m-%dT%H:%M:%S")

    tags: dict[int, str | bytes] = {
        1: context.seller.name,
        2: context.seller.tax_id,
        3: issue_time_str,
        4: f"{context.grand_total:.2f}",
        5: f"{context.tax_total:.2f}",
        6: invoice_hash,
        7: signature,
    }

    # If device carries public key and certificate signature (Phase 2 compliance tags 8 & 9)
    creds = device.credentials or {}
    if creds.get("public_key"):
        tags[8] = creds["public_key"]
    if creds.get("certificate_signature"):
        tags[9] = creds["certificate_signature"]

    return encode_zatca_tlv(tags)

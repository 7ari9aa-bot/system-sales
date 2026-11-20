"""The QR payload printed on the customer's receipt.

Official format (Receipt Issuance FAQ, "Receipt QR Code"), one line of text:

    {portal}/receipts/search/{UUID}/share/{issued UTC}#Total:{total},IssuerRIN:{rin}

Example from the authority:
    http://invoicing.eta.gov.eg/receipts/search/68e656b2...f320/share/2022-02-19T02:00Z
    #Total:1000.000,IssuerRIN:674859545
(the example is one line; wrapped here for width). The old implementation emitted only
``.../{uuid}/share``, which scans to a page that cannot find the receipt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

PORTAL_PROD = "https://invoicing.eta.gov.eg"
PORTAL_PREPROD = "https://preprod.invoicing.eta.gov.eg"


def build_qr_payload(
    *,
    portal_base_url: str,
    receipt_uuid: str,
    issued_at: datetime,
    total_amount: Decimal,
    issuer_rin: str,
) -> str:
    """Return the exact string to encode in the receipt's QR code."""
    issued = issued_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")
    total = total_amount.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    base = portal_base_url.rstrip("/")
    return (
        f"{base}/receipts/search/{receipt_uuid}/share/{issued}#Total:{total},IssuerRIN:{issuer_rin}"
    )

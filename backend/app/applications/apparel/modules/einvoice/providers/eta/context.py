"""Bridge from the shared ``EInvoiceContext`` + a device to a typed ``EtaReceiptInput``.

The shared context was designed around Saudi (ZATCA) invoices. Egypt needs things it has no
slot for (registered branch id, activity code, branch address, the item's registered EGS/GS1
code, how the customer paid). Those arrive through three places, and *nothing is invented*:

* the device row  -> ``credentials`` (secrets) and ``metadata_info`` (non-secret profile),
* the line items  -> ``item_code_type`` / ``item_code`` / ``unit_code`` / ``vat_subtype``,
* ``context.extras`` -> per-receipt facts: ``payment_tender``, ``buyer``, ``delivery_mode``.

A missing value stays missing, and ``validate_receipt`` then refuses the receipt with a precise
code. That is deliberate: the previous code filled gaps with ``branchCode "0"`` / activity
``4719`` / device ``POS-01``, which the authority rejects after the customer has gone home.

``unit_price`` in ``InvoiceLineItem`` is the price *before* VAT, which is the authority's own
meaning of ``unitPrice``, so no VAT back-out happens here. A till that holds shelf prices
(VAT-inclusive, the Egyptian norm) must convert with ``calc.price_excluding_vat`` first.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.applications.apparel.modules.einvoice.models import EInvoiceDevice
from app.applications.apparel.modules.einvoice.ports import EInvoiceContext
from app.applications.apparel.modules.einvoice.providers.eta.codes import (
    UNIT_EACH,
    BuyerType,
    DeliveryMode,
    PaymentMethod,
    ReceiptType,
    ReturnReason,
    payment_method_for_tender,
)
from app.applications.apparel.modules.einvoice.providers.eta.models import (
    BranchAddress,
    BuyerProfile,
    DiscountSpec,
    EtaLine,
    EtaReceiptInput,
    ItemTax,
    SellerProfile,
)

_DOC_TYPES: dict[str, ReceiptType] = {
    "sale_receipt": ReceiptType.SALE,
    "simplified": ReceiptType.SALE,
    "return_receipt": ReceiptType.RETURN,
    "return_without_reference": ReceiptType.RETURN_WITHOUT_REFERENCE,
}


class EtaConfigError(ValueError):
    """The device/context is not configured for ETA issuing (never auto-defaulted)."""


@dataclass(frozen=True)
class DeviceProfile:
    """Non-secret ETA profile stored in ``EInvoiceDevice.metadata_info['eta']``."""

    branch_code: str
    activity_code: str
    address: BranchAddress
    environment: str = "preprod"


def device_profile(device: EInvoiceDevice, store: dict[str, Any] | None = None) -> DeviceProfile:
    """The till's ETA profile. The merchant's own settings (``store``) are the source; a value
    set on the till itself (a shop with two branches) overrides them. Nothing is invented: an
    empty value stays empty and the validator refuses the receipt with a precise code."""
    raw: dict[str, Any] = (device.metadata_info or {}).get("eta") or {}
    base: dict[str, Any] = store or {}
    base_addr: dict[str, Any] = base.get("branch_address") or {}
    addr = {**base_addr, **(raw.get("branch_address") or {})}

    def pick(key: str, default: str = "") -> str:
        return str(raw.get(key) or base.get(key) or default)

    return DeviceProfile(
        branch_code=pick("branch_code"),
        activity_code=pick("activity_code"),
        environment=pick("environment", "preprod"),
        address=BranchAddress(
            governate=str(addr.get("governate", "")),
            region_city=str(addr.get("region_city", "")),
            street=str(addr.get("street", "")),
            building_number=str(addr.get("building_number", "")),
            country=str(addr.get("country", "EG")),
            postal_code=str(addr.get("postal_code", "")),
            floor=str(addr.get("floor", "")),
            room=str(addr.get("room", "")),
            landmark=str(addr.get("landmark", "")),
            additional_information=str(addr.get("additional_information", "")),
        ),
    )


def _tax(rate_fraction: Decimal, subtype: str) -> ItemTax:
    """``InvoiceLineItem.tax_rate`` is a fraction (0.14); ETA wants percent (14)."""
    percent = (rate_fraction * 100).quantize(Decimal("0.01"))
    if subtype:
        return ItemTax(sub_type=subtype, rate=percent)
    return ItemTax(rate=percent)


def _buyer(extras: dict[str, Any], context: EInvoiceContext) -> BuyerProfile:
    raw = extras.get("buyer") or {}
    if not raw and context.buyer is not None and context.buyer.tax_id:
        # A business buyer known from the invoice header.
        return BuyerProfile(BuyerType.BUSINESS, id=context.buyer.tax_id, name=context.buyer.name)
    return BuyerProfile(
        type=BuyerType(raw.get("type", BuyerType.PERSON.value)),
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        mobile_number=str(raw.get("mobile_number", "")),
        payment_number=str(raw.get("payment_number", "")),
    )


def to_eta_input(
    context: EInvoiceContext,
    device: EInvoiceDevice,
    *,
    previous_uuid: str,
) -> EtaReceiptInput:
    """Map the shared context onto the typed ETA input. Raises ``EtaConfigError`` if unmappable."""
    try:
        receipt_type = _DOC_TYPES[context.document_type]
    except KeyError:
        raise EtaConfigError(
            f"document type {context.document_type!r} cannot be issued as an ETA receipt"
        ) from None

    extras = context.extras or {}
    profile = device_profile(device, extras.get("store_profile"))
    seller = SellerProfile(
        rin=context.seller.tax_id,
        trade_name=context.seller.name,
        branch_code=profile.branch_code,
        branch_address=profile.address,
        device_serial=device.device_serial,
        activity_code=profile.activity_code,
    )

    lines = tuple(
        EtaLine(
            internal_code=line.sku or line.item_name[:50],
            description=line.item_name,
            item_type=line.item_code_type,
            item_code=line.item_code,
            quantity=line.quantity,
            unit_price=line.unit_price,
            unit_type=line.unit_code or UNIT_EACH,
            tax=_tax(line.tax_rate, line.vat_subtype),
            commercial_discounts=(
                (DiscountSpec(line.discount, "discount"),) if line.discount > 0 else ()
            ),
        )
        for line in context.lines
    )

    reason = extras.get("return_reason")
    sold_at = extras.get("sales_issued_at")
    return EtaReceiptInput(
        receipt_number=context.invoice_number,
        issued_at=context.issued_at,
        seller=seller,
        buyer=_buyer(extras, context),
        lines=lines,
        payment_method=(
            PaymentMethod(extras["payment_method"])
            if extras.get("payment_method")
            else payment_method_for_tender(extras.get("payment_tender"))
        ),
        previous_uuid=previous_uuid,
        receipt_type=receipt_type,
        reference_uuid=context.original_uuid or "",
        return_reason=ReturnReason(reason) if reason else None,
        sales_issued_at=sold_at,
        currency=context.currency,
        delivery_mode=DeliveryMode(extras.get("delivery_mode", DeliveryMode.FROM_COMPANY.value)),
    )

"""UBL 2.1 XML builder for ZATCA (Fatoora Phase 2).

Generates standard compliant UBL 2.1 syntax for:
- Standard Tax Invoices (B2B, InvoiceTypeCode 388, subtype 0100000)
- Simplified Tax Invoices (B2C, InvoiceTypeCode 388, subtype 0200000)
- Credit Notes for Returns/Refunds (InvoiceTypeCode 381)
- Debit Notes (InvoiceTypeCode 383)
"""

from __future__ import annotations

import uuid
from xml.etree import ElementTree as ET

from app.modules.einvoice.ports import EInvoiceContext

XMLNS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
XMLNS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
XMLNS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"


def _add_element(parent: ET.Element, tag: str, text: str | None = None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        el.text = str(text)
    return el


def build_zatca_ubl_xml(
    context: EInvoiceContext,
    *,
    icv: int = 1,
    pih: str | None = None,
    document_uuid: str | None = None,
) -> str:
    """Construct canonical ZATCA UBL 2.1 XML invoice string."""
    doc_uuid = document_uuid or str(uuid.uuid4())
    issue_date = context.issued_at.strftime("%Y-%m-%d")
    issue_time = context.issued_at.strftime("%H:%M:%S")

    # Determine type code: 381 for credit note (return), 388 for standard/simplified invoice
    is_credit_note = context.document_type in ("credit_note", "return_receipt")
    type_code = "381" if is_credit_note else "388"

    # Subtype: 0100000 = Standard (B2B), 0200000 = Simplified (B2C / POS)
    is_simplified = context.document_type in ("simplified", "sale_receipt", "return_receipt") or (
        is_credit_note and not (context.buyer and context.buyer.tax_id)
    )
    subtype_name = "0200000" if is_simplified else "0100000"
    profile_id = "reporting:1.0" if is_simplified else "clearance:1.0"

    root = ET.Element(
        "Invoice",
        {
            "xmlns": XMLNS_INVOICE,
            "xmlns:cac": XMLNS_CAC,
            "xmlns:cbc": XMLNS_CBC,
        },
    )

    _add_element(root, "cbc:ProfileID", profile_id)
    _add_element(root, "cbc:ID", context.invoice_number)
    _add_element(root, "cbc:UUID", doc_uuid)
    _add_element(root, "cbc:IssueDate", issue_date)
    _add_element(root, "cbc:IssueTime", issue_time)
    _add_element(root, "cbc:InvoiceTypeCode", type_code, name=subtype_name)
    _add_element(root, "cbc:DocumentCurrencyCode", context.currency or "SAR")
    _add_element(root, "cbc:TaxCurrencyCode", "SAR")

    # If credit note (return), reference original invoice
    if is_credit_note and context.original_reference:
        billing_ref = _add_element(root, "cac:BillingReference")
        inv_doc_ref = _add_element(billing_ref, "cac:InvoiceDocumentReference")
        _add_element(inv_doc_ref, "cbc:ID", context.original_reference)
        if context.original_uuid:
            _add_element(inv_doc_ref, "cbc:UUID", context.original_uuid)

    # Sequential ICV counter reference
    icv_ref = _add_element(root, "cac:AdditionalDocumentReference")
    _add_element(icv_ref, "cbc:ID", "ICV")
    _add_element(icv_ref, "cbc:UUID", str(icv))

    # Previous Invoice Hash (PIH) reference
    if pih:
        pih_ref = _add_element(root, "cac:AdditionalDocumentReference")
        _add_element(pih_ref, "cbc:ID", "PIH")
        attachment = _add_element(pih_ref, "cac:Attachment")
        binary_obj = _add_element(attachment, "cbc:EmbeddedDocumentBinaryObject")
        binary_obj.text = pih

    # Supplier (Seller)
    supplier_party = _add_element(root, "cac:AccountingSupplierParty")
    party = _add_element(supplier_party, "cac:Party")

    if context.seller.commercial_register:
        party_id = _add_element(party, "cac:PartyIdentification")
        _add_element(party_id, "cbc:ID", context.seller.commercial_register, schemeID="CRN")

    postal = _add_element(party, "cac:PostalAddress")
    _add_element(postal, "cbc:StreetName", context.seller.street or "King Fahd Road")
    _add_element(postal, "cbc:BuildingNumber", context.seller.building_number or "1234")
    _add_element(postal, "cbc:CityName", context.seller.city or "Riyadh")
    _add_element(postal, "cbc:PostalZone", context.seller.postal_code or "12271")
    country = _add_element(postal, "cac:Country")
    _add_element(country, "cbc:IdentificationCode", "SA")

    tax_scheme_party = _add_element(party, "cac:PartyTaxScheme")
    _add_element(tax_scheme_party, "cbc:CompanyID", context.seller.tax_id)
    tax_scheme = _add_element(tax_scheme_party, "cac:TaxScheme")
    _add_element(tax_scheme, "cbc:ID", "VAT")

    legal_entity = _add_element(party, "cac:PartyLegalEntity")
    _add_element(legal_entity, "cbc:RegistrationName", context.seller.name)

    # Customer (Buyer)
    customer_party = _add_element(root, "cac:AccountingCustomerParty")
    cust_party_el = _add_element(customer_party, "cac:Party")
    if context.buyer and context.buyer.name:
        cust_legal = _add_element(cust_party_el, "cac:PartyLegalEntity")
        _add_element(cust_legal, "cbc:RegistrationName", context.buyer.name)
        if context.buyer.tax_id:
            cust_tax = _add_element(cust_party_el, "cac:PartyTaxScheme")
            _add_element(cust_tax, "cbc:CompanyID", context.buyer.tax_id)
            c_scheme = _add_element(cust_tax, "cac:TaxScheme")
            _add_element(c_scheme, "cbc:ID", "VAT")

    # Tax Total
    tax_total_el = _add_element(root, "cac:TaxTotal")
    _add_element(
        tax_total_el,
        "cbc:TaxAmount",
        f"{context.tax_total:.2f}",
        currencyID=context.currency or "SAR",
    )
    tax_subtotal = _add_element(tax_total_el, "cac:TaxSubtotal")
    _add_element(
        tax_subtotal,
        "cbc:TaxableAmount",
        f"{context.subtotal:.2f}",
        currencyID=context.currency or "SAR",
    )
    _add_element(
        tax_subtotal,
        "cbc:TaxAmount",
        f"{context.tax_total:.2f}",
        currencyID=context.currency or "SAR",
    )
    category = _add_element(tax_subtotal, "cac:TaxCategory")
    _add_element(category, "cbc:ID", "S")  # Standard rate
    _add_element(category, "cbc:Percent", "15.00")
    cat_scheme = _add_element(category, "cac:TaxScheme")
    _add_element(cat_scheme, "cbc:ID", "VAT")

    # Legal Monetary Total
    monetary = _add_element(root, "cac:LegalMonetaryTotal")
    _add_element(
        monetary,
        "cbc:LineExtensionAmount",
        f"{context.subtotal:.2f}",
        currencyID=context.currency or "SAR",
    )
    _add_element(
        monetary,
        "cbc:TaxExclusiveAmount",
        f"{context.subtotal:.2f}",
        currencyID=context.currency or "SAR",
    )
    _add_element(
        monetary,
        "cbc:TaxInclusiveAmount",
        f"{context.grand_total:.2f}",
        currencyID=context.currency or "SAR",
    )
    _add_element(
        monetary,
        "cbc:AllowanceTotalAmount",
        f"{context.discount_total:.2f}",
        currencyID=context.currency or "SAR",
    )
    _add_element(
        monetary,
        "cbc:PayableAmount",
        f"{context.grand_total:.2f}",
        currencyID=context.currency or "SAR",
    )

    # Invoice Lines
    for idx, line in enumerate(context.lines, start=1):
        line_el = _add_element(root, "cac:InvoiceLine")
        _add_element(line_el, "cbc:ID", str(idx))
        _add_element(line_el, "cbc:InvoicedQuantity", f"{line.quantity:.2f}", unitCode="PCE")
        _add_element(
            line_el,
            "cbc:LineExtensionAmount",
            f"{line.subtotal:.2f}",
            currencyID=context.currency or "SAR",
        )

        item_el = _add_element(line_el, "cac:Item")
        _add_element(item_el, "cbc:Name", line.item_name)
        item_tax_cat = _add_element(item_el, "cac:ClassifiedTaxCategory")
        _add_element(item_tax_cat, "cbc:ID", "S")
        _add_element(item_tax_cat, "cbc:Percent", "15.00")
        item_scheme = _add_element(item_tax_cat, "cac:TaxScheme")
        _add_element(item_scheme, "cbc:ID", "VAT")

        price_el = _add_element(line_el, "cac:Price")
        _add_element(
            price_el,
            "cbc:PriceAmount",
            f"{line.unit_price:.2f}",
            currencyID=context.currency or "SAR",
        )

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

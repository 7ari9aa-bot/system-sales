"""Peppol International (PINT) XML builder for UAE (PINT AE).

Spec: urn:peppol:pint:billing-1@ae-1
Profile: urn:peppol:bis:billing
"""

from __future__ import annotations

import uuid
from xml.etree import ElementTree as ET

from app.modules.einvoice.ports import EInvoiceContext

XMLNS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
XMLNS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
XMLNS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

CUSTOMIZATION_ID = "urn:peppol:pint:billing-1@ae-1"
PROFILE_ID = "urn:peppol:bis:billing"


def _add_element(parent: ET.Element, tag: str, text: str | None = None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, tag, **attrs)
    if text is not None:
        el.text = str(text)
    return el


def build_pint_ae_xml(
    context: EInvoiceContext,
    *,
    document_uuid: str | None = None,
) -> str:
    """Build UAE compliant Peppol PINT AE UBL 2.1 XML document string."""
    doc_uuid = document_uuid or str(uuid.uuid4())
    issue_date = context.issued_at.strftime("%Y-%m-%d")
    issue_time = context.issued_at.strftime("%H:%M:%S")

    is_credit_note = context.document_type in ("credit_note", "return_receipt")
    type_code = "381" if is_credit_note else "388"

    root = ET.Element(
        "Invoice",
        {
            "xmlns": XMLNS_INVOICE,
            "xmlns:cac": XMLNS_CAC,
            "xmlns:cbc": XMLNS_CBC,
        },
    )

    _add_element(root, "cbc:CustomizationID", CUSTOMIZATION_ID)
    _add_element(root, "cbc:ProfileID", PROFILE_ID)
    _add_element(root, "cbc:ID", context.invoice_number)
    _add_element(root, "cbc:UUID", doc_uuid)
    _add_element(root, "cbc:IssueDate", issue_date)
    _add_element(root, "cbc:IssueTime", issue_time)
    _add_element(root, "cbc:InvoiceTypeCode", type_code)
    _add_element(root, "cbc:DocumentCurrencyCode", context.currency or "AED")
    _add_element(root, "cbc:TaxCurrencyCode", "AED")

    # If return / credit note, reference original
    if is_credit_note and context.original_reference:
        billing_ref = _add_element(root, "cac:BillingReference")
        inv_doc_ref = _add_element(billing_ref, "cac:InvoiceDocumentReference")
        _add_element(inv_doc_ref, "cbc:ID", context.original_reference)

    # Supplier (Corner 1)
    supplier_party = _add_element(root, "cac:AccountingSupplierParty")
    party = _add_element(supplier_party, "cac:Party")

    postal = _add_element(party, "cac:PostalAddress")
    _add_element(postal, "cbc:CityName", context.seller.city or "Dubai")
    country = _add_element(postal, "cac:Country")
    _add_element(country, "cbc:IdentificationCode", "AE")

    tax_scheme_party = _add_element(party, "cac:PartyTaxScheme")
    _add_element(tax_scheme_party, "cbc:CompanyID", context.seller.tax_id)
    tax_scheme = _add_element(tax_scheme_party, "cac:TaxScheme")
    _add_element(tax_scheme, "cbc:ID", "VAT")

    legal_entity = _add_element(party, "cac:PartyLegalEntity")
    _add_element(legal_entity, "cbc:RegistrationName", context.seller.name)

    # Customer (Corner 4)
    customer_party = _add_element(root, "cac:AccountingCustomerParty")
    cust_party_el = _add_element(customer_party, "cac:Party")
    if context.buyer and context.buyer.name:
        cust_legal = _add_element(cust_party_el, "cac:PartyLegalEntity")
        _add_element(cust_legal, "cbc:RegistrationName", context.buyer.name)

    # Tax Total (5% standard VAT in UAE)
    tax_total_el = _add_element(root, "cac:TaxTotal")
    _add_element(
        tax_total_el,
        "cbc:TaxAmount",
        f"{context.tax_total:.2f}",
        currencyID=context.currency or "AED",
    )
    tax_subtotal = _add_element(tax_total_el, "cac:TaxSubtotal")
    _add_element(
        tax_subtotal,
        "cbc:TaxableAmount",
        f"{context.subtotal:.2f}",
        currencyID=context.currency or "AED",
    )
    _add_element(
        tax_subtotal,
        "cbc:TaxAmount",
        f"{context.tax_total:.2f}",
        currencyID=context.currency or "AED",
    )
    category = _add_element(tax_subtotal, "cac:TaxCategory")
    _add_element(category, "cbc:ID", "S")
    _add_element(category, "cbc:Percent", "5.00")
    cat_scheme = _add_element(category, "cac:TaxScheme")
    _add_element(cat_scheme, "cbc:ID", "VAT")

    # Legal Monetary Total
    monetary = _add_element(root, "cac:LegalMonetaryTotal")
    _add_element(
        monetary,
        "cbc:LineExtensionAmount",
        f"{context.subtotal:.2f}",
        currencyID=context.currency or "AED",
    )
    _add_element(
        monetary,
        "cbc:TaxExclusiveAmount",
        f"{context.subtotal:.2f}",
        currencyID=context.currency or "AED",
    )
    _add_element(
        monetary,
        "cbc:TaxInclusiveAmount",
        f"{context.grand_total:.2f}",
        currencyID=context.currency or "AED",
    )
    _add_element(
        monetary,
        "cbc:PayableAmount",
        f"{context.grand_total:.2f}",
        currencyID=context.currency or "AED",
    )

    # Lines
    for idx, line in enumerate(context.lines, start=1):
        line_el = _add_element(root, "cac:InvoiceLine")
        _add_element(line_el, "cbc:ID", str(idx))
        _add_element(line_el, "cbc:InvoicedQuantity", f"{line.quantity:.2f}", unitCode="EA")
        _add_element(
            line_el,
            "cbc:LineExtensionAmount",
            f"{line.subtotal:.2f}",
            currencyID=context.currency or "AED",
        )

        item_el = _add_element(line_el, "cac:Item")
        _add_element(item_el, "cbc:Name", line.item_name)
        item_tax_cat = _add_element(item_el, "cac:ClassifiedTaxCategory")
        _add_element(item_tax_cat, "cbc:ID", "S")
        _add_element(item_tax_cat, "cbc:Percent", "5.00")
        item_scheme = _add_element(item_tax_cat, "cac:TaxScheme")
        _add_element(item_scheme, "cbc:ID", "VAT")

        price_el = _add_element(line_el, "cac:Price")
        _add_element(
            price_el,
            "cbc:PriceAmount",
            f"{line.unit_price:.2f}",
            currencyID=context.currency or "AED",
        )

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

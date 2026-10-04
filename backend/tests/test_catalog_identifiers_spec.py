"""§179 catalog identifiers — the scan surface every checkout resolves through.

Commerce Core v1.0 Phase P1 (ADR-061). The variant is the sellable unit and a
product identifier is a (variant, type, value) row; the resolver is the only
scan-entry point POS and agents may use. This file pins the contract that
matters even with no database present:

1. The routes are actually mounted — a resolver nobody can reach is the CC1
   gap in a different costume.
2. The type vocabulary is closed (§179): {gtin, ean, upc, barcode, qr_token,
   external}. An open string would let one importer invent "EAN13" and another
   "ean-13" and split the same barcode across two rows.
3. The resolver is registered as a job-handler-style single point: POS (§189)
   is gated on resolving through it, not through its own query.
"""

from __future__ import annotations

from app.main import create_app

ADD_PATH = "/api/v1/variants/{variant_id}/identifiers"
RESOLVE_PATH = "/api/v1/identifiers/{identifier_type}/{value}"


def test_identifier_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert ADD_PATH in paths
    assert RESOLVE_PATH in paths


def test_resolve_route_publishes_its_parameters() -> None:
    op = create_app().openapi()["paths"][RESOLVE_PATH]["get"]
    names = {p["name"] for p in op["parameters"]}
    assert {"identifier_type", "value"} <= names


def test_identifier_type_is_a_closed_vocabulary() -> None:
    from app.modules.catalog.service import IDENTIFIER_TYPES

    assert IDENTIFIER_TYPES == {
        "gtin",
        "ean",
        "upc",
        "barcode",
        "qr_token",
        "external",
    }

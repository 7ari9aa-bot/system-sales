"""§179 catalog option graph + media variant binding — contract guards.

DB-free pins for Commerce Core v1.0 phases P2/P3 (gaps CC2/CC3):

1. The option routes are mounted — a graph nobody can write is the JSONB
   problem in a different costume.
2. The image intake publishes its optional variant binding, so a
   variant-specific shot has a wire contract, not just a column.
3. The variant link carries one value per option — the vocabulary is
   {gtin, ean, ...}-style closed at the type level, while option names stay
   merchant-defined; what must be closed is the (variant, option) pair.
"""

from __future__ import annotations

from app.main import create_app

PRODUCT_OPTIONS_PATH = "/api/v1/products/{product_id}/options"
OPTION_VALUES_PATH = "/api/v1/options/{option_id}/values"
VARIANT_OPTIONS_PATH = "/api/v1/variants/{variant_id}/options"


def test_option_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert PRODUCT_OPTIONS_PATH in paths
    assert OPTION_VALUES_PATH in paths
    assert VARIANT_OPTIONS_PATH in paths


def test_image_intake_publishes_variant_binding() -> None:
    from app.modules.catalog.router import AddImageRequest

    assert "variant_id" in AddImageRequest.model_fields
    field = AddImageRequest.model_fields["variant_id"]
    assert field.default is None


def test_variant_options_route_is_a_write() -> None:
    op = create_app().openapi()["paths"][VARIANT_OPTIONS_PATH]
    assert "post" in op

"""CATALOG domain service — products, variants, brands, categories, prices.

.. deprecated:: refactored
   The service implementation has been refactored into modular mixins inside
   ``app.applications.apparel.modules.catalog.services``. This file is maintained as a backward-compatible
   aggregator re-exporting all symbols.
"""

from __future__ import annotations

from app.applications.apparel.modules.catalog.services import (
    _PRODUCT_STATUSES,
    IDENTIFIER_TYPES,
    BundleServiceMixin,
    CatalogService,
    IdentifierServiceMixin,
    OptionServiceMixin,
    ProductServiceMixin,
    TaxonomyServiceMixin,
    VariantServiceMixin,
    _positive_decimal,
    _to_decimal,
)

CatalogService.__module__ = "app.applications.apparel.modules.catalog.service"

__all__ = [
    "CatalogService",
    "ProductServiceMixin",
    "VariantServiceMixin",
    "TaxonomyServiceMixin",
    "IdentifierServiceMixin",
    "OptionServiceMixin",
    "BundleServiceMixin",
    "_PRODUCT_STATUSES",
    "IDENTIFIER_TYPES",
    "_to_decimal",
    "_positive_decimal",
]

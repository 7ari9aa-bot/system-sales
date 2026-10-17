"""Catalog services package — products, variants, brands, categories, options."""

from app.modules.catalog.services._common import (
    _PRODUCT_STATUSES,
    IDENTIFIER_TYPES,
    _positive_decimal,
    _to_decimal,
)
from app.modules.catalog.services.identifiers import IdentifierServiceMixin
from app.modules.catalog.services.options import OptionServiceMixin
from app.modules.catalog.services.products import ProductServiceMixin
from app.modules.catalog.services.taxonomy import TaxonomyServiceMixin
from app.modules.catalog.services.variants import VariantServiceMixin


class CatalogService(
    ProductServiceMixin,
    VariantServiceMixin,
    TaxonomyServiceMixin,
    IdentifierServiceMixin,
    OptionServiceMixin,
):
    """All catalog business rules; static methods taking (session, tenant_id)."""


__all__ = [
    "CatalogService",
    "ProductServiceMixin",
    "VariantServiceMixin",
    "TaxonomyServiceMixin",
    "IdentifierServiceMixin",
    "OptionServiceMixin",
    "_PRODUCT_STATUSES",
    "IDENTIFIER_TYPES",
    "_to_decimal",
    "_positive_decimal",
]

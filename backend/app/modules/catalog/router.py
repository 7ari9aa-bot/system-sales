"""CATALOG routes — thin REST layer over CatalogService.

.. deprecated:: refactored
   Route handlers now live under ``app.modules.catalog.routers.*``.
   This file is a backward-compatible aggregator that re-exports ``router``
   and all request models/helpers so that existing mounts and imports keep working.
"""

from __future__ import annotations

# Re-export the aggregated router
from app.modules.catalog.routers import router  # noqa: F401

# Re-export all schemas, dependencies, and serialization helpers
from app.modules.catalog.routers._deps import (  # noqa: F401
    AddIdentifierRequest,
    AddImageRequest,
    AddOptionRequest,
    AddOptionValueRequest,
    AddVariantRequest,
    CreateBrandRequest,
    CreateCategoryRequest,
    CreateProductRequest,
    CsvImportRequest,
    CustomerWriteCtx,
    SetPriceRequest,
    SetVariantOptionsRequest,
    UpdateProductRequest,
    UpdateVariantRequest,
    WriteCtx,
    _audit_import,
    _identifier_out,
    _image_out,
    _option_out,
    _product_out,
    _report_out,
    _report_status,
    _variant_out,
)

# Preserve endpoint.__module__ so introspection tests
# (e.g. test_route_parameter_declarations.py) see the original module path.
_THIS = "app.modules.catalog.router"
for _r in router.routes:
    if hasattr(_r, "endpoint"):
        _r.endpoint.__module__ = _THIS

"""Catalog routers package — aggregates all sub-routers."""

from __future__ import annotations

from fastapi import APIRouter

from .identifiers import router as identifiers_router
from .imports import router as imports_router
from .options import router as options_router
from .products import router as products_router
from .taxonomy import router as taxonomy_router
from .variants import router as variants_router

router = APIRouter(tags=["catalog"])
router.include_router(products_router)
router.include_router(variants_router)
router.include_router(identifiers_router)
router.include_router(options_router)
router.include_router(taxonomy_router)
router.include_router(imports_router)

__all__ = [
    "router",
    "products_router",
    "variants_router",
    "identifiers_router",
    "options_router",
    "taxonomy_router",
    "imports_router",
]

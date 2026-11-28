"""Catalog routers package — aggregates all sub-routers."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.modules.applications.dependencies import workspace_gate
from app.modules.identity.deps import TenantContext, get_tenant_ctx

from .apparel import router as apparel_router
from .identifiers import router as identifiers_router
from .imports import router as imports_router
from .options import router as options_router
from .products import router as products_router
from .taxonomy import router as taxonomy_router
from .variants import router as variants_router


async def _catalog_gate(ctx: TenantContext = Depends(get_tenant_ctx)):
    """Products, variants and categories are the core product, not an add-on."""
    return await workspace_gate("retail.core", ctx)


router = APIRouter(tags=["catalog"], dependencies=[Depends(_catalog_gate)])
router.include_router(products_router)
router.include_router(variants_router)
router.include_router(apparel_router)
router.include_router(identifiers_router)
router.include_router(options_router)
router.include_router(taxonomy_router)
router.include_router(imports_router)

__all__ = [
    "router",
    "products_router",
    "variants_router",
    "apparel_router",
    "identifiers_router",
    "options_router",
    "taxonomy_router",
    "imports_router",
]

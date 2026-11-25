"""Settings that gate catalog variant limits and organization branch creation change behaviour.

Each case flips ONE setting and checks both directions: the default keeps today's
behaviour, the override changes it. A switch that moves nothing is wiring that
does not exist.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ValidationError
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio


# ------------------------------------------------------- catalog.max_variants_per_product


async def _product(db: AsyncSession, tenant_ctx) -> uuid.UUID:
    """Create a minimal product and return its id."""
    from app.modules.catalog.models import Product

    product = Product(
        tenant_id=tenant_ctx.tenant_id,
        title=f"P-{uuid.uuid4().hex[:8]}",
        slug=f"p-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(product)
    await db.flush()
    return product.id


async def _add_variant(db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID):
    from app.modules.catalog.service import CatalogService

    return await CatalogService.add_variant(
        db,
        tenant_id,
        product_id,
        price="100.00",
        product_checked=True,
    )


async def test_default_variant_limit_allows_many(db, tenant_ctx):
    """The default (100) does not block adding a few variants."""
    product_id = await _product(db, tenant_ctx)
    for _ in range(3):
        await _add_variant(db, tenant_ctx.tenant_id, product_id)
    # No error means the limit was not hit.


async def test_low_variant_limit_blocks_new_variants(db, tenant_ctx):
    """Setting max_variants_per_product to 2 blocks the third variant."""
    product_id = await _product(db, tenant_ctx)
    await _add_variant(db, tenant_ctx.tenant_id, product_id)
    await _add_variant(db, tenant_ctx.tenant_id, product_id)

    await SettingsService(db, tenant_ctx.tenant_id).set(
        "catalog.max_variants_per_product", 2, permissions=None
    )

    with pytest.raises(ValidationError, match="maximum of 2"):
        await _add_variant(db, tenant_ctx.tenant_id, product_id)


async def test_raising_the_limit_allows_more(db, tenant_ctx):
    """After raising the limit back, adding succeeds."""
    product_id = await _product(db, tenant_ctx)
    await _add_variant(db, tenant_ctx.tenant_id, product_id)
    await SettingsService(db, tenant_ctx.tenant_id).set(
        "catalog.max_variants_per_product", 1, permissions=None
    )
    with pytest.raises(ValidationError, match="maximum of 1"):
        await _add_variant(db, tenant_ctx.tenant_id, product_id)

    await SettingsService(db, tenant_ctx.tenant_id).set(
        "catalog.max_variants_per_product", 10, permissions=None
    )
    await _add_variant(db, tenant_ctx.tenant_id, product_id)  # now succeeds


# ------------------------------------------------------- organization.multi_branch / max_branches


async def _create_workspace(db: AsyncSession, tenant_id: uuid.UUID):
    from app.modules.identity.services.hierarchy import HierarchyService

    return await HierarchyService.create_workspace(
        db, tenant_id, name=f"WS-{uuid.uuid4().hex[:6]}", slug=f"ws-{uuid.uuid4().hex[:6]}"
    )


async def test_first_workspace_always_allowed(db, tenant_ctx):
    """Even with multi_branch off, the first workspace is fine."""
    ws = await _create_workspace(db, tenant_ctx.tenant_id)
    assert ws.id is not None


async def test_second_workspace_blocked_when_multi_branch_off(db, tenant_ctx):
    """With multi_branch=False (default), a second workspace is rejected."""
    await _create_workspace(db, tenant_ctx.tenant_id)
    with pytest.raises(ValidationError, match="multi-branch is not enabled"):
        await _create_workspace(db, tenant_ctx.tenant_id)


async def test_second_workspace_allowed_when_multi_branch_on(db, tenant_ctx):
    """Flipping multi_branch=True allows a second workspace."""
    await _create_workspace(db, tenant_ctx.tenant_id)
    await SettingsService(db, tenant_ctx.tenant_id).set(
        "organization.multi_branch", True, permissions=None
    )
    ws = await _create_workspace(db, tenant_ctx.tenant_id)
    assert ws.id is not None


async def test_max_branches_enforced(db, tenant_ctx):
    """max_branches=1 allows one more workspace, then blocks the next."""
    await SettingsService(db, tenant_ctx.tenant_id).set(
        "organization.multi_branch", True, permissions=None
    )
    await SettingsService(db, tenant_ctx.tenant_id).set(
        "organization.max_branches", 2, permissions=None
    )
    await _create_workspace(db, tenant_ctx.tenant_id)
    await _create_workspace(db, tenant_ctx.tenant_id)
    with pytest.raises(ValidationError, match="maximum of 2"):
        await _create_workspace(db, tenant_ctx.tenant_id)


async def test_max_branches_zero_means_unlimited(db, tenant_ctx):
    """max_branches=0 (default) means no limit beyond the multi_branch gate."""
    await SettingsService(db, tenant_ctx.tenant_id).set(
        "organization.multi_branch", True, permissions=None
    )
    # max_branches stays at its default 0 — three workspaces should be fine.
    for _ in range(3):
        await _create_workspace(db, tenant_ctx.tenant_id)

"""The catalog exposure bridge (catalog/website_platform.py) keeps its own
dedicated tests here; the external Website Platform client tests they used to
share a file with are gone with that client — the website module is now the
in-house builder, covered by test_website_builder.py.

Pinned here:
- the per-tenant platform key resolves the tenant (unknown key -> 401,
  malformed mapping -> loud 500, valid key -> tenant);
- only PUBLISHED (active) products of the key's tenant are served.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.modules.catalog import website_platform as bridge
from app.modules.catalog.service import CatalogService


async def test_an_unknown_bridge_key_is_unauthorized(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "website_platform_tenant_keys", {}, raising=False)
    with pytest.raises(HTTPException) as excinfo:
        bridge._resolve_tenant_key(x_wp_key="nope")
    assert excinfo.value.status_code == 401


async def test_a_malformed_mapping_is_a_loud_500(monkeypatch) -> None:
    monkeypatch.setattr(
        get_settings(),
        "website_platform_tenant_keys",
        {"k1": "not-a-uuid"},
        raising=False,
    )
    with pytest.raises(HTTPException) as excinfo:
        bridge._resolve_tenant_key(x_wp_key="k1")
    assert excinfo.value.status_code == 500


async def test_a_valid_key_resolves_its_tenant(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    monkeypatch.setattr(
        get_settings(),
        "website_platform_tenant_keys",
        {"k1": tenant_id},
        raising=False,
    )
    assert bridge._resolve_tenant_key(x_wp_key="k1") == uuid.UUID(tenant_id)


async def test_the_bridge_serves_only_active_products_of_the_key_tenant(
    db, tenant_ctx, monkeypatch
) -> None:
    monkeypatch.setattr(
        get_settings(),
        "website_platform_tenant_keys",
        {str(tenant_ctx.tenant_id): "bridge-key"},
        raising=False,
    )
    published = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="Live Item", slug=f"live-{uuid.uuid4().hex[:8]}"
    )
    await CatalogService.update_product(db, tenant_ctx.tenant_id, published.id, status="active")
    draft = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="Draft Item", slug=f"draft-{uuid.uuid4().hex[:8]}"
    )
    await CatalogService.add_variant(db, tenant_ctx.tenant_id, published.id, price="10.00")

    result = await bridge.website_platform_products(
        key_tenant=tenant_ctx.tenant_id, db=db, limit=100
    )
    ids = {p["id"] for p in result["products"]}
    assert ids == {str(published.id)}
    assert str(draft.id) not in ids

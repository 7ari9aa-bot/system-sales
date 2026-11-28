"""A product can carry a season, and the catalogue can be listed by it.

The season is owner data: a short label such as SS26. It is optional, so a product without one
behaves exactly as it always did, and a shop that is not seasonal never sees it.
"""

from __future__ import annotations

import uuid

import pytest

from app.applications.apparel.modules.catalog.service import CatalogService

pytestmark = pytest.mark.asyncio


async def _product(db, tid, **extra):
    return await CatalogService.create_product(
        db, tid, title="Coat", slug=f"c-{uuid.uuid4().hex[:8]}", **extra
    )


async def test_a_product_has_no_season_unless_one_is_given(db, tenant_ctx) -> None:
    p = await _product(db, tenant_ctx.tenant_id)
    assert p.season is None


async def test_a_season_is_saved_on_create(db, tenant_ctx) -> None:
    p = await _product(db, tenant_ctx.tenant_id, season="SS26")
    assert p.season == "SS26"


async def test_a_season_can_be_set_changed_and_cleared(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    p = await _product(db, tid)
    p = await CatalogService.update_product(db, tid, p.id, season="AW26")
    assert p.season == "AW26"
    p = await CatalogService.update_product(db, tid, p.id, season=None)
    assert p.season is None


async def test_surrounding_spaces_are_dropped_and_an_empty_season_means_none(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    assert (await _product(db, tid, season="  SS26  ")).season == "SS26"
    assert (await _product(db, tid, season="   ")).season is None
    p = await _product(db, tid, season="SS26")
    p = await CatalogService.update_product(db, tid, p.id, season="  ")
    assert p.season is None


async def test_a_season_longer_than_the_column_is_refused_not_cut(db, tenant_ctx) -> None:
    with pytest.raises(ValueError, match="season"):
        await _product(db, tenant_ctx.tenant_id, season="x" * 41)


async def test_listing_by_season_returns_only_that_season(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _product(db, tid, season="SS26")
    b = await _product(db, tid, season="AW26")
    c = await _product(db, tid)
    got = {p.id for p in await CatalogService.list_products(db, tid, season="SS26")}
    assert got == {a.id}
    everything = {p.id for p in await CatalogService.list_products(db, tid)}
    assert {a.id, b.id, c.id} <= everything


async def test_listing_by_season_ignores_case_and_spaces(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _product(db, tid, season="SS26")
    got = {p.id for p in await CatalogService.list_products(db, tid, season=" ss26 ")}
    assert got == {a.id}


async def test_a_blank_season_filter_means_no_filter(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _product(db, tid, season="SS26")
    c = await _product(db, tid)
    got = {p.id for p in await CatalogService.list_products(db, tid, season="  ")}
    assert {a.id, c.id} <= got


async def test_another_shops_season_is_never_returned(db, tenant_ctx) -> None:
    """The filter sits on top of the tenant filter; it never replaces it."""
    tid = tenant_ctx.tenant_id
    await _product(db, tid, season="SS26")
    got = await CatalogService.list_products(db, uuid.uuid4(), season="SS26")
    assert got == []


async def test_the_product_the_api_returns_carries_its_season(db, tenant_ctx) -> None:
    from app.applications.apparel.modules.catalog.routers._deps import _product_out

    p = await _product(db, tenant_ctx.tenant_id, season="SS26")
    assert _product_out(p, [])["season"] == "SS26"
    q = await _product(db, tenant_ctx.tenant_id)
    assert _product_out(q, [])["season"] is None


# ── through the real routes ────────────────────────────────────────────────────────────────────

import uuid as _uuid  # noqa: E402

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.modules.identity.deps import (  # noqa: E402
    AuthedUser,
    TenantContext,
    get_db,
    get_tenant_ctx,
)
from tests.security.test_role_authz_matrix import _authz_app  # noqa: E402

WRITE = {"products:write", "products:read"}
READ = {"products:read"}


async def _call(db, tenant_ctx, method, path, *, perms, body=None):
    app = _authz_app()
    ctx = TenantContext(
        session=db,
        user=AuthedUser(
            id=_uuid.uuid4(), tenant_id=tenant_ctx.tenant_id, role_code="x", is_platform_admin=False
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="x",
        permission_codes=perms,
    )

    async def _db():
        yield db

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=20
    ) as client:
        return await client.request(method, path, json=body)


async def test_the_route_creates_a_product_with_a_season(db, tenant_ctx) -> None:
    r = await _call(
        db,
        tenant_ctx,
        "POST",
        "/api/v1/products",
        perms=WRITE,
        body={"title": "Coat", "slug": f"c-{_uuid.uuid4().hex[:8]}", "season": "SS26"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["season"] == "SS26"


async def test_a_patch_with_null_season_clears_it_and_a_patch_without_it_leaves_it(
    db, tenant_ctx
) -> None:
    p = await _product(db, tenant_ctx.tenant_id, season="SS26")
    leave = await _call(
        db, tenant_ctx, "PATCH", f"/api/v1/products/{p.id}", perms=WRITE, body={"title": "New"}
    )
    assert leave.status_code == 200 and leave.json()["season"] == "SS26"
    clear = await _call(
        db, tenant_ctx, "PATCH", f"/api/v1/products/{p.id}", perms=WRITE, body={"season": None}
    )
    assert clear.status_code == 200 and clear.json()["season"] is None


async def test_a_season_that_is_too_long_is_a_422_not_a_500(db, tenant_ctx) -> None:
    p = await _product(db, tenant_ctx.tenant_id)
    r = await _call(
        db,
        tenant_ctx,
        "PATCH",
        f"/api/v1/products/{p.id}",
        perms=WRITE,
        body={"season": "x" * 41},
    )
    assert r.status_code == 422, r.text


async def test_the_list_route_filters_by_season(db, tenant_ctx) -> None:
    a = await _product(db, tenant_ctx.tenant_id, season="SS26")
    await _product(db, tenant_ctx.tenant_id, season="AW26")
    r = await _call(db, tenant_ctx, "GET", "/api/v1/products?season=SS26", perms=READ)
    assert r.status_code == 200, r.text
    ids = {row["id"] for row in r.json()}
    assert str(a.id) in ids
    assert all(row["season"] == "SS26" for row in r.json())

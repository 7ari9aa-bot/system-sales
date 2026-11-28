"""A product can carry its fabric, and the catalogue can be listed by it.

The material is owner data: a short label such as "قطن" or "cotton". It is optional, so a product
without one behaves exactly as it always did, and a shop that never records a fabric never sees it.
It sits next to the season and does not change how the season works.
"""

from __future__ import annotations

import uuid
import uuid as _uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.applications.apparel.modules.catalog.service import CatalogService
from app.platform.identity.deps import (
    AuthedUser,
    TenantContext,
    get_db,
    get_tenant_ctx,
)
from tests.security.test_role_authz_matrix import _authz_app

pytestmark = pytest.mark.asyncio

WRITE = {"products:write", "products:read"}
READ = {"products:read"}


async def _product(db, tid, **extra):
    return await CatalogService.create_product(
        db, tid, title="Shirt", slug=f"s-{uuid.uuid4().hex[:8]}", **extra
    )


async def test_a_product_has_no_material_unless_one_is_given(db, tenant_ctx) -> None:
    p = await _product(db, tenant_ctx.tenant_id)
    assert p.material is None


async def test_a_material_is_saved_on_create(db, tenant_ctx) -> None:
    p = await _product(db, tenant_ctx.tenant_id, material="Cotton")
    assert p.material == "Cotton"


async def test_a_material_can_be_set_changed_and_cleared(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    p = await _product(db, tid)
    p = await CatalogService.update_product(db, tid, p.id, material="Linen")
    assert p.material == "Linen"
    p = await CatalogService.update_product(db, tid, p.id, material=None)
    assert p.material is None


async def test_surrounding_spaces_are_dropped_and_an_empty_material_means_none(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    assert (await _product(db, tid, material="  Cotton  ")).material == "Cotton"
    assert (await _product(db, tid, material="   ")).material is None
    p = await _product(db, tid, material="Cotton")
    p = await CatalogService.update_product(db, tid, p.id, material="  ")
    assert p.material is None


async def test_a_material_of_exactly_the_limit_is_kept_and_one_more_is_refused(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    assert (await _product(db, tid, material="x" * 60)).material == "x" * 60
    with pytest.raises(ValueError, match="material"):
        await _product(db, tid, material="x" * 61)


async def test_an_update_that_does_not_mention_material_leaves_it_alone(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    p = await _product(db, tid, material="Cotton")
    p = await CatalogService.update_product(db, tid, p.id, title="Renamed")
    assert p.material == "Cotton"


async def test_listing_by_material_returns_only_that_material(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _product(db, tid, material="Cotton")
    b = await _product(db, tid, material="Linen")
    c = await _product(db, tid)
    got = {p.id for p in await CatalogService.list_products(db, tid, material="Cotton")}
    assert got == {a.id}
    everything = {p.id for p in await CatalogService.list_products(db, tid)}
    assert {a.id, b.id, c.id} <= everything


async def test_listing_by_material_ignores_case_and_spaces(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _product(db, tid, material="Cotton")
    got = {p.id for p in await CatalogService.list_products(db, tid, material=" cOTTON ")}
    assert got == {a.id}


async def test_a_blank_material_filter_means_no_filter(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    a = await _product(db, tid, material="Cotton")
    c = await _product(db, tid)
    got = {p.id for p in await CatalogService.list_products(db, tid, material="  ")}
    assert {a.id, c.id} <= got


async def test_material_and_season_filter_together_and_stay_independent(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    both = await _product(db, tid, season="SS26", material="Cotton")
    await _product(db, tid, season="SS26", material="Linen")
    await _product(db, tid, season="AW26", material="Cotton")
    got = {
        p.id for p in await CatalogService.list_products(db, tid, season="SS26", material="Cotton")
    }
    assert got == {both.id}
    only_season = await CatalogService.list_products(db, tid, season="SS26")
    assert len(only_season) == 2


async def test_another_shops_material_is_never_returned(db, tenant_ctx) -> None:
    """The filter sits on top of the tenant filter; it never replaces it."""
    tid = tenant_ctx.tenant_id
    await _product(db, tid, material="Cotton")
    got = await CatalogService.list_products(db, uuid.uuid4(), material="Cotton")
    assert got == []


async def test_the_product_the_api_returns_carries_its_material(db, tenant_ctx) -> None:
    from app.applications.apparel.modules.catalog.routers._deps import _product_out

    p = await _product(db, tenant_ctx.tenant_id, material="Cotton")
    assert _product_out(p, [])["material"] == "Cotton"
    q = await _product(db, tenant_ctx.tenant_id)
    assert _product_out(q, [])["material"] is None


# ── through the real routes ────────────────────────────────────────────────────────────────────


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


async def test_the_route_creates_a_product_with_a_material(db, tenant_ctx) -> None:
    r = await _call(
        db,
        tenant_ctx,
        "POST",
        "/api/v1/products",
        perms=WRITE,
        body={"title": "Shirt", "slug": f"s-{_uuid.uuid4().hex[:8]}", "material": "Cotton"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["material"] == "Cotton"


async def test_a_patch_with_null_material_clears_it_and_a_patch_without_it_leaves_it(
    db, tenant_ctx
) -> None:
    p = await _product(db, tenant_ctx.tenant_id, material="Cotton")
    leave = await _call(
        db, tenant_ctx, "PATCH", f"/api/v1/products/{p.id}", perms=WRITE, body={"title": "New"}
    )
    assert leave.status_code == 200 and leave.json()["material"] == "Cotton"
    clear = await _call(
        db, tenant_ctx, "PATCH", f"/api/v1/products/{p.id}", perms=WRITE, body={"material": None}
    )
    assert clear.status_code == 200 and clear.json()["material"] is None


async def test_a_material_that_is_too_long_is_a_422_not_a_500(db, tenant_ctx) -> None:
    p = await _product(db, tenant_ctx.tenant_id)
    r = await _call(
        db,
        tenant_ctx,
        "PATCH",
        f"/api/v1/products/{p.id}",
        perms=WRITE,
        body={"material": "x" * 61},
    )
    assert r.status_code == 422, r.text


async def test_the_list_route_filters_by_material(db, tenant_ctx) -> None:
    a = await _product(db, tenant_ctx.tenant_id, material="Cotton")
    await _product(db, tenant_ctx.tenant_id, material="Linen")
    r = await _call(db, tenant_ctx, "GET", "/api/v1/products?material=Cotton", perms=READ)
    assert r.status_code == 200, r.text
    ids = {row["id"] for row in r.json()}
    assert str(a.id) in ids
    assert all(row["material"] == "Cotton" for row in r.json())


async def test_a_material_that_is_too_long_on_create_is_a_422_not_a_500(db, tenant_ctx) -> None:
    r = await _call(
        db,
        tenant_ctx,
        "POST",
        "/api/v1/products",
        perms=WRITE,
        body={"title": "Shirt", "slug": f"s-{_uuid.uuid4().hex[:8]}", "material": "x" * 61},
    )
    assert r.status_code == 422, r.text


async def test_the_model_and_the_database_agree_about_the_material_column(db) -> None:
    """The model says nullable and 60 long; the migrated table must say the same.

    The migration drift test only checks that a column exists. A model that quietly became
    NOT NULL would still pass it while every product without a fabric failed to save.
    """
    from sqlalchemy import text

    from app.applications.apparel.modules.catalog.models import Product

    column = Product.__table__.c.material
    assert column.nullable is True
    assert column.type.length == 60
    row = (
        await db.execute(
            text(
                "select is_nullable, character_maximum_length from information_schema.columns "
                "where table_name = 'products' and column_name = 'material'"
            )
        )
    ).one()
    assert row[0] == "YES"
    assert row[1] == 60

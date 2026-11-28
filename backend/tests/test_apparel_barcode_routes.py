"""Barcode assignment and the label print page, through the real routes on a real database."""

from __future__ import annotations

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.applications.apparel.modules.catalog.apparel.service import ApparelMatrixService as M
from app.applications.apparel.modules.catalog.service import CatalogService
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from tests.security.test_role_authz_matrix import _authz_app

pytestmark = pytest.mark.asyncio


def _ctx(db, tenant_ctx, perms: set[str]) -> TenantContext:
    return TenantContext(
        session=db,
        user=AuthedUser(
            id=uuid.uuid4(),
            tenant_id=tenant_ctx.tenant_id,
            role_code="x",
            is_platform_admin=False,
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="x",
        permission_codes=perms,
    )


async def _call(db, tenant_ctx, method: str, path: str, *, perms: set[str], body=None):
    app = _authz_app()
    ctx = _ctx(db, tenant_ctx, perms)

    async def _db():
        yield db

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=20
    ) as client:
        return await client.request(method, path, json=body)


async def _garment(db, tenant_ctx):
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="قميص <كتان>", slug=f"r-{uuid.uuid4().hex[:10]}"
    )
    made = await M.generate(
        db,
        tenant_ctx.tenant_id,
        product.id,
        sizes=["M", "L"],
        colors=["أسود"],
        price="249.5",
        sku_prefix=f"R{uuid.uuid4().hex[:4]}",
    )
    return product, [v.id for v in made.created]


WRITE = {"products:write", "products:read"}
READ = {"products:read"}


async def test_assigning_then_printing_gives_one_scannable_label_per_variant(
    db, tenant_ctx
) -> None:
    product, ids = await _garment(db, tenant_ctx)
    made = await _call(
        db, tenant_ctx, "POST", f"/api/v1/products/{product.id}/barcodes", perms=WRITE, body={}
    )
    assert made.status_code == 201, made.text
    out = made.json()
    assert out["assigned"] == 2 and out["already_had_one"] == 0 and len(out["codes"]) == 2

    page = await _call(
        db, tenant_ctx, "GET", f"/api/v1/products/{product.id}/labels?copies=3", perms=READ
    )
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert page.headers["cache-control"] == "no-store"
    assert page.text.count("<svg") == 6  # 2 variants x 3 copies
    for code in out["codes"].values():
        assert page.text.count(f">{code}</text>") == 3
    assert "@page{size:50.0mm 30.0mm;margin:0}" in page.text


async def test_the_product_name_cannot_inject_markup_into_the_print_page(db, tenant_ctx) -> None:
    product, _ = await _garment(db, tenant_ctx)  # titled "قميص <كتان>"
    await _call(
        db, tenant_ctx, "POST", f"/api/v1/products/{product.id}/barcodes", perms=WRITE, body={}
    )
    page = await _call(db, tenant_ctx, "GET", f"/api/v1/products/{product.id}/labels", perms=READ)
    assert "<كتان>" not in page.text and "&lt;كتان&gt;" in page.text


async def test_printing_refuses_while_any_variant_has_no_barcode(db, tenant_ctx) -> None:
    product, _ = await _garment(db, tenant_ctx)
    page = await _call(db, tenant_ctx, "GET", f"/api/v1/products/{product.id}/labels", perms=READ)
    assert page.status_code == 409
    assert "svg" not in page.text  # never a blank or unscannable label


async def test_assigning_again_changes_nothing(db, tenant_ctx) -> None:
    product, _ = await _garment(db, tenant_ctx)
    path = f"/api/v1/products/{product.id}/barcodes"
    first = (await _call(db, tenant_ctx, "POST", path, perms=WRITE, body={})).json()
    again = (await _call(db, tenant_ctx, "POST", path, perms=WRITE, body={})).json()
    assert again["assigned"] == 0 and again["already_had_one"] == 2
    assert again["codes"] == first["codes"]


async def test_a_subset_can_be_labelled_and_printed(db, tenant_ctx) -> None:
    product, ids = await _garment(db, tenant_ctx)
    path = f"/api/v1/products/{product.id}/barcodes"
    one = await _call(
        db, tenant_ctx, "POST", path, perms=WRITE, body={"variant_ids": [str(ids[0])]}
    )
    assert one.json()["assigned"] == 1
    page = await _call(
        db,
        tenant_ctx,
        "GET",
        f"/api/v1/products/{product.id}/labels?variant_id={ids[0]}",
        perms=READ,
    )
    assert page.status_code == 200 and page.text.count("<svg") == 1


async def test_a_variant_of_another_garment_is_refused(db, tenant_ctx) -> None:
    product, _ = await _garment(db, tenant_ctx)
    _, other_ids = await _garment(db, tenant_ctx)
    res = await _call(
        db,
        tenant_ctx,
        "POST",
        f"/api/v1/products/{product.id}/barcodes",
        perms=WRITE,
        body={"variant_ids": [str(other_ids[0])]},
    )
    assert res.status_code == 404


@pytest.mark.parametrize("query", ["size=huge", "copies=0", "copies=21"])
async def test_bad_print_options_are_refused(db, tenant_ctx, query: str) -> None:
    product, _ = await _garment(db, tenant_ctx)
    await _call(
        db, tenant_ctx, "POST", f"/api/v1/products/{product.id}/barcodes", perms=WRITE, body={}
    )
    page = await _call(
        db, tenant_ctx, "GET", f"/api/v1/products/{product.id}/labels?{query}", perms=READ
    )
    assert page.status_code in (400, 422)


async def test_the_barcode_numbers_are_unique_across_garments(db, tenant_ctx) -> None:
    a, _ = await _garment(db, tenant_ctx)
    b, _ = await _garment(db, tenant_ctx)
    ca = (
        await _call(
            db, tenant_ctx, "POST", f"/api/v1/products/{a.id}/barcodes", perms=WRITE, body={}
        )
    ).json()["codes"]
    cb = (
        await _call(
            db, tenant_ctx, "POST", f"/api/v1/products/{b.id}/barcodes", perms=WRITE, body={}
        )
    ).json()["codes"]
    allcodes = list(ca.values()) + list(cb.values())
    assert len(set(allcodes)) == 4 and all(re.fullmatch(r"2\d{12}", c) for c in allcodes)


async def test_an_unknown_garment_is_a_404(db, tenant_ctx) -> None:
    res = await _call(
        db, tenant_ctx, "POST", f"/api/v1/products/{uuid.uuid4()}/barcodes", perms=WRITE, body={}
    )
    assert res.status_code == 404

"""Catalog admin surface — the writes a merchandiser can actually reach.

Price tiers (`CatalogService.set_variant_price`), brands and categories all
existed as service methods WITH tests — and nothing but `tests/` ever called
them, because there was no route. A tenant could not set a quantity tier,
create a brand, or attach a gallery image through the API. `ProductImage` was
worse: no service method and no route either, so the table had zero writers.

The route guards here run without a database (OpenAPI only), which is the
point: they fail on a machine that cannot run the DB suite. The image tests
below are DB-backed and therefore CI-verified.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.catalog.service import CatalogService
from app.modules.errors import NotFoundError


def _body_properties(path: str, method: str = "post") -> set[str]:
    spec = create_app().openapi()
    schema = spec["paths"][path][method]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    name = schema["$ref"].rsplit("/", 1)[-1]
    return set(spec["components"]["schemas"][name]["properties"])


# ------------------------------------------------ routes on the wire ----


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/brands"),
        ("post", "/api/v1/categories"),
        ("post", "/api/v1/variants/{variant_id}/prices"),
        ("post", "/api/v1/products/{product_id}/images"),
        ("get", "/api/v1/products/{product_id}/images"),
    ],
)
def test_catalog_admin_route_is_mounted(method: str, path: str) -> None:
    paths = create_app().openapi()["paths"]
    assert path in paths, f"{path} is not mounted"
    assert method in paths[path]


def test_price_tier_route_takes_the_tier_fields() -> None:
    """A tier without its currency and minimum quantity is just a price."""
    assert {
        "unit_price",
        "currency",
        "min_quantity",
    } <= _body_properties("/api/v1/variants/{variant_id}/prices")


def test_category_route_can_name_a_parent() -> None:
    assert {"name", "parent_id"} <= _body_properties("/api/v1/categories")


# ------------------------------------------------ the gallery ----


async def _product(db: AsyncSession, tenant_id: uuid.UUID):
    return await CatalogService.create_product(
        db,
        tenant_id,
        title="Gallery Product",
        slug=f"gal-{uuid.uuid4().hex[:10]}",
    )


async def test_add_image_appends_in_position_order(db: AsyncSession, tenant_ctx):
    """The gallery is ordered, and the caller must not have to count rows to
    place one — position is derived from what the product already has."""
    tenant_id = tenant_ctx.tenant_id
    product = await _product(db, tenant_id)

    first = await CatalogService.add_image(
        db, tenant_id, product.id, url="https://cdn.test/1.jpg"
    )
    second = await CatalogService.add_image(
        db, tenant_id, product.id, url="https://cdn.test/2.jpg", alt="أزرق"
    )
    assert (first.position, second.position) == (0, 1)

    rows = await CatalogService.list_images(db, tenant_id, product.id)
    assert [r.position for r in rows] == [0, 1]
    assert [r.url for r in rows] == ["https://cdn.test/1.jpg", "https://cdn.test/2.jpg"]
    assert rows[1].alt == "أزرق"


async def test_add_image_refuses_a_product_that_is_not_there(
    db: AsyncSession, tenant_ctx
) -> None:
    with pytest.raises(NotFoundError):
        await CatalogService.add_image(
            db, tenant_ctx.tenant_id, uuid.uuid4(), url="https://cdn.test/1.jpg"
        )

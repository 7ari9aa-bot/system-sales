"""§161 CSV import — real call targets, and failures that cannot go green.

Mirror of the Shopify adapter fix: the importer used to call
``product_service.create()`` and ``customer_service.create_from_import()``,
methods that exist nowhere, and the bare per-row ``except Exception`` turned
that into a ``{imported: 0, errors: N}`` report nobody read. These tests pin
the product path against the REAL ``CatalogService`` surface with a spec
mock (any future call at a method the service does not define lands here as
a failed row), and pin the verdict: a run with a failed or refused row is
never reported as success.

DB-backed cases SKIP locally without ``DATABASE_URL_APP_ADMIN`` and run in CI;
the pure cases must fail locally the moment the pipeline drifts.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.external.csv_import import CSVImportService
from app.modules.catalog.models import Product, ProductVariant
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")

_PRODUCTS_CSV = (
    "title,slug,description,price,sku,status\n"
    "Koshari Bowl,koshari-bowl,rice and pasta,19.99,KB-1,active\n"
)


def _session() -> AsyncMock:
    return AsyncMock()


# --------------------------------------------- pure: the call target is real ----
async def test_product_row_reaches_the_catalog_upsert_contract() -> None:
    """The pipeline must hand each row to a method CatalogService defines."""
    service = AsyncMock(spec=CatalogService)

    report = await CSVImportService.import_products(
        _session(), TENANT, raw_csv=_PRODUCTS_CSV, product_service=service
    )

    assert report.imported == 1, (
        f"the importer called a method the real service does not define: "
        f"{report.error_details}"
    )
    assert report.errors == 0 and report.success
    service.upsert_from_external.assert_awaited_once()
    kwargs = service.upsert_from_external.await_args.kwargs
    assert kwargs["source"] == "csv"
    assert kwargs["external_ref"] == "koshari-bowl"
    assert kwargs["data"]["title"] == "Koshari Bowl"
    assert kwargs["data"]["variants"][0]["price"] == "19.99"
    assert kwargs["data"]["variants"][0]["sku"] == "KB-1"


async def test_a_service_refusal_is_a_conflict_not_a_lost_row() -> None:
    service = AsyncMock(spec=CatalogService)
    service.upsert_from_external.side_effect = ConflictError(
        "this tenant prices in EGP; a USD amount never sells"
    )

    report = await CSVImportService.import_products(
        _session(), TENANT, raw_csv=_PRODUCTS_CSV, product_service=service
    )

    assert report.imported == 0
    assert report.conflicts == 1
    assert not report.success


async def test_every_failed_row_makes_the_run_not_green() -> None:
    """The defect class: N failed rows next to a report that reads as done."""
    service = AsyncMock(spec=CatalogService)
    service.upsert_from_external.side_effect = RuntimeError("db is down")

    report = await CSVImportService.import_products(
        _session(), TENANT, raw_csv=_PRODUCTS_CSV, product_service=service
    )

    assert report.errors == 1 and report.imported == 0
    assert report.success is False
    assert report.error_details[0]["row"] == 1


async def test_one_bad_row_among_good_ones_is_still_visible() -> None:
    service = AsyncMock(spec=CatalogService)
    service.upsert_from_external.side_effect = [None, ValueError("bad price")]
    csv = _PRODUCTS_CSV + "Foul Mudammas,foul-mudammas,,abc,FM-1,active\n"

    report = await CSVImportService.import_products(
        _session(), TENANT, raw_csv=csv, product_service=service
    )

    assert report.imported == 1 and report.errors == 1
    assert report.success is False


async def test_row_declaring_an_unstorable_currency_is_refused_before_write() -> None:
    """KWD is three-decimal; NUMERIC(14,2) would round every price on write."""
    service = AsyncMock(spec=CatalogService)
    csv = "title,slug,price,currency\nFoul,foul,2.500,KWD\n"

    report = await CSVImportService.import_products(
        _session(), TENANT, raw_csv=csv, product_service=service
    )

    assert report.imported == 0 and report.conflicts == 1
    assert not report.success
    service.upsert_from_external.assert_not_awaited()


# ------------------------------------------- pure: the customer half refuses ----
async def test_customer_import_refuses_naming_the_missing_method() -> None:
    """NotImplementedError beats an AttributeError swallowed into a report."""
    with pytest.raises(NotImplementedError) as excinfo:
        await CSVImportService.import_customers(
            _session(),
            TENANT,
            raw_csv="name\nAisha\n",
            customer_service=object(),
        )
    assert "create_from_import" in str(excinfo.value)


async def test_customer_import_delegates_when_the_method_exists() -> None:
    """Pinned for the day CustomerService owns the intake: one call per row."""

    class _Stub:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def create_from_import(
            self, session: Any, tenant_id: Any, **kwargs: Any
        ) -> None:
            self.calls.append(kwargs)

    stub = _Stub()
    report = await CSVImportService.import_customers(
        _session(),
        TENANT,
        raw_csv="name,email\nAisha,a@x.com\n",
        customer_service=stub,
    )

    assert report.imported == 1 and report.success
    assert stub.calls[0]["name"] == "Aisha"


# ---------------------------------------------------------- end to end (DB) ----
async def _products(db: AsyncSession, tenant_id: uuid.UUID) -> list[Product]:
    return list(
        (await db.execute(select(Product).where(Product.tenant_id == tenant_id)))
        .scalars()
        .all()
    )


async def test_csv_product_row_lands_as_a_real_product(db: AsyncSession, tenant_ctx) -> None:
    """End to end through the real CatalogService: not 'imported 0, errors 1'."""
    tenant_id = tenant_ctx.tenant_id

    report = await CSVImportService.import_products(
        db, tenant_id, raw_csv=_PRODUCTS_CSV, product_service=None
    )
    await db.flush()

    assert report.imported == 1 and report.success, report.error_details
    (product,) = await _products(db, tenant_id)
    assert product.slug == "koshari-bowl"
    assert product.status == "active"
    assert product.attributes["_source"] == "csv"
    assert product.attributes["_external_id"] == "koshari-bowl"
    variant = (
        await db.execute(
            select(ProductVariant).where(ProductVariant.tenant_id == tenant_id)
        )
    ).scalar_one()
    assert variant.sku == "KB-1"
    assert variant.price == Decimal("19.99")


async def test_reuploaded_csv_updates_the_row_it_already_owns(
    db: AsyncSession, tenant_ctx
) -> None:
    """The import path and the Shopify path share one upsert — no duplicates."""
    tenant_id = tenant_ctx.tenant_id
    await CSVImportService.import_products(
        db, tenant_id, raw_csv=_PRODUCTS_CSV, product_service=None
    )
    renamed = _PRODUCTS_CSV.replace("Koshari Bowl", "Koshari Bowl, large").replace(
        "19.99", "17.50"
    )

    report = await CSVImportService.import_products(
        db, tenant_id, raw_csv=renamed, product_service=None
    )
    await db.flush()

    assert report.imported == 1 and report.success
    products = await _products(db, tenant_id)
    assert len(products) == 1
    assert products[0].title == "Koshari Bowl, large"
    variant = (
        await db.execute(
            select(ProductVariant).where(ProductVariant.tenant_id == tenant_id)
        )
    ).scalar_one()
    assert variant.price == Decimal("17.50")


async def test_foreign_currency_row_writes_nothing(db: AsyncSession, tenant_ctx) -> None:
    """§47: a CSV row in another shop's money is refused, not relabelled."""
    tenant_id = tenant_ctx.tenant_id
    csv = "title,slug,price,currency\nFoul,foul-mudammas,4.00,USD\n"

    report = await CSVImportService.import_products(
        db, tenant_id, raw_csv=csv, product_service=None
    )
    await db.flush()

    assert report.imported == 0 and report.conflicts == 1
    assert not report.success
    assert await _products(db, tenant_id) == []

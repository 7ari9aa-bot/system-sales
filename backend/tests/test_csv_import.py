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
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.catalog.external.csv_import import CSVImportService
from app.modules.catalog.models import Product, ProductVariant
from app.modules.catalog.service import CatalogService
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

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
        f"the importer called a method the real service does not define: {report.error_details}"
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


# --------------------------------------- pure: the customer half is live ----
async def test_customer_import_uses_the_real_service_surface() -> None:
    """The pipeline must call a method CustomerService ACTUALLY defines.

    ``AsyncMock(spec=CustomerService)`` is the mirror of the product-path pin:
    any attribute the importer reaches that the real class does not define
    lands here as an ``AttributeError`` (a failed row), never a silently green
    report. ``create_from_import`` therefore has to exist on the production
    ``CustomerService``, with the exact call shape the pipeline sends.
    """
    service = AsyncMock(spec=CustomerService)

    report = await CSVImportService.import_customers(
        _session(),
        TENANT,
        raw_csv="name,email,phone,tags\nAisha,a@x.com,+201001234567,vip\n",
        customer_service=service,
    )

    assert report.imported == 1 and report.success, report.error_details
    service.create_from_import.assert_awaited_once()
    args, kwargs = service.create_from_import.await_args
    # session + tenant positional, then the documented keyword contract — the
    # pipeline passes each CSV value UNCHANGED (it only strips blanks).
    assert args[1] == TENANT
    assert kwargs == {
        "name": "Aisha",
        "email": "a@x.com",
        "phone": "+201001234567",
        "source": "csv_import",
        "tags": "vip",
    }


async def test_customer_import_guard_still_refuses_a_service_without_intake() -> None:
    """The loud refusal is only for a caller that has no create_from_import.

    ``object()`` is not a CustomerService; a NotImplementedError still beats an
    AttributeError swallowed into a report. (The real service now HAS the
    method — the previous test pinned the ORPHAN state, which no longer holds.)
    """
    with pytest.raises(NotImplementedError) as excinfo:
        await CSVImportService.import_customers(
            _session(),
            TENANT,
            raw_csv="name\nAisha\n",
            customer_service=object(),
        )
    assert "create_from_import" in str(excinfo.value)


async def test_real_customer_service_now_owns_the_intake() -> None:
    """The hard refusal is gone: the production class defines the method."""
    assert hasattr(CustomerService, "create_from_import")


async def test_customer_import_delegates_when_the_method_exists() -> None:
    """The documented per-row call shape: one create_from_import per row."""

    class _Stub:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def create_from_import(self, session: Any, tenant_id: Any, **kwargs: Any) -> None:
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


async def test_customer_import_conflict_is_a_conflict_not_a_generic_error() -> None:
    """A domain refusal raises ConflictError so the pipeline surfaces it.

    The generic ``except Exception`` branch would fold a duplicate into
    ``errors``; a CSV row that collides with an existing customer must land in
    ``conflicts`` instead, and the run must not read green.
    """
    service = AsyncMock(spec=CustomerService)
    service.create_from_import.side_effect = ConflictError("phone already exists")

    report = await CSVImportService.import_customers(
        _session(),
        TENANT,
        raw_csv="name,phone\nAisha,+201001234567\n",
        customer_service=service,
    )

    assert report.imported == 0
    assert report.conflicts == 1
    assert report.errors == 0
    assert not report.success


# ---------------------------------------------------------- end to end (DB) ----
async def _products(db: AsyncSession, tenant_id: uuid.UUID) -> list[Product]:
    return list(
        (await db.execute(select(Product).where(Product.tenant_id == tenant_id))).scalars().all()
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
        await db.execute(select(ProductVariant).where(ProductVariant.tenant_id == tenant_id))
    ).scalar_one()
    assert variant.sku == "KB-1"
    assert variant.price == Decimal("19.99")


async def test_reuploaded_csv_updates_the_row_it_already_owns(db: AsyncSession, tenant_ctx) -> None:
    """The import path and the Shopify path share one upsert — no duplicates."""
    tenant_id = tenant_ctx.tenant_id
    await CSVImportService.import_products(
        db, tenant_id, raw_csv=_PRODUCTS_CSV, product_service=None
    )
    # Quoted, because the new title carries a comma: an unquoted one shifts
    # every column right and the row fails on "price" for the wrong reason.
    renamed = _PRODUCTS_CSV.replace("Koshari Bowl", '"Koshari Bowl, large"').replace(
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
        await db.execute(select(ProductVariant).where(ProductVariant.tenant_id == tenant_id))
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


# --------------------------------------- DB: the REAL CustomerService intake ----
async def _customers(db: AsyncSession, tenant_id: uuid.UUID) -> list[Customer]:
    return list(
        (await db.execute(select(Customer).where(Customer.tenant_id == tenant_id))).scalars().all()
    )


async def test_create_from_import_lands_a_real_normalized_customer(
    db: AsyncSession, tenant_ctx
) -> None:
    """The fake in the delegation test must not hide a broken production method.

    This drives the REAL ``CustomerService.create_from_import``: a local-format
    phone is stored CANONICAL (ADR-056), the source rides the row, and the
    comma-separated tags become tag links.
    """
    tenant_id = tenant_ctx.tenant_id

    customer = await CustomerService.create_from_import(
        db,
        tenant_id,
        name="Sameh",
        email="  Sameh@Example.COM ",
        phone="01001234567",
        source="csv_import",
        tags="vip,wholesale",
    )
    await db.flush()

    assert customer.phone == "+201001234567"
    assert customer.email == "sameh@example.com"
    assert (customer.extra or {}).get("source") == "csv_import"
    tags = await CustomerService.list_tags(db, tenant_id, customer.id)
    assert {t.name for t in tags} == {"vip", "wholesale"}


async def test_create_from_import_refuses_a_normalised_phone_duplicate(
    db: AsyncSession, tenant_ctx
) -> None:
    """A CSV row cannot clone a customer the API path already refuses.

    The first row is typed in local format (stored canonical ``+20…``); the
    second is the international spelling of the SAME number. Identity
    resolution must catch it and raise ``ConflictError`` — the one exception the
    pipeline surfaces as a visible conflict, not a generic error.
    """
    tenant_id = tenant_ctx.tenant_id
    await CustomerService.create_from_import(
        db,
        tenant_id,
        name="Sameh",
        phone="01001234567",
        source="csv_import",
        tags=None,
    )
    await db.flush()

    with pytest.raises(ConflictError):
        await CustomerService.create_from_import(
            db,
            tenant_id,
            name="Sameh Again",
            phone="+20 100 123 4567",
            source="csv_import",
            tags=None,
        )

    # The refused row wrote nothing.
    assert len(await _customers(db, tenant_id)) == 1


async def test_csv_customer_row_lands_through_the_real_service(
    db: AsyncSession, tenant_ctx
) -> None:
    """End to end through the real CustomerService: not 'imported 0, errors 1'."""
    tenant_id = tenant_ctx.tenant_id

    report = await CSVImportService.import_customers(
        db,
        tenant_id,
        raw_csv="name,email,phone\nAisha,a@x.com,01001234567\n",
        customer_service=CustomerService,
    )
    await db.flush()

    assert report.imported == 1 and report.success, report.error_details
    (customer,) = await _customers(db, tenant_id)
    assert customer.name == "Aisha"
    assert customer.phone == "+201001234567"


async def test_csv_reupload_collides_on_the_normalised_number(db: AsyncSession, tenant_ctx) -> None:
    """Second run, same human spelled differently: a conflict, never a clone."""
    tenant_id = tenant_ctx.tenant_id
    await CSVImportService.import_customers(
        db,
        tenant_id,
        raw_csv="name,phone\nAisha,01001234567\n",
        customer_service=CustomerService,
    )
    await db.flush()

    report = await CSVImportService.import_customers(
        db,
        tenant_id,
        raw_csv="name,phone\nAisha,+201001234567\n",
        customer_service=CustomerService,
    )

    assert report.imported == 0 and report.conflicts == 1
    assert not report.success
    assert len(await _customers(db, tenant_id)) == 1


# ------------------------------------- route: parse → resolve → create → status ----
def test_import_intake_routes_are_mounted() -> None:
    """The pipeline is reachable from the composition root without a database.

    OpenAPI-only: this proves ``app.main`` wires the ``/imports/*`` intake (and
    so transitively imports ``csv_import``) on any machine, including one that
    cannot run the DB-backed cases below.
    """
    paths = create_app().openapi()["paths"]
    assert "/api/v1/imports/customers" in paths, "customer import has no route"
    assert "/api/v1/imports/products" in paths, "product import has no route"


def _write_ctx(
    session: AsyncSession, tenant_id: uuid.UUID, actor_user_id: uuid.UUID
) -> TenantContext:
    """The owner's request context.

    ``actor_user_id`` MUST be a persisted ``users.id``: the import routes append
    one audit row per run (§66, ``catalog/router._audit_import``) on BOTH the
    green and the conflicted verdict, and ``audit_logs.actor_user_id`` carries a
    foreign key to ``users``. A fabricated id is a CI-only
    ForeignKeyViolationError.
    """
    return TenantContext(
        session=session,
        user=AuthedUser(id=actor_user_id, tenant_id=tenant_id, role_code="owner"),
        tenant_id=tenant_id,
        role_code="owner",
        permission_codes={"customers:write", "products:write"},
    )


def _app(session: AsyncSession, tenant_id: uuid.UUID, actor_user_id: uuid.UUID):
    app = create_app()
    ctx = _write_ctx(session, tenant_id, actor_user_id)

    async def _override() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _override
    return app


async def _post_import(app, path: str, csv: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json={"csv": csv})


async def test_customer_import_route_drives_the_whole_path(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    app = _app(db, tenant_id, tenant_ctx.user.id)

    response = await _post_import(
        app, "/api/v1/imports/customers", "name,phone\nAisha,01001234567\n"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1 and body["success"] is True
    (customer,) = await _customers(db, tenant_id)
    assert customer.phone == "+201001234567"


async def test_customer_import_route_conflict_is_not_a_green_lie(
    db: AsyncSession, tenant_ctx
) -> None:
    """A row colliding by NORMALISED phone → non-2xx + per-row error_details.

    The stored customer was first written in local format (canonicalised on
    store); the CSV row arrives as an ``+20`` value for the SAME number. The
    run must not report 200-green, and the merchant must get back the row that
    clashed.
    """
    tenant_id = tenant_ctx.tenant_id
    await CustomerService.create_from_import(
        db,
        tenant_id,
        name="Aisha",
        phone="01001234567",
        source="csv_import",
        tags=None,
    )
    await db.flush()
    app = _app(db, tenant_id, tenant_ctx.user.id)

    response = await _post_import(
        app,
        "/api/v1/imports/customers",
        "name,phone\nAisha Clone,+20 100 123 4567\n",
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["conflicts"] == 1 and body["success"] is False
    assert body["error_details"][0]["row"] == 1


async def test_product_import_route_is_reachable(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    app = _app(db, tenant_id, tenant_ctx.user.id)

    response = await _post_import(app, "/api/v1/imports/products", _PRODUCTS_CSV)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1 and body["success"] is True


async def test_import_route_requires_write_permission(db: AsyncSession, tenant_ctx) -> None:
    app = create_app()
    # The fabricated id is deliberate and safe HERE and only here: the refusal
    # happens in the require_permission DEPENDENCY (no membership, no route
    # body, no audit row; the DomainError handler in app.main writes nothing
    # to audit_logs), so the actor never reaches the FK.
    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_ctx.tenant_id, role_code="viewer"),
        tenant_id=tenant_ctx.tenant_id,
        role_code="viewer",
        permission_codes=set(),
    )

    async def _override() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/imports/customers", json={"csv": "name\nAisha\n"})
    assert response.status_code == 403

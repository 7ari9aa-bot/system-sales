"""DB-free tests for the CRM CRUD surface (customers + catalog).

The DB-backed behaviour lives in ``test_customers_service.py`` /
``test_catalog_service.py`` and CI; these tests cover what is pure: route
mounting, service-level input validation that must fail before any session is
touched, and the request-body constraints the routers rely on.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.catalog.router import AddVariantRequest, UpdateVariantRequest
from app.modules.catalog.service import CatalogService
from app.modules.customers.router import NoteBody, TagBody
from app.modules.customers.service import CustomerService

# --------------------------------------------------------- route mounting -


def test_crm_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    expected = {
        "/api/v1/customers",
        "/api/v1/customers/{customer_id}",
        "/api/v1/customers/{customer_id}/block",
        "/api/v1/customers/{customer_id}/unblock",
        "/api/v1/customers/{customer_id}/archive",
        "/api/v1/customers/{customer_id}/tags",
        "/api/v1/customers/{customer_id}/tags/{tag_name}",
        "/api/v1/customers/{customer_id}/notes",
        "/api/v1/products",
        "/api/v1/products/{product_id}",
        "/api/v1/products/{product_id}/archive",
        "/api/v1/products/{product_id}/variants",
        "/api/v1/variants/{variant_id}",
        "/api/v1/categories",
        "/api/v1/brands",
        "/api/v1/warehouses",
    }
    assert expected <= paths


def test_warehouse_route_is_not_duplicated() -> None:
    """Only the catalog read-only list may expose /warehouses."""
    paths = [p for p in create_app().openapi()["paths"] if p.endswith("/warehouses")]
    assert paths == ["/api/v1/warehouses"]


# ------------------------------------------- service validation (no DB) ----


async def test_customer_update_rejects_unknown_fields_without_db() -> None:
    with pytest.raises(ValidationError):
        await CustomerService.update_customer(
            None,  # type: ignore[arg-type] — raises before the session is used
            uuid.uuid4(),
            uuid.uuid4(),
            nope=1,
        )


async def test_product_update_rejects_unknown_fields_without_db() -> None:
    with pytest.raises(ValueError):
        await CatalogService.update_product(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            uuid.uuid4(),
            nope=1,
        )


async def test_product_update_rejects_bad_status_without_db() -> None:
    with pytest.raises(ValueError):
        await CatalogService.update_product(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            uuid.uuid4(),
            status="not-a-status",
        )


async def test_variant_update_rejects_unknown_fields_without_db() -> None:
    with pytest.raises(ValidationError):
        await CatalogService.update_variant(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            uuid.uuid4(),
            nope=1,
        )


# ---------------------------------------------------- request-body rules ---


@pytest.mark.parametrize("body_model", [TagBody, NoteBody])
def test_empty_bodies_are_rejected(body_model) -> None:
    """Tag/note bodies carry min_length=1 so blank writes never reach the DB."""
    field = "name" if body_model is TagBody else "body"
    with pytest.raises(PydanticValidationError):
        body_model(**{field: ""})


def test_variant_price_must_be_positive() -> None:
    with pytest.raises(PydanticValidationError):
        AddVariantRequest(price=0)
    with pytest.raises(PydanticValidationError):
        AddVariantRequest(price=-1)
    with pytest.raises(PydanticValidationError):
        UpdateVariantRequest(price=-5)
    assert UpdateVariantRequest(price="12.50").price is not None

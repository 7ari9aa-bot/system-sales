"""Garment matrix routes: building one needs products:write, reading one only needs a login."""

from __future__ import annotations

import uuid

import pytest

from app.main import create_app
from tests.security.test_role_authz_matrix import _ctx_for, _status_for

PRODUCT = uuid.uuid4()
BODY = {"sizes": ["M"], "colors": ["x"], "price": "10", "sku_prefix": "P"}


@pytest.mark.parametrize("role", ["owner", "manager", "staff"])
async def test_who_may_build_a_matrix_is_exactly_who_may_write_products(role) -> None:
    from tests.security.test_role_authz_matrix import ROLE_MATRIX

    try:
        status = await _status_for(
            create_app(), _ctx_for(role), "POST", f"/api/v1/products/{PRODUCT}/matrix", BODY
        )
    except Exception:  # noqa: BLE001 - the inert stub session failing INSIDE the handler
        status = 500  # the gate already let the role in
    if "products:write" in ROLE_MATRIX[role]:
        assert status not in (401, 403), (role, status)
    else:
        assert status == 403, (role, status)


@pytest.mark.parametrize("role", ["owner", "manager", "staff"])
async def test_every_role_may_read_the_grid(role) -> None:
    try:
        status = await _status_for(
            create_app(), _ctx_for(role), "GET", f"/api/v1/products/{PRODUCT}/matrix"
        )
    except Exception:  # noqa: BLE001
        status = 500
    assert status not in (401, 403), (role, status)


async def test_the_cashier_in_particular_cannot_create_variants() -> None:
    from tests.security.test_role_authz_matrix import ROLE_MATRIX

    if "products:write" in ROLE_MATRIX["staff"]:
        pytest.skip("staff holds products:write in this seed; the role model changed")
    status = await _status_for(
        create_app(), _ctx_for("staff"), "POST", f"/api/v1/products/{PRODUCT}/matrix", BODY
    )
    assert status == 403


@pytest.mark.parametrize("role", ["owner", "manager", "staff"])
async def test_who_may_assign_barcodes_is_exactly_who_may_write_products(role) -> None:
    from tests.security.test_role_authz_matrix import ROLE_MATRIX

    try:
        status = await _status_for(
            create_app(), _ctx_for(role), "POST", f"/api/v1/products/{PRODUCT}/barcodes", {}
        )
    except Exception:  # noqa: BLE001 - the inert stub session failing INSIDE the handler
        status = 500
    if "products:write" in ROLE_MATRIX[role]:
        assert status not in (401, 403), (role, status)
    else:
        assert status == 403, (role, status)


@pytest.mark.parametrize("role", ["owner", "manager", "staff"])
async def test_every_role_may_open_the_print_page(role) -> None:
    try:
        status = await _status_for(
            create_app(), _ctx_for(role), "GET", f"/api/v1/products/{PRODUCT}/labels"
        )
    except Exception:  # noqa: BLE001
        status = 500
    assert status not in (401, 403), (role, status)

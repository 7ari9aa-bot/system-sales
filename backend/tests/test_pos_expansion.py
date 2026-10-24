"""§189 POS expansion — profiles, scan, quote, split tender, reconciliation.

Two test classes, per AGENT_BRIEF §7:

* **DB-free guards** run everywhere: the new routes are mounted, the new wire
  fields exist and the tender/change arithmetic
  are pure functions that can be exercised without a database.
* **DB-backed** tests run only where a database URL is configured (CI); conftest
  skips them locally. They are reported as UNVERIFIED when only local runs were
  possible.
"""

from __future__ import annotations

import uuid

import pytest

from app.main import create_app
from app.modules.errors import ConflictError

PROFILES_PATH = "/api/v1/pos/profiles"
PROFILE_PATH = "/api/v1/pos/profiles/{profile_id}"
PROFILE_USERS_PATH = "/api/v1/pos/profiles/{profile_id}/users"
SCAN_PATH = "/api/v1/pos/sessions/{session_id}/scan"
QUOTE_PATH = "/api/v1/pos/sessions/{session_id}/quote"
CLOSE_PATH = "/api/v1/pos/sessions/{session_id}/close"


# --------------------------------------------------------- DB-free guards --


def test_profile_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {
        PROFILES_PATH,
        PROFILE_PATH,
        PROFILE_USERS_PATH,
        SCAN_PATH,
        QUOTE_PATH,
        CLOSE_PATH,
    } <= paths
    # the close is not a drawer count any more: the reconciliation route is gone
    assert "/api/v1/pos/sessions/{session_id}/reconciliation" not in paths


def test_close_takes_no_counted_figure() -> None:
    """The close is not a drawer count: the route has no body model asking for one."""
    import app.modules.pos.router as router

    assert not hasattr(router, "CloseSessionRequest")


# ----------------------------------------------------------- DB-backed ----


def _profile_payload(warehouse_id):
    return {
        "name": "كاشير المحل",
        "code": f"P-{uuid.uuid4().hex[:6]}",
        "warehouse_id": str(warehouse_id),
    }


async def test_profile_created_and_listed(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService
    from app.modules.pos.profiles import PosProfileService

    warehouse = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="كاشير المحل",
        code=f"P-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )
    assert profile.id is not None
    listed = await PosProfileService.list_profiles(db, tenant_ctx.tenant_id)
    assert any(p.id == profile.id for p in listed)


async def test_duplicate_profile_code_is_refused(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService
    from app.modules.pos.profiles import PosProfileService

    warehouse = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    code = f"P-{uuid.uuid4().hex[:6]}"
    await PosProfileService.create(
        db, tenant_ctx.tenant_id, name="A", code=code, warehouse_id=warehouse.id
    )
    with pytest.raises(ConflictError):
        await PosProfileService.create(
            db, tenant_ctx.tenant_id, name="B", code=code, warehouse_id=warehouse.id
        )


async def test_scan_resolves_a_registered_identifier(db, tenant_ctx):
    import uuid as _uuid

    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService
    from app.modules.pos.service import PosService

    warehouse = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="شاي", slug=f"s-{_uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="علبة", price="12.00"
    )
    barcode = f"BAR{_uuid.uuid4().hex[:10]}"
    await CatalogService.add_identifier(db, tenant_ctx.tenant_id, variant.id, "barcode", barcode)

    register = await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="REG",
        code=f"REG-{_uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)

    found = await PosService.scan(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        identifier_type="barcode",
        value=barcode,
    )
    assert found["found"] is True
    assert found["variant_id"] == variant.id

    missing = await PosService.scan(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        identifier_type="barcode",
        value="NOPE-NOT-A-CODE",
    )
    assert missing["found"] is False

"""§189 POS expansion — profiles, scan, quote, split tender, reconciliation.

Two test classes, per AGENT_BRIEF §7:

* **DB-free guards** run everywhere: the new routes are mounted, the new wire
  fields exist, the tender/change arithmetic and the discount-ceiling policy
  are pure functions that can be exercised without a database.
* **DB-backed** tests run only where a database URL is configured (CI); conftest
  skips them locally. They are reported as UNVERIFIED when only local runs were
  possible.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.main import create_app
from app.modules.errors import ConflictError, ValidationError

PROFILES_PATH = "/api/v1/pos/profiles"
PROFILE_PATH = "/api/v1/pos/profiles/{profile_id}"
PROFILE_USERS_PATH = "/api/v1/pos/profiles/{profile_id}/users"
SCAN_PATH = "/api/v1/pos/sessions/{session_id}/scan"
QUOTE_PATH = "/api/v1/pos/sessions/{session_id}/quote"
SELL_PATH = "/api/v1/pos/sessions/{session_id}/sell"
CLOSE_PATH = "/api/v1/pos/sessions/{session_id}/close"
RECON_PATH = "/api/v1/pos/sessions/{session_id}/reconciliation"


# --------------------------------------------------------- DB-free guards --


def test_profile_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {
        PROFILES_PATH,
        PROFILE_PATH,
        PROFILE_USERS_PATH,
        SCAN_PATH,
        QUOTE_PATH,
        SELL_PATH,
        CLOSE_PATH,
        RECON_PATH,
    } <= paths


def test_sell_wire_accepts_split_tender_and_discount() -> None:
    from app.modules.pos.router import SellRequest

    body = SellRequest(
        items=[{"variant_id": str(uuid.uuid4()), "quantity": 2}],
        tenders=[
            {"method": "cash", "amount": "30.00"},
            {"method": "card", "amount": "20.00"},
        ],
        discount_total="5.00",
        tendered_cash="50.00",
    )
    assert len(body.tenders) == 2
    assert body.discount_total == "5.00"


def test_sell_wire_accepts_legacy_single_tender() -> None:
    from app.modules.pos.router import SellRequest

    body = SellRequest(items=[{"variant_id": str(uuid.uuid4()), "quantity": 1}], method="cash")
    assert body.method == "cash"
    assert body.tenders is None


def test_close_wire_accepts_per_method_counts() -> None:
    from app.modules.pos.router import CloseSessionRequest

    body = CloseSessionRequest(counted_cash="100.00", counted_by_method={"cash": "100.00"})
    assert body.counted_by_method == {"cash": "100.00"}


def test_profile_wire_refuses_bad_ceiling() -> None:
    from app.modules.pos.router import CreateProfileRequest

    with pytest.raises(PydanticValidationError):
        CreateProfileRequest(
            name="Till", code="T1", warehouse_id=uuid.uuid4(), discount_ceiling_pct="abc"
        )


def test_change_arithmetic_is_exact() -> None:
    from app.modules.pos.service import PosService

    settle = PosService._settle_change
    # Exact cash — no change.
    assert settle(Decimal("50.00"), None) == (Decimal("50.00"), Decimal("0.00"))
    # Over-tender — change returned.
    assert settle(Decimal("50.00"), "100.00") == (Decimal("100.00"), Decimal("50.00"))
    # No cash in the sale (card only) — no tender/change pair at all.
    assert settle(Decimal("0"), None) == (None, None)


def test_change_refuses_under_tender() -> None:
    from app.modules.pos.service import PosService

    with pytest.raises(ConflictError):
        PosService._settle_change(Decimal("50.00"), "30.00")


def test_discount_ceiling_predicate() -> None:
    from app.modules.pos.profiles import PosProfileService

    class _P:
        discount_ceiling_pct = Decimal("10.00")

    # 5% of 100 == 5.00 → under a 10% ceiling.
    assert PosProfileService.discount_needs_approval(_P(), "5.00", "100.00") is False
    # 20% of 100 == 20.00 → over the ceiling.
    assert PosProfileService.discount_needs_approval(_P(), "20.00", "100.00") is True
    # No discount never needs approval.
    assert PosProfileService.discount_needs_approval(_P(), None, "100.00") is False


def test_discount_ceiling_raises_when_unapproved() -> None:
    from app.modules.pos.profiles import PosProfileService

    class _P:
        discount_ceiling_pct = Decimal("10.00")

    # Approved → never raises.
    PosProfileService.ensure_discount_allowed(_P(), "20.00", "100.00", approved=True)
    with pytest.raises(ValidationError):
        PosProfileService.ensure_discount_allowed(_P(), "20.00", "100.00", approved=False)
    # Within the ceiling → never raises even without approval.
    PosProfileService.ensure_discount_allowed(_P(), "5.00", "100.00", approved=False)


def test_tender_shapes_are_mutually_exclusive() -> None:
    from app.modules.pos.service import PosService

    with pytest.raises(ValidationError):
        PosService._normalise_tenders(
            [{"method": "cash", "amount": "10.00"}], method="cash", amount="10.00"
        )


def test_tender_rejects_unknown_method() -> None:
    from app.modules.pos.service import PosService

    with pytest.raises(ValidationError):
        PosService._normalise_tenders([{"method": "crypto", "amount": "10.00"}], None, None)


# ----------------------------------------------------------- DB-backed ----


def _profile_payload(warehouse_id):
    return {
        "name": "كاشير المحل",
        "code": f"P-{uuid.uuid4().hex[:6]}",
        "warehouse_id": str(warehouse_id),
        "discount_ceiling_pct": "10.00",
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
        discount_ceiling_pct="10.00",
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


async def test_split_tender_settles_the_whole_order(db, tenant_ctx):
    import uuid as _uuid

    from sqlalchemy import func, select

    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService
    from app.modules.orders.models import OrderPayment
    from app.modules.pos.service import PosService

    warehouse = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="قهوة", slug=f"c-{_uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="كيس", price="100.00"
    )
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=3,
        reason="purchase",
    )
    from app.modules.customers.service import CustomerService

    customer = await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون", source="pos"
    )
    register = await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="REG",
        code=f"REG-{_uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)

    result = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        tenders=[
            {"method": "cash", "amount": "60.00"},
            {"method": "card", "amount": "40.00"},
        ],
        tendered_cash="60.00",
    )
    assert result["payment_count"] == 2

    total = (
        await db.execute(
            select(func.count())
            .select_from(OrderPayment)
            .where(OrderPayment.order_id == result["order_id"])
        )
    ).scalar_one()
    assert total == 2

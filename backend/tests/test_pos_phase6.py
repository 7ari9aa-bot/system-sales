"""§189 phases 4/5 — catalog scoping, derived return state, receipt email,
and the idempotent daily projection.

DB-free guards run everywhere; DB-backed tests run on CI and are reported
UNVERIFIED when only local runs were possible (AGENT_BRIEF §3a).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.main import create_app

EMAIL_PATH = "/api/v1/pos/receipts/{receipt_id}/email"
DAILY_PATH = "/api/v1/pos/reports/daily"


# --------------------------------------------------------- DB-free guards --


def test_phase6_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {EMAIL_PATH, DAILY_PATH} <= paths


def test_profile_wire_accepts_item_groups() -> None:
    from app.modules.pos.router import CreateProfileRequest

    body = CreateProfileRequest(
        name="مقسمة",
        code="P9",
        warehouse_id=uuid.uuid4(),
        item_group_ids=[str(uuid.uuid4())],
    )
    assert len(body.item_group_ids) == 1


# ----------------------------------------------------------- DB-backed -----


async def _warehouse(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService

    return await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)


async def _register(db, tenant_ctx):
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    return await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )


async def _sellable_variant(db, tenant_ctx, *, category_id=None, price="25.00", stock=5):
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    warehouse = await _warehouse(db, tenant_ctx)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="صنف", slug=f"p-{uuid.uuid4().hex[:10]}"
    )
    fields = {"status": "active"}
    if category_id is not None:
        fields["category_id"] = category_id
    product = await CatalogService.update_product(db, tenant_ctx.tenant_id, product.id, **fields)
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="وحدة", price=price
    )
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=stock,
        reason="purchase",
    )
    return variant


async def _customer(db, tenant_ctx):
    from app.modules.customers.service import CustomerService

    return await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون", source="pos"
    )


async def test_profile_scopes_scan_and_browse(db, tenant_ctx):
    from app.modules.catalog.service import CatalogService
    from app.modules.errors import ValidationError
    from app.modules.pos.profiles import PosProfileService
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    inside = await CatalogService.create_category(db, tenant_ctx.tenant_id, name="داخل النطاق")
    outside = await CatalogService.create_category(db, tenant_ctx.tenant_id, name="خارج النطاق")
    variant_in = await _sellable_variant(db, tenant_ctx, category_id=inside.id)
    variant_out = await _sellable_variant(db, tenant_ctx, category_id=outside.id)

    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="مقسمة",
        code=f"P-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
        item_group_ids=[str(inside.id)],
    )
    # A category the tenant does not have is refused — never a silent empty till.
    with pytest.raises(ValidationError):
        await PosProfileService.update(
            db,
            tenant_ctx.tenant_id,
            profile.id,
            item_group_ids=[str(uuid.uuid4())],
        )

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db,
        tenant_ctx.tenant_id,
        register.id,
        profile_id=profile.id,
        opened_by=tenant_ctx.user.id,
    )

    # The grid sees only the profile's category.
    page = await PosService.browse(db, tenant_ctx.tenant_id, pos_session.id)
    ids = {item["variant_id"] for item in page["items"]}
    assert str(variant_in.id) in ids
    assert str(variant_out.id) not in ids

    # The scan refuses outside the scope with the same discipline.
    barcode = f"OUT{uuid.uuid4().hex[:10]}"
    await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant_out.id, "barcode", barcode
    )
    refused = await PosService.scan(
        db, tenant_ctx.tenant_id, pos_session.id, identifier_type="barcode", value=barcode
    )
    assert refused["found"] is False
    assert "catalog" in refused["refusal"]


async def test_receipts_carry_derived_return_state(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx, price="25.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
    )

    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    receipts = await PosService.list_receipts(db, tenant_ctx.tenant_id, pos_session.id)
    sale_row = next(r for r in receipts if r["kind"] == "sale")
    assert sale_row["returned_units"] == 1
    assert Decimal(sale_row["refunded_total"]) == Decimal("25.00")

    detail = await PosService.get_receipt(db, tenant_ctx.tenant_id, sale_row["id"])
    line = detail["lines"][0]
    assert line["returned_qty"] == 1
    assert detail["order"]["fully_returned"] is False

    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    detail = await PosService.get_receipt(db, tenant_ctx.tenant_id, sale_row["id"])
    assert detail["order"]["fully_returned"] is True


async def test_receipt_email_queues_an_event_and_refuses_when_unconfigured(
    db, tenant_ctx, monkeypatch
):
    from app.core.config import Settings
    from app.core.events.schemas import DOMAIN_EVENT_TYPES
    from app.modules.errors import ValidationError
    from app.modules.platform.models import OutboxEvent
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx, price="10.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
    )

    # Unconfigured deployment: refused up front, never queued to retry forever.
    with pytest.raises(ValidationError):
        await PosService.request_receipt_email(
            db,
            tenant_ctx.tenant_id,
            sold["receipt_id"],
            email="customer@example.com",
            requested_by=tenant_ctx.user.id,
        )

    # Configured deployment: the durable event is staged inside the tx.
    monkeypatch.setattr(
        Settings,
        "auth_email_delivery_configured",
        property(lambda self: True),
    )
    result = await PosService.request_receipt_email(
        db,
        tenant_ctx.tenant_id,
        sold["receipt_id"],
        email="customer@example.com",
        requested_by=tenant_ctx.user.id,
    )
    assert result["queued"] is True
    assert "pos.receipt.email_requested" in DOMAIN_EVENT_TYPES
    staged = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "pos_session",
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(
        "pos.receipt.email_requested" in e.payload
        and e.payload.get("receipt_id") == str(sold["receipt_id"])
        for e in staged
    )


async def test_daily_projection_is_idempotent(db, tenant_ctx):
    from app.modules.pos.models import PosDailySales
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opening_float="10.00"
    )
    variant = await _sellable_variant(db, tenant_ctx, price="30.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    await PosService.close_session(db, tenant_ctx.tenant_id, pos_session.id)

    business_date = date.fromisoformat(datetime.now(UTC).date().isoformat())
    written = await PosService.upsert_daily_projection(
        db, tenant_ctx.tenant_id, business_date=business_date
    )
    assert written == 1
    rows = (
        (
            await db.execute(
                select(PosDailySales).where(PosDailySales.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.session_count == 1
    assert row.invoice_count == 1
    assert Decimal(str(row.sales_total)) == Decimal("30.00")
    assert Decimal(str(row.returns_total)) == Decimal("30.00")
    assert Decimal(str(row.variance_total)) == Decimal("0.00")  # nothing is counted any more
    assert row.by_method == []

    # A redelivered event REWRITES the same truth — never doubles it.
    await PosService.upsert_daily_projection(db, tenant_ctx.tenant_id, business_date=business_date)
    rows = (
        (
            await db.execute(
                select(PosDailySales).where(PosDailySales.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert Decimal(str(rows[0].returns_total)) == Decimal("30.00")

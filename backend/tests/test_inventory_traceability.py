"""Tests for Inventory Traceability: Lots, Serials, Expiry, and Policies (§4 Phase 6, 6.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.applications.apparel.modules.purchasing.models  # noqa: F401
from app.applications.apparel.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError
from app.applications.apparel.modules.inventory.service import TraceabilityService

# ═══════════════════════════════════════════════════════════════════════════
# 6.3 Tracking Policy and Mandatory Expiry Enforcement
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_tracking_policy_and_expiry_enforcement(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id

    prod = await CatalogService.create_product(
        db, tid, title="Pharma Batch Item", slug=f"pbi-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="40.00")

    # Set policy: batch tracking with mandatory expiry
    policy = await TraceabilityService.set_tracking_policy(
        db, tid, variant_id=var.id, mode="batch", expiry_required=True
    )
    assert policy.mode == "batch"
    assert policy.expiry_required is True

    # Attempting to create a lot without expiry date is refused
    with pytest.raises(ValidationError, match="expiry date is required"):
        await TraceabilityService.create_lot(db, tid, variant_id=var.id, lot_code="LOT-NO-EXPIRY")

    # Creating lot with expiry succeeds
    exp_date = datetime.now(UTC) + timedelta(days=180)
    lot = await TraceabilityService.create_lot(
        db,
        tid,
        variant_id=var.id,
        lot_code="LOT-2026-001",
        expires_at=exp_date,
        unit_cost="12.50",
    )
    assert lot.lot_code == "LOT-2026-001"
    assert lot.expires_at == exp_date

    # Duplicate lot code for same variant is refused
    with pytest.raises(ConflictError, match="already exists"):
        await TraceabilityService.create_lot(
            db, tid, variant_id=var.id, lot_code="LOT-2026-001", expires_at=exp_date
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6.4 FEFO (First Expired First Out) Ordering for Lots
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fefo_lot_listing_order(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id

    prod = await CatalogService.create_product(
        db, tid, title="Dairy Product", slug=f"dp-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="5.00")

    now = datetime.now(UTC)
    # Lot 1: expires in 60 days
    lot_later = await TraceabilityService.create_lot(
        db, tid, variant_id=var.id, lot_code="LOT-60D", expires_at=now + timedelta(days=60)
    )
    # Lot 2: expires in 15 days (should be first in FEFO!)
    lot_sooner = await TraceabilityService.create_lot(
        db, tid, variant_id=var.id, lot_code="LOT-15D", expires_at=now + timedelta(days=15)
    )
    # Lot 3: expires in 90 days
    lot_last = await TraceabilityService.create_lot(
        db, tid, variant_id=var.id, lot_code="LOT-90D", expires_at=now + timedelta(days=90)
    )

    lots = await TraceabilityService.list_lots(db, tid, variant_id=var.id)
    assert len(lots) == 3
    # FEFO: sooner first
    assert lots[0].id == lot_sooner.id
    assert lots[1].id == lot_later.id
    assert lots[2].id == lot_last.id


# ═══════════════════════════════════════════════════════════════════════════
# 6.5 Serial Number Registration and Status Transitions
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_serial_registration_and_lifecycle(db: AsyncSession, tenant_ctx):
    tid = tenant_ctx.tenant_id

    prod = await CatalogService.create_product(
        db, tid, title="Electronics Unit", slug=f"eu-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="500.00")

    # Register serials
    serials = await TraceabilityService.register_serials(
        db, tid, variant_id=var.id, serial_codes=["SN-001", "SN-002", "SN-003"]
    )
    assert len(serials) == 3
    assert all(s.status == "in_stock" for s in serials)

    # Duplicate registration fails
    with pytest.raises(ConflictError, match="already registered"):
        await TraceabilityService.register_serials(
            db, tid, variant_id=var.id, serial_codes=["SN-001"]
        )

    # Status transitions: sell unit SN-001
    s1 = await TraceabilityService.update_serial_status(
        db, tid, variant_id=var.id, serial_code="SN-001", status="sold"
    )
    assert s1.status == "sold"

    # Quarantine unit SN-002
    s2 = await TraceabilityService.update_serial_status(
        db, tid, variant_id=var.id, serial_code="SN-002", status="quarantined"
    )
    assert s2.status == "quarantined"

    # Filter serials by status
    in_stock = await TraceabilityService.list_serials(db, tid, variant_id=var.id, status="in_stock")
    assert len(in_stock) == 1
    assert in_stock[0].serial_code == "SN-003"

"""INVENTORY routes — balances, movement ledger, recording movements."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.modules.errors import ValidationError
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.inventory.reconciliation import InventoryReconciliationService
from app.modules.inventory.service import (
    MOVEMENT_DIRECTION_PATTERN,
    MOVEMENT_REASON_FILTER_PATTERN,
    MOVEMENT_REASON_PATTERN,
    ChannelAllocationService,
    InventoryReportingService,
    InventoryService,
    QualityInspectionService,
    ReplenishmentService,
    StocktakeService,
    TraceabilityService,
    ValuationService,
    WarehouseLocationService,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


class MovementRequest(BaseModel):
    variant_id: uuid.UUID
    warehouse_id: uuid.UUID
    # `hold`/`release` are deliberately absent: they pair with the reservation
    # machinery, and a hand-written one would fake a hold nothing can release.
    direction: str = Field(pattern=MOVEMENT_DIRECTION_PATTERN)
    quantity: int = Field(gt=0)
    # Closed vocabulary (M9) — was free text, so the ledger could not be
    # grouped, filtered or reconciled. Default kept for existing callers.
    reason: str = Field(default="adjustment", pattern=MOVEMENT_REASON_PATTERN)


@router.get("/balances")
async def list_balances(ctx: TenantCtxDep, limit: int = 200):
    rows = await InventoryService.list_balances(ctx.session, ctx.tenant_id, limit=limit)
    return [
        {
            "variant_id": str(b.variant_id),
            "warehouse_id": str(b.warehouse_id),
            "on_hand": b.on_hand,
            "reserved": b.reserved,
        }
        for b in rows
    ]


@router.get("/movements")
async def list_movements(
    ctx: TenantCtxDep,
    variant_id: uuid.UUID | None = None,
    reason: Annotated[str | None, Query(pattern=MOVEMENT_REASON_FILTER_PATTERN)] = None,
    reservation_id: uuid.UUID | None = None,
    limit: int = 50,
):
    """The stock ledger, newest first.

    `reservation_id` answers "what reserved this, and was it released": it
    returns the hold row behind that reservation plus every release row that
    names it. `reason` is filtered against the closed vocabulary, so a typo is a
    422 rather than a silently empty 200.
    """
    rows = await InventoryService.list_movements(
        ctx.session,
        ctx.tenant_id,
        variant_id=variant_id,
        reason=reason,
        reservation_id=reservation_id,
        limit=limit,
    )
    from app.modules.identity.service import UserService

    actor_names = await UserService.names(ctx.session, {m.actor_user_id for m in rows} - {None})
    return [
        {
            "id": str(m.id),
            "variant_id": str(m.variant_id),
            "warehouse_id": str(m.warehouse_id),
            "direction": m.direction,
            "quantity": m.quantity,
            "reason": m.reason,
            "reference_type": m.reference_type,
            "reference_id": str(m.reference_id) if m.reference_id else None,
            "balance_after": m.balance_after,
            "created_at": m.created_at.isoformat(),
            "actor_user_id": str(m.actor_user_id) if m.actor_user_id else None,
            "actor_name": actor_names.get(m.actor_user_id),
        }
        for m in rows
    ]


@router.post("/movements", status_code=201)
async def record_movement(
    body: MovementRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    """A stock movement is an accounting event: it moves `on_hand` for real, so
    it needs the write permission instead of merely being logged in. Reservations
    move `reserved` through `InventoryService.reserve`/`release` on the order
    path, never through this route."""
    movement = await InventoryService.move(
        ctx.session,
        ctx.tenant_id,
        body.variant_id,
        body.warehouse_id,
        direction=body.direction,
        quantity=body.quantity,
        reason=body.reason,
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(movement.id),
        "balance_after": movement.balance_after,
    }


def _finding_out(f) -> dict:
    return {
        "id": str(f.id),
        "check": f.check_kind,
        "warehouse_id": str(f.warehouse_id) if f.warehouse_id else None,
        "variant_id": str(f.variant_id) if f.variant_id else None,
        "movement_id": str(f.movement_id) if f.movement_id else None,
        "expected": f.expected,
        "actual": f.actual,
        "status": f.status,
        "note": f.note,
        "created_at": f.created_at.isoformat(),
    }


@router.get("/reconciliation/findings")
async def list_reconciliation_findings(ctx: TenantCtxDep, status: str = "OPEN"):
    """§188: discrepancies are records, not log lines. OPEN by default."""
    rows = await InventoryReconciliationService.list_findings(
        ctx.session, ctx.tenant_id, status=status
    )
    return [_finding_out(f) for f in rows]


class ResolveFindingRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


@router.post("/reconciliation/findings/{finding_id}/resolve")
async def resolve_reconciliation_finding(
    finding_id: uuid.UUID,
    body: ResolveFindingRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    """OPEN → RESOLVED, once. Resolving says "I looked and this is fine" —
    it never edits the ledger or the balance."""
    finding = await InventoryReconciliationService.resolve_finding(
        ctx.session,
        ctx.tenant_id,
        finding_id,
        resolved_by=ctx.user.id,
        note=body.note,
    )
    return _finding_out(finding)


# ------------------------------------------------ locations & relocation ----


class LocationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=63)
    kind: str = Field(
        default="bin",
        pattern="^(receiving|qc|storage|picking|packing|returns|quarantine|damaged|zone|rack|shelf|bin)$",
    )
    parent_id: uuid.UUID | None = None
    capacity: int | None = None
    notes: str | None = Field(default=None, max_length=2000)


class LocationOut(BaseModel):
    id: str
    warehouse_id: str
    name: str
    code: str
    kind: str
    parent_id: str | None
    capacity: int | None
    is_active: bool
    notes: str | None


class RelocateRequest(BaseModel):
    variant_id: uuid.UUID
    warehouse_id: uuid.UUID
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    quantity: int = Field(gt=0)


@router.get("/warehouses")
async def list_warehouses(ctx: TenantCtxDep):
    from sqlalchemy import select

    from app.modules.inventory.models import Warehouse

    q = (
        select(Warehouse)
        .where(Warehouse.tenant_id == ctx.tenant_id, Warehouse.is_active.is_(True))
        .order_by(Warehouse.created_at.asc())
    )
    rows = list((await ctx.session.execute(q)).scalars())
    return [
        {
            "id": str(w.id),
            "name": w.name,
            "code": w.code,
            "address": w.address,
            "is_active": w.is_active,
        }
        for w in rows
    ]


@router.get("/warehouses/{warehouse_id}/locations", response_model=list[LocationOut])
async def list_warehouse_locations(warehouse_id: uuid.UUID, ctx: TenantCtxDep):
    rows = await WarehouseLocationService.list_locations(ctx.session, ctx.tenant_id, warehouse_id)
    return [
        LocationOut(
            id=str(r.id),
            warehouse_id=str(r.warehouse_id),
            name=r.name,
            code=r.code,
            kind=r.kind,
            parent_id=str(r.parent_id) if r.parent_id else None,
            capacity=r.capacity,
            is_active=r.is_active,
            notes=r.notes,
        )
        for r in rows
    ]


@router.post("/warehouses/{warehouse_id}/locations", status_code=201, response_model=LocationOut)
async def create_warehouse_location(
    warehouse_id: uuid.UUID,
    body: LocationCreateRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    loc = await WarehouseLocationService.create_location(
        ctx.session,
        ctx.tenant_id,
        warehouse_id=warehouse_id,
        name=body.name,
        code=body.code,
        kind=body.kind,
        parent_id=body.parent_id,
        capacity=body.capacity,
        notes=body.notes,
    )
    return LocationOut(
        id=str(loc.id),
        warehouse_id=str(loc.warehouse_id),
        name=loc.name,
        code=loc.code,
        kind=loc.kind,
        parent_id=str(loc.parent_id) if loc.parent_id else None,
        capacity=loc.capacity,
        is_active=loc.is_active,
        notes=loc.notes,
    )


class PutawayRequest(BaseModel):
    variant_id: uuid.UUID
    warehouse_id: uuid.UUID
    to_location_id: uuid.UUID
    quantity: int = Field(gt=0)


@router.post("/relocate", status_code=201)
async def relocate_stock(
    body: RelocateRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    mov = await WarehouseLocationService.relocate(
        ctx.session,
        ctx.tenant_id,
        variant_id=body.variant_id,
        warehouse_id=body.warehouse_id,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        quantity=body.quantity,
        user_id=ctx.user.id,
    )
    return {"id": str(mov.id), "quantity": mov.quantity}


@router.post("/putaway", status_code=201)
async def putaway_stock(
    body: PutawayRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    mov = await WarehouseLocationService.putaway(
        ctx.session,
        ctx.tenant_id,
        warehouse_id=body.warehouse_id,
        variant_id=body.variant_id,
        to_location_id=body.to_location_id,
        quantity=body.quantity,
        user_id=ctx.user.id,
    )
    return {"id": str(mov.id), "quantity": mov.quantity}


# ------------------------------------------------ quality inspections ----


class InspectionCreateRequest(BaseModel):
    source_type: str = Field(pattern="^(goods_receipt|return_receipt|transfer_receipt)$")
    warehouse_id: uuid.UUID
    source_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class InspectionResultRequest(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(gt=0)
    verdict: str = Field(pattern="^(pass|quarantine|reject)$")
    note: str | None = Field(default=None, max_length=255)


class InspectionCompleteRequest(BaseModel):
    verdict: str | None = Field(default=None, pattern="^(passed|quarantined|rejected)$")
    note: str | None = Field(default=None, max_length=2000)


@router.post("/inspections", status_code=201)
async def create_inspection(
    body: InspectionCreateRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    insp = await QualityInspectionService.create(
        ctx.session,
        ctx.tenant_id,
        source_type=body.source_type,
        warehouse_id=body.warehouse_id,
        source_id=body.source_id,
        note=body.note,
    )
    return {"id": str(insp.id), "status": insp.status}


@router.get("/inspections/{inspection_id}")
async def get_inspection(inspection_id: uuid.UUID, ctx: TenantCtxDep):
    insp = await QualityInspectionService.get(ctx.session, ctx.tenant_id, inspection_id)
    return {
        "id": str(insp.id),
        "source_type": insp.source_type,
        "source_id": str(insp.source_id) if insp.source_id else None,
        "warehouse_id": str(insp.warehouse_id),
        "status": insp.status,
        "note": insp.note,
    }


@router.post("/inspections/{inspection_id}/results", status_code=201)
async def record_inspection_result(
    inspection_id: uuid.UUID,
    body: InspectionResultRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    res = await QualityInspectionService.record_result(
        ctx.session,
        ctx.tenant_id,
        inspection_id=inspection_id,
        variant_id=body.variant_id,
        quantity=body.quantity,
        verdict=body.verdict,
        note=body.note,
        user_id=ctx.user.id,
    )
    return {"id": str(res.id), "inspection_id": str(res.inspection_id), "verdict": res.verdict}


@router.post("/inspections/{inspection_id}/complete")
async def complete_inspection(
    inspection_id: uuid.UUID,
    body: InspectionCompleteRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    insp = await QualityInspectionService.complete(
        ctx.session,
        ctx.tenant_id,
        inspection_id=inspection_id,
        user_id=ctx.user.id,
        note=body.note,
    )
    return {"id": str(insp.id), "status": insp.status}


# ------------------------------------------------ transfers lifecycle ----


class TransferLineIn(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(gt=0)


class TransferCreateRequest(BaseModel):
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    lines: list[TransferLineIn]
    note: str | None = Field(default=None, max_length=2000)


class TransferShipLineIn(BaseModel):
    transfer_line_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    quantity: int = Field(gt=0)


class TransferShipRequest(BaseModel):
    lines: list[TransferShipLineIn] | None = None
    carrier: str | None = Field(default=None, max_length=255)
    tracking_number: str | None = Field(default=None, max_length=255)
    tracking_ref: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


class TransferReceiveLineIn(BaseModel):
    transfer_line_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    quantity: int = Field(gt=0)
    condition: str = Field(default="good", pattern="^(good|damaged|short)$")


class TransferReceiveRequest(BaseModel):
    lines: list[TransferReceiveLineIn] | None = None
    shipment_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


@router.get("/transfers")
async def list_transfers(
    ctx: TenantCtxDep,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
):
    from sqlalchemy import select

    from app.modules.inventory.models import InventoryTransfer

    q = select(InventoryTransfer).where(InventoryTransfer.tenant_id == ctx.tenant_id)
    if status:
        q = q.where(InventoryTransfer.status == status)
    q = q.order_by(InventoryTransfer.created_at.desc()).limit(limit)
    rows = list((await ctx.session.execute(q)).scalars())
    return [
        {
            "id": str(t.id),
            "from_warehouse_id": str(t.from_warehouse_id),
            "to_warehouse_id": str(t.to_warehouse_id),
            "status": t.status,
            "note": t.notes,
            "created_at": t.created_at.isoformat(),
        }
        for t in rows
    ]


@router.get("/transfers/{transfer_id}")
async def get_transfer(transfer_id: uuid.UUID, ctx: TenantCtxDep):
    tr = await InventoryService.get_transfer(ctx.session, ctx.tenant_id, transfer_id)
    return {
        "id": str(tr.id),
        "from_warehouse_id": str(tr.from_warehouse_id),
        "to_warehouse_id": str(tr.to_warehouse_id),
        "status": tr.status,
        "note": tr.notes,
        "created_at": tr.created_at.isoformat(),
    }


@router.post("/transfers", status_code=201)
async def create_transfer(
    body: TransferCreateRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    tr = await InventoryService.create_transfer(
        ctx.session,
        ctx.tenant_id,
        from_warehouse_id=body.from_warehouse_id,
        to_warehouse_id=body.to_warehouse_id,
        lines=[ln.model_dump(mode="json") for ln in body.lines],
        notes=body.note,
    )
    return {"id": str(tr.id), "status": tr.status}


@router.post("/transfers/{transfer_id}/ship")
async def ship_transfer(
    transfer_id: uuid.UUID,
    body: TransferShipRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    lines_payload = (
        [ln.model_dump(mode="json", exclude_none=True) for ln in body.lines] if body.lines else None
    )
    sh = await InventoryService.ship_transfer(
        ctx.session,
        ctx.tenant_id,
        transfer_id=transfer_id,
        lines=lines_payload,
        carrier=body.carrier,
        tracking_ref=body.tracking_ref or body.tracking_number,
        note=body.note,
        user_id=ctx.user.id,
    )
    return {"shipment_id": str(sh.id), "transfer_id": str(transfer_id)}


@router.post("/transfers/{transfer_id}/receive")
async def receive_transfer(
    transfer_id: uuid.UUID,
    body: TransferReceiveRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    lines_payload = (
        [ln.model_dump(mode="json", exclude_none=True) for ln in body.lines] if body.lines else None
    )
    rc = await InventoryService.receive_transfer(
        ctx.session,
        ctx.tenant_id,
        transfer_id=transfer_id,
        lines=lines_payload,
        shipment_id=body.shipment_id,
        note=body.note,
        user_id=ctx.user.id,
    )
    return {"receipt_id": str(rc.id), "transfer_id": str(transfer_id)}


# ------------------------------------------------ stocktakes upgrade ----


class StocktakeCreateRequest(BaseModel):
    warehouse_id: uuid.UUID
    kind: str = Field(default="full", pattern="^(full|cycle|blind|spot)$")
    is_blind: bool = False
    variance_threshold_percent: Decimal = Decimal("5.0")
    note: str | None = Field(default=None, max_length=2000)


class StocktakeCountLineIn(BaseModel):
    variant_id: uuid.UUID
    counted_quantity: int = Field(ge=0)


class StocktakeCountRequest(BaseModel):
    variant_id: uuid.UUID | None = None
    counted_quantity: int | None = Field(default=None, ge=0)
    counts: list[StocktakeCountLineIn] | None = None


@router.get("/stocktakes")
async def list_stocktakes(
    ctx: TenantCtxDep,
    warehouse_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
):
    return await StocktakeService.list_recent(ctx.session, ctx.tenant_id, limit=limit)


@router.get("/stocktakes/{stocktake_id}")
async def get_stocktake(stocktake_id: uuid.UUID, ctx: TenantCtxDep):
    return await StocktakeService.detail(ctx.session, ctx.tenant_id, stocktake_id=stocktake_id)


@router.post("/stocktakes", status_code=201)
async def create_stocktake(
    body: StocktakeCreateRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    pct = int(body.variance_threshold_percent) if body.variance_threshold_percent else 10
    st = await StocktakeService.open(
        ctx.session,
        ctx.tenant_id,
        warehouse_id=body.warehouse_id,
        kind=body.kind,
        blind=body.is_blind,
        recount_threshold_pct=pct,
        user_id=ctx.user.id,
        note=body.note,
    )
    return {"id": str(st.id), "status": st.status, "warehouse_id": str(st.warehouse_id)}


@router.post("/stocktakes/{stocktake_id}/count")
async def record_stocktake_count(
    stocktake_id: uuid.UUID,
    body: StocktakeCountRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    counts: list[dict] = []
    if body.counts:
        counts = [
            {"variant_id": str(c.variant_id), "counted_qty": c.counted_quantity}
            for c in body.counts
        ]
    elif body.variant_id is not None and body.counted_quantity is not None:
        counts = [{"variant_id": str(body.variant_id), "counted_qty": body.counted_quantity}]
    else:
        raise ValidationError("must provide counted line or counts list")

    written = await StocktakeService.record_counts(
        ctx.session,
        ctx.tenant_id,
        stocktake_id=stocktake_id,
        counts=counts,
        user_id=ctx.user.id,
    )
    return {
        "ok": True,
        "written": written,
        "stocktake_id": str(stocktake_id),
    }


@router.post("/stocktakes/{stocktake_id}/complete")
async def complete_stocktake(
    stocktake_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    res = await StocktakeService.approve(
        ctx.session,
        ctx.tenant_id,
        stocktake_id=stocktake_id,
        user_id=ctx.user.id,
    )
    return res


# ------------------------------------------------ replenishment engine ----


class PolicySetRequest(BaseModel):
    variant_id: uuid.UUID
    warehouse_id: uuid.UUID
    min_stock: int = Field(ge=0)
    max_stock: int | None = Field(default=None, ge=0)
    # None = the shop-wide default (inventory.safety_stock_default).
    safety_stock: int | None = Field(default=None, ge=0)
    lead_time_days: int = Field(default=0, ge=0)
    moq: int = Field(default=1, gt=0)
    order_multiple: int = Field(default=1, gt=0)
    review_period_days: int = Field(default=7, gt=0)
    preferred_supplier_id: uuid.UUID | None = None


@router.get("/replenishment/policies")
async def list_replenishment_policies(
    ctx: TenantCtxDep,
    warehouse_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    from sqlalchemy import select

    from app.modules.inventory.models import InventoryPolicy

    q = select(InventoryPolicy).where(InventoryPolicy.tenant_id == ctx.tenant_id)
    if warehouse_id:
        q = q.where(InventoryPolicy.warehouse_id == warehouse_id)
    rows = list((await ctx.session.execute(q.limit(limit))).scalars())
    return [
        {
            "variant_id": str(p.variant_id),
            "warehouse_id": str(p.warehouse_id),
            "min_stock": p.min_stock,
            "max_stock": p.max_stock,
            "safety_stock": p.safety_stock,
            "lead_time_days": p.lead_time_days,
            "moq": p.moq,
            "order_multiple": p.order_multiple,
        }
        for p in rows
    ]


@router.post("/replenishment/policies", status_code=201)
async def set_replenishment_policy(
    body: PolicySetRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    pol = await ReplenishmentService.set_policy(
        ctx.session,
        ctx.tenant_id,
        variant_id=body.variant_id,
        warehouse_id=body.warehouse_id,
        min_stock=body.min_stock,
        max_stock=body.max_stock,
        safety_stock=body.safety_stock,
        lead_time_days=body.lead_time_days,
        moq=body.moq,
        order_multiple=body.order_multiple,
        review_period_days=body.review_period_days,
        preferred_supplier_id=body.preferred_supplier_id,
    )
    return {
        "variant_id": str(pol.variant_id),
        "warehouse_id": str(pol.warehouse_id),
        "min_stock": pol.min_stock,
        "max_stock": pol.max_stock,
    }


@router.get("/replenishment/suggestions")
async def list_reorder_suggestions(
    ctx: TenantCtxDep,
    warehouse_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    from sqlalchemy import select

    from app.modules.inventory.models import ReorderSuggestion

    q = select(ReorderSuggestion).where(ReorderSuggestion.tenant_id == ctx.tenant_id)
    if warehouse_id:
        q = q.where(ReorderSuggestion.warehouse_id == warehouse_id)
    if status:
        q = q.where(ReorderSuggestion.status == status)
    rows = list(
        (
            await ctx.session.execute(q.order_by(ReorderSuggestion.created_at.desc()).limit(limit))
        ).scalars()
    )
    return [
        {
            "id": str(s.id),
            "variant_id": str(s.variant_id),
            "warehouse_id": str(s.warehouse_id),
            "suggested_quantity": s.suggested_quantity,
            "source": s.source,
            "status": s.status,
            "reason": s.reason,
            "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]


@router.post("/replenishment/generate")
async def generate_reorder_suggestions(
    ctx: TenantContext = Depends(require_permission("inventory:write")),
    warehouse_id: uuid.UUID | None = None,
):
    suggestions = await ReplenishmentService.generate_suggestions(
        ctx.session, ctx.tenant_id, warehouse_id=warehouse_id
    )
    return {"generated_count": len(suggestions)}


@router.post("/replenishment/suggestions/{suggestion_id}/approve")
async def approve_reorder_suggestion(
    suggestion_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    sug = await ReplenishmentService.approve_suggestion(
        ctx.session, ctx.tenant_id, suggestion_id=suggestion_id
    )
    return {
        "id": str(sug.id),
        "status": sug.status,
    }


@router.post("/replenishment/suggestions/{suggestion_id}/dismiss")
async def dismiss_reorder_suggestion(
    suggestion_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    sug = await ReplenishmentService.dismiss_suggestion(
        ctx.session, ctx.tenant_id, suggestion_id=suggestion_id
    )
    return {"id": str(sug.id), "status": sug.status}


# ------------------------------------------------ valuation & landed cost ----


class LandedCostCreateRequest(BaseModel):
    warehouse_id: uuid.UUID
    total: Decimal = Field(gt=0)
    purchase_order_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


@router.get("/valuation")
async def get_valuation(ctx: TenantCtxDep, warehouse_id: uuid.UUID | None = None):
    res = await ValuationService.calculate_valuation(
        ctx.session, ctx.tenant_id, warehouse_id=warehouse_id
    )
    return {
        "total_valuation": f"{res['total_valuation']:.4f}",
        "total_quantity": res["total_quantity"],
        "average_unit_cost": f"{res['average_unit_cost']:.4f}",
        "layer_count": res["layer_count"],
    }


@router.post("/landed-costs", status_code=201)
async def create_landed_cost(
    body: LandedCostCreateRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    lc = await ValuationService.create_landed_cost(
        ctx.session,
        ctx.tenant_id,
        warehouse_id=body.warehouse_id,
        total=body.total,
        purchase_order_id=body.purchase_order_id,
        note=body.note,
        user_id=ctx.user.id,
    )
    return {
        "id": str(lc.id),
        "warehouse_id": str(lc.warehouse_id),
        "total": f"{lc.total:.2f}",
        "status": lc.status,
    }


class LandedCostAllocateItemIn(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(gt=0)
    unit_cost: Decimal | None = None


class LandedCostAllocateRequest(BaseModel):
    method: str = Field(default="quantity", pattern="^(quantity|value)$")
    items: list[LandedCostAllocateItemIn] | None = None


@router.post("/landed-costs/{cost_id}/allocate")
async def allocate_landed_cost(
    cost_id: uuid.UUID,
    body: LandedCostAllocateRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    items = [item.model_dump(mode="json") for item in body.items] if body.items else None
    lines = await ValuationService.allocate_landed_cost(
        ctx.session,
        ctx.tenant_id,
        landed_cost_id=cost_id,
        method=body.method,
        items=items,
    )
    return {
        "landed_cost_id": str(cost_id),
        "allocated_lines": len(lines),
    }


@router.post("/landed-costs/{cost_id}/post")
async def post_landed_cost(
    cost_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    lc = await ValuationService.post_landed_cost(ctx.session, ctx.tenant_id, cost_id=cost_id)
    return {"id": str(lc.id), "status": lc.status}


# ------------------------------------------------ traceability ----


class TrackingPolicyRequest(BaseModel):
    mode: str = Field(pattern="^(none|batch|serial)$")
    expiry_required: bool = False


class LotCreateRequest(BaseModel):
    lot_code: str = Field(min_length=1, max_length=63)
    expires_at: datetime | None = None
    supplier_id: uuid.UUID | None = None
    unit_cost: Decimal | None = None


class SerialsRegisterRequest(BaseModel):
    warehouse_id: uuid.UUID | None = None
    serial_numbers: list[str] = Field(default_factory=list)
    serial_codes: list[str] = Field(default_factory=list)
    lot_id: uuid.UUID | None = None


@router.get("/variants/{variant_id}/tracking-policy")
async def get_tracking_policy(variant_id: uuid.UUID, ctx: TenantCtxDep):
    pol = await TraceabilityService.get_tracking_policy(
        ctx.session, ctx.tenant_id, variant_id=variant_id
    )
    return {
        "variant_id": str(variant_id),
        "mode": pol.mode if pol else "none",
        "expiry_required": pol.expiry_required if pol else False,
    }


@router.post("/variants/{variant_id}/tracking-policy")
async def set_tracking_policy(
    variant_id: uuid.UUID,
    body: TrackingPolicyRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    pol = await TraceabilityService.set_tracking_policy(
        ctx.session,
        ctx.tenant_id,
        variant_id=variant_id,
        mode=body.mode,
        expiry_required=body.expiry_required,
    )
    return {
        "variant_id": str(pol.variant_id),
        "mode": pol.mode,
        "expiry_required": pol.expiry_required,
    }


@router.get("/variants/{variant_id}/lots")
async def list_variant_lots(variant_id: uuid.UUID, ctx: TenantCtxDep):
    rows = await TraceabilityService.list_lots(ctx.session, ctx.tenant_id, variant_id=variant_id)
    return [
        {
            "id": str(lot.id),
            "lot_code": lot.lot_code,
            "expires_at": lot.expires_at.isoformat() if lot.expires_at else None,
            "supplier_id": str(lot.supplier_id) if lot.supplier_id else None,
            "unit_cost": str(lot.unit_cost) if lot.unit_cost is not None else None,
        }
        for lot in rows
    ]


@router.post("/variants/{variant_id}/lots", status_code=201)
async def create_variant_lot(
    variant_id: uuid.UUID,
    body: LotCreateRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    lot = await TraceabilityService.create_lot(
        ctx.session,
        ctx.tenant_id,
        variant_id=variant_id,
        lot_code=body.lot_code,
        expires_at=body.expires_at,
        supplier_id=body.supplier_id,
        unit_cost=body.unit_cost,
    )
    return {"id": str(lot.id), "lot_code": lot.lot_code}


@router.get("/variants/{variant_id}/serials")
async def list_variant_serials(
    variant_id: uuid.UUID,
    ctx: TenantCtxDep,
    warehouse_id: uuid.UUID | None = None,
    status: str | None = None,
    lot_id: uuid.UUID | None = None,
):
    rows = await TraceabilityService.list_serials(
        ctx.session, ctx.tenant_id, variant_id=variant_id, status=status, lot_id=lot_id
    )
    return [
        {
            "id": str(s.id),
            "serial_code": s.serial_code,
            "serial_number": s.serial_code,
            "lot_id": str(s.lot_id) if s.lot_id else None,
            "status": s.status,
        }
        for s in rows
    ]


@router.post("/variants/{variant_id}/serials", status_code=201)
async def register_variant_serials(
    variant_id: uuid.UUID,
    body: SerialsRegisterRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    codes = body.serial_codes or body.serial_numbers
    serials = await TraceabilityService.register_serials(
        ctx.session,
        ctx.tenant_id,
        variant_id=variant_id,
        serial_codes=codes,
        lot_id=body.lot_id,
    )
    return {
        "registered_count": len(serials),
        "serials": [
            {
                "id": str(s.id),
                "serial_code": s.serial_code,
                "serial_number": s.serial_code,
                "status": s.status,
            }
            for s in serials
        ],
    }


# ------------------------------------------------ reports ----


@router.get("/reports/summary")
async def get_stock_summary(ctx: TenantCtxDep, warehouse_id: uuid.UUID | None = None):
    res = await InventoryReportingService.stock_summary(
        ctx.session, ctx.tenant_id, warehouse_id=warehouse_id
    )
    return {
        "on_hand": res["on_hand"],
        "sellable": res["sellable"],
        "available": res["available"],
        "reserved": res["reserved"],
        "quarantined": res["quarantined"],
        "in_transit": res["in_transit"],
        "total_valuation": f"{res['total_valuation']:.4f}",
    }


@router.get("/reports/dead-stock")
async def get_dead_stock(
    ctx: TenantCtxDep,
    days_inactive: Annotated[int, Query(ge=7, le=365)] = 90,
    warehouse_id: uuid.UUID | None = None,
):
    rows = await InventoryReportingService.dead_stock(
        ctx.session, ctx.tenant_id, days_inactive=days_inactive, warehouse_id=warehouse_id
    )
    return rows


@router.get("/reports/low-stock-alerts")
async def get_low_stock_alerts(ctx: TenantCtxDep, warehouse_id: uuid.UUID | None = None):
    rows = await InventoryReportingService.low_stock_alerts(
        ctx.session, ctx.tenant_id, warehouse_id=warehouse_id
    )
    return rows


@router.get("/reports/apparel-insights")
async def get_apparel_insights(
    ctx: TenantCtxDep,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
    warehouse_id: uuid.UUID | None = None,
):
    return await InventoryReportingService.apparel_insights(
        ctx.session, ctx.tenant_id, warehouse_id=warehouse_id, days=days
    )


# ------------------------------------------------ channel allocations ----


class ChannelAllocationIn(BaseModel):
    warehouse_id: uuid.UUID
    variant_id: uuid.UUID
    channel: str = Field(min_length=1, max_length=31)
    quantity: int = Field(ge=0)


class ChannelAllocationOut(BaseModel):
    id: uuid.UUID
    warehouse_id: uuid.UUID
    variant_id: uuid.UUID
    channel: str
    allocated_quantity: int
    reserved_in_channel: int


class ChannelAvailabilityOut(BaseModel):
    variant_id: uuid.UUID
    warehouse_id: uuid.UUID
    channel: str
    available_quantity: int
    allocated_quantity: int | None = None
    reserved_in_channel: int = 0
    global_available: int


class MarkSerialsRequest(BaseModel):
    serial_codes: list[str] = Field(min_length=1)


@router.get("/channel-allocations", response_model=list[ChannelAllocationOut])
async def list_channel_allocations(
    ctx: TenantCtxDep,
    warehouse_id: uuid.UUID | None = None,
    variant_id: uuid.UUID | None = None,
    channel: str | None = None,
):
    rows = await ChannelAllocationService.list_allocations(
        ctx.session,
        ctx.tenant_id,
        warehouse_id=warehouse_id,
        variant_id=variant_id,
        channel=channel,
    )
    return [
        ChannelAllocationOut(
            id=r.id,
            warehouse_id=r.warehouse_id,
            variant_id=r.variant_id,
            channel=r.channel,
            allocated_quantity=r.allocated_quantity,
            reserved_in_channel=r.reserved_in_channel,
        )
        for r in rows
    ]


@router.post("/channel-allocations", response_model=ChannelAllocationOut, status_code=201)
async def set_channel_allocation(
    body: ChannelAllocationIn,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    alloc = await ChannelAllocationService.set_allocation(
        ctx.session,
        ctx.tenant_id,
        warehouse_id=body.warehouse_id,
        variant_id=body.variant_id,
        channel=body.channel,
        quantity=body.quantity,
    )
    return ChannelAllocationOut(
        id=alloc.id,
        warehouse_id=alloc.warehouse_id,
        variant_id=alloc.variant_id,
        channel=alloc.channel,
        allocated_quantity=alloc.allocated_quantity,
        reserved_in_channel=alloc.reserved_in_channel,
    )


@router.delete("/channel-allocations/{allocation_id}", status_code=200)
async def delete_channel_allocation(
    allocation_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    await ChannelAllocationService.delete_allocation(
        ctx.session,
        ctx.tenant_id,
        allocation_id=allocation_id,
    )
    return {"ok": True}


@router.get("/channel-availability", response_model=ChannelAvailabilityOut)
async def get_channel_availability(
    ctx: TenantCtxDep,
    warehouse_id: uuid.UUID,
    variant_id: uuid.UUID,
    channel: str,
):
    res = await ChannelAllocationService.get_channel_availability(
        ctx.session,
        ctx.tenant_id,
        warehouse_id=warehouse_id,
        variant_id=variant_id,
        channel=channel,
    )
    return ChannelAvailabilityOut(**res)


# ------------------------------------------------ checkout traceability ----


@router.get("/variants/{variant_id}/checkout-traceability")
async def get_checkout_traceability(
    variant_id: uuid.UUID,
    ctx: TenantCtxDep,
):
    """Retrieve tracking policy and available lots/serials for checkout."""
    pol = await TraceabilityService.get_tracking_policy(
        ctx.session, ctx.tenant_id, variant_id=variant_id
    )
    mode = pol.mode if pol else "none"
    expiry_req = pol.expiry_required if pol else False

    lots = []
    serials = []
    if mode == "batch":
        lots_rows = await TraceabilityService.list_lots(
            ctx.session, ctx.tenant_id, variant_id=variant_id
        )
        lots = [
            {
                "id": str(lot_item.id),
                "lot_code": lot_item.lot_code,
                "expires_at": lot_item.expires_at.isoformat() if lot_item.expires_at else None,
                "unit_cost": str(lot_item.unit_cost) if lot_item.unit_cost is not None else None,
            }
            for lot_item in lots_rows
        ]
    elif mode == "serial":
        serials_rows = await TraceabilityService.list_serials(
            ctx.session, ctx.tenant_id, variant_id=variant_id, status="in_stock"
        )
        serials = [
            {
                "id": str(s.id),
                "serial_code": s.serial_code,
                "lot_id": str(s.lot_id) if s.lot_id else None,
                "status": s.status,
            }
            for s in serials_rows
        ]

    return {
        "variant_id": str(variant_id),
        "mode": mode,
        "expiry_required": expiry_req,
        "lots": lots,
        "serials": serials,
    }


@router.post("/variants/{variant_id}/serials/mark-sold")
async def mark_serials_sold(
    variant_id: uuid.UUID,
    body: MarkSerialsRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    for code in body.serial_codes:
        await TraceabilityService.update_serial_status(
            ctx.session,
            ctx.tenant_id,
            variant_id=variant_id,
            serial_code=code,
            status="sold",
        )
    return {"ok": True, "count": len(body.serial_codes)}


@router.post("/variants/{variant_id}/serials/mark-returned")
async def mark_serials_returned(
    variant_id: uuid.UUID,
    body: MarkSerialsRequest,
    ctx: TenantContext = Depends(require_permission("inventory:write")),
):
    for code in body.serial_codes:
        await TraceabilityService.update_serial_status(
            ctx.session,
            ctx.tenant_id,
            variant_id=variant_id,
            serial_code=code,
            status="returned",
        )
    return {"ok": True, "count": len(body.serial_codes)}

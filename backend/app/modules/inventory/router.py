"""INVENTORY routes — balances, movement ledger, recording movements."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.inventory.reconciliation import InventoryReconciliationService
from app.modules.inventory.service import (
    MOVEMENT_DIRECTION_PATTERN,
    MOVEMENT_REASON_FILTER_PATTERN,
    MOVEMENT_REASON_PATTERN,
    InventoryService,
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

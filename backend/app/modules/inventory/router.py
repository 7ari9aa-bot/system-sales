"""INVENTORY routes — balances, movement ledger, recording movements."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.modules.identity.deps import TenantCtxDep
from app.modules.inventory.service import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])


class MovementRequest(BaseModel):
    variant_id: uuid.UUID
    warehouse_id: uuid.UUID
    direction: str = Field(pattern="^(in|out|adjust)$")
    quantity: int = Field(gt=0)
    reason: str = "adjustment"


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
async def list_movements(ctx: TenantCtxDep, variant_id: uuid.UUID | None = None, limit: int = 50):
    rows = await InventoryService.list_movements(
        ctx.session, ctx.tenant_id, variant_id=variant_id, limit=limit
    )
    return [
        {
            "id": str(m.id),
            "variant_id": str(m.variant_id),
            "warehouse_id": str(m.warehouse_id),
            "direction": m.direction,
            "quantity": m.quantity,
            "reason": m.reason,
            "balance_after": m.balance_after,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


@router.post("/movements", status_code=201)
async def record_movement(ctx: TenantCtxDep, body: MovementRequest):
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

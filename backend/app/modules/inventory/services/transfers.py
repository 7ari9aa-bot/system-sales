"""Warehouse-to-warehouse stock transfer service for InventoryService."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError
from app.modules.inventory.models import InventoryTransfer
from ._common import _TRANSFER_STATUSES, _now, _positive_int
from .balances import BalanceServiceMixin
from .movements import MovementServiceMixin


class TransferServiceMixin:
    """Inter-warehouse inventory transfer workflows."""

    @staticmethod
    async def get_transfer(
        session: AsyncSession, tenant_id: UUID, transfer_id: UUID
    ) -> InventoryTransfer:
        transfer = (
            await session.execute(
                select(InventoryTransfer).where(
                    InventoryTransfer.id == transfer_id,
                    InventoryTransfer.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if transfer is None:
            raise NotFoundError(f"transfer {transfer_id} not found")
        return transfer

    @staticmethod
    async def create_transfer(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        from_warehouse_id: UUID,
        to_warehouse_id: UUID,
        lines: list[dict],
    ) -> InventoryTransfer:
        """Open a stock transfer between two warehouses of the tenant."""
        if from_warehouse_id == to_warehouse_id:
            raise ValueError("source and destination warehouses must differ")
        if not lines:
            raise ValueError("transfer must contain at least one line")
        await BalanceServiceMixin._get_warehouse(session, tenant_id, from_warehouse_id)
        await BalanceServiceMixin._get_warehouse(session, tenant_id, to_warehouse_id)

        normalized: list[dict] = []
        for line in lines:
            quantity = _positive_int(line.get("quantity"))
            variant_id = line.get("variant_id")
            if variant_id is None:
                raise ValueError("each transfer line needs a variant_id")
            normalized.append({"variant_id": str(variant_id), "quantity": quantity})

        transfer = InventoryTransfer(
            tenant_id=tenant_id,
            from_warehouse_id=from_warehouse_id,
            to_warehouse_id=to_warehouse_id,
            lines=normalized,
        )
        session.add(transfer)
        await session.flush()
        return transfer

    @staticmethod
    async def complete_transfer(
        session: AsyncSession, tenant_id: UUID, transfer_id: UUID
    ) -> InventoryTransfer:
        """Ship the transfer: out-move from source, in-move to destination."""
        transfer = await TransferServiceMixin.get_transfer(session, tenant_id, transfer_id)
        if transfer.status not in _TRANSFER_STATUSES:
            raise ConflictError(
                f"transfer {transfer_id} cannot be completed from status '{transfer.status}'"
            )

        for line in transfer.lines or []:
            variant_id = UUID(str(line["variant_id"]))
            quantity = int(line["quantity"])
            await MovementServiceMixin.move(
                session,
                tenant_id,
                variant_id,
                transfer.from_warehouse_id,
                direction="out",
                quantity=quantity,
                reason="transfer_out",
                reference_type="inventory_transfer",
                reference_id=transfer_id,
            )
            await MovementServiceMixin.move(
                session,
                tenant_id,
                variant_id,
                transfer.to_warehouse_id,
                direction="in",
                quantity=quantity,
                reason="transfer_in",
                reference_type="inventory_transfer",
                reference_id=transfer_id,
            )

        transfer.status = "completed"
        transfer.completed_at = _now()
        await session.flush()
        return transfer

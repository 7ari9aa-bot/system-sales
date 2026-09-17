"""INVENTORY domain service — the stock ledger and its rules.

inventory_movements is the append-only ledger; inventory_balances holds the
current position and is always mutated under SELECT ... FOR UPDATE so
concurrent checkouts serialize. Every method takes the caller's session and
tenant and NEVER commits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import ProductVariant
from app.modules.errors import ConflictError, NotFoundError
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    InventoryTransfer,
    Warehouse,
)
from app.modules.orders.errors import InsufficientStockError

_DIRECTIONS = {"in", "out", "adjust"}
_TRANSFER_STATUSES = {"draft", "in_transit"}


def _now() -> datetime:
    return datetime.now(UTC)


def _positive_int(quantity: object, field: str = "quantity") -> int:
    try:
        value = int(quantity)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return value


class InventoryService:
    """All stock business rules; static methods taking (session, tenant_id)."""

    # ------------------------------------------------------------- move ----

    @staticmethod
    async def move(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        *,
        direction: str,
        quantity: int,
        reason: str,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> InventoryMovement:
        """Apply a stock movement and append its ledger row.

        - in:     on_hand += quantity
        - out:    on_hand -= quantity (InsufficientStockError below zero)
        - adjust: on_hand = quantity (absolute count, e.g. stocktake)
        """
        if direction not in _DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(_DIRECTIONS)}")
        quantity = _positive_int(quantity)

        await InventoryService._get_variant(session, tenant_id, variant_id)
        await InventoryService._get_warehouse(session, tenant_id, warehouse_id)
        balance = await InventoryService._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )

        if direction == "in":
            new_on_hand = balance.on_hand + quantity
        elif direction == "out":
            new_on_hand = balance.on_hand - quantity
            if new_on_hand < 0:
                raise InsufficientStockError(
                    f"insufficient stock for variant {variant_id} in warehouse "
                    f"{warehouse_id}: on_hand={balance.on_hand}, out={quantity}"
                )
        else:  # adjust — set the absolute position
            new_on_hand = quantity

        balance.on_hand = new_on_hand
        movement = InventoryMovement(
            tenant_id=tenant_id,
            variant_id=variant_id,
            warehouse_id=warehouse_id,
            direction=direction,
            quantity=quantity,
            reason=reason,
            reference_type=reference_type,
            reference_id=reference_id,
            balance_after=new_on_hand,
        )
        session.add(movement)
        await session.flush()
        return movement

    # --------------------------------------------------- reserve/release ----

    @staticmethod
    async def reserve(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
    ) -> InventoryBalance:
        """Hold stock for an order: on_hand - reserved must cover quantity."""
        quantity = _positive_int(quantity)
        await InventoryService._get_variant(session, tenant_id, variant_id)
        await InventoryService._get_warehouse(session, tenant_id, warehouse_id)
        balance = await InventoryService._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )

        available = balance.on_hand - balance.reserved
        if available < quantity:
            raise InsufficientStockError(
                f"cannot reserve {quantity} of variant {variant_id} in warehouse "
                f"{warehouse_id}: on_hand={balance.on_hand}, "
                f"reserved={balance.reserved}, available={available}"
            )
        balance.reserved += quantity
        await session.flush()
        return balance

    @staticmethod
    async def release(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
    ) -> InventoryBalance:
        """Give reserved stock back; never drops reserved below zero."""
        quantity = _positive_int(quantity)
        await InventoryService._get_variant(session, tenant_id, variant_id)
        await InventoryService._get_warehouse(session, tenant_id, warehouse_id)
        balance = await InventoryService._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )

        balance.reserved = max(0, balance.reserved - quantity)
        await session.flush()
        return balance

    # ----------------------------------------------------------- balance ----

    @staticmethod
    async def get_balance(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID, warehouse_id: UUID
    ) -> InventoryBalance:
        """Current position (created with zeros on first sight, no lock)."""
        balance = (
            await session.execute(
                select(InventoryBalance).where(
                    InventoryBalance.tenant_id == tenant_id,
                    InventoryBalance.warehouse_id == warehouse_id,
                    InventoryBalance.variant_id == variant_id,
                )
            )
        ).scalar_one_or_none()
        if balance is not None:
            return balance
        await InventoryService._ensure_balance_row(
            session, tenant_id, variant_id, warehouse_id
        )
        return (
            await session.execute(
                select(InventoryBalance).where(
                    InventoryBalance.tenant_id == tenant_id,
                    InventoryBalance.warehouse_id == warehouse_id,
                    InventoryBalance.variant_id == variant_id,
                )
            )
        ).scalar_one()

    @staticmethod
    async def list_movements(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InventoryMovement]:
        """Ledger for a variant, newest first."""
        stmt = (
            select(InventoryMovement)
            .where(
                InventoryMovement.tenant_id == tenant_id,
                InventoryMovement.variant_id == variant_id,
            )
            .order_by(
                InventoryMovement.created_at.desc(), InventoryMovement.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(stmt)).scalars().all())

    # --------------------------------------------------------- transfers ----

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
        await InventoryService._get_warehouse(session, tenant_id, from_warehouse_id)
        await InventoryService._get_warehouse(session, tenant_id, to_warehouse_id)

        normalized: list[dict] = []
        for line in lines:
            quantity = _positive_int(line.get("quantity"))
            variant_id = line.get("variant_id")
            if variant_id is None:
                raise ValueError("each transfer line needs a variant_id")
            normalized.append(
                {"variant_id": str(variant_id), "quantity": quantity}
            )

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
        transfer = await InventoryService.get_transfer(session, tenant_id, transfer_id)
        if transfer.status not in _TRANSFER_STATUSES:
            raise ConflictError(
                f"transfer {transfer_id} cannot be completed from status "
                f"'{transfer.status}'"
            )

        for line in transfer.lines or []:
            variant_id = UUID(str(line["variant_id"]))
            quantity = int(line["quantity"])
            await InventoryService.move(
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
            await InventoryService.move(
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

    # ----------------------------------------------------------- helpers ----

    @staticmethod
    async def _get_variant(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID
    ) -> ProductVariant:
        """Existence + tenant check (inactive variants still hold stock)."""
        variant = (
            await session.execute(
                select(ProductVariant).where(
                    ProductVariant.id == variant_id,
                    ProductVariant.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if variant is None:
            raise NotFoundError(f"variant {variant_id} not found")
        return variant

    @staticmethod
    async def _get_warehouse(
        session: AsyncSession, tenant_id: UUID, warehouse_id: UUID
    ) -> Warehouse:
        warehouse = (
            await session.execute(
                select(Warehouse).where(
                    Warehouse.id == warehouse_id,
                    Warehouse.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if warehouse is None:
            raise NotFoundError(f"warehouse {warehouse_id} not found")
        return warehouse

    @staticmethod
    async def _locked_balance(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
    ) -> InventoryBalance:
        """Fetch the balance row FOR UPDATE, creating it with zeros if absent."""
        stmt = select(InventoryBalance).where(
            InventoryBalance.tenant_id == tenant_id,
            InventoryBalance.warehouse_id == warehouse_id,
            InventoryBalance.variant_id == variant_id,
        )
        balance = (await session.execute(stmt.with_for_update())).scalar_one_or_none()
        if balance is not None:
            return balance
        await InventoryService._ensure_balance_row(
            session, tenant_id, variant_id, warehouse_id
        )
        return (await session.execute(stmt.with_for_update())).scalar_one()

    @staticmethod
    async def _ensure_balance_row(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
    ) -> None:
        """Create the zeroed balance row; concurrent creators converge."""
        await session.execute(
            pg_insert(InventoryBalance)
            .values(
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                variant_id=variant_id,
                on_hand=0,
                reserved=0,
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "warehouse_id", "variant_id"]
            )
        )

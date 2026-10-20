"""Balance operations and warehouse access for InventoryService."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import NotFoundError
from app.modules.inventory.models import InventoryBalance, Warehouse


class BalanceServiceMixin:
    """Balance queries, locking, warehouse bootstrapping, and catalog variant lookup."""

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
        await BalanceServiceMixin._ensure_balance_row(session, tenant_id, variant_id, warehouse_id)
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
    async def total_on_hand(session: AsyncSession, tenant_id: UUID, variant_id: UUID) -> int:
        """Units of a variant on the shelf across ALL warehouses (0 if never stocked).

        Read-only and unlocked: a caller that needs a stable figure (moving-average cost)
        takes its own lock first. May be negative: stock can be sold before the receipt is entered.
        """
        total = (
            await session.execute(
                select(func.coalesce(func.sum(InventoryBalance.on_hand), 0)).where(
                    InventoryBalance.tenant_id == tenant_id,
                    InventoryBalance.variant_id == variant_id,
                )
            )
        ).scalar_one()
        return int(total)

    @staticmethod
    async def list_balances(session: AsyncSession, tenant_id: UUID, *, limit: int = 200) -> list:
        rows = (
            (
                await session.execute(
                    select(InventoryBalance)
                    .where(InventoryBalance.tenant_id == tenant_id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    @staticmethod
    async def get_warehouse(
        session: AsyncSession, tenant_id: UUID, warehouse_id: UUID
    ) -> Warehouse:
        """Public cross-module accessor — delegates to the private helper (§8)."""
        return await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)

    @staticmethod
    async def get_default_warehouse(session: AsyncSession, tenant_id: UUID) -> Warehouse:
        """The tenant's first active warehouse, bootstrapping 'Main' if needed.

        Moved here from OrderService so orders never touches the Warehouse
        model directly (§8 module-boundary rule).
        """
        warehouse = (
            await session.execute(
                select(Warehouse)
                .where(
                    Warehouse.tenant_id == tenant_id,
                    Warehouse.is_active.is_(True),
                )
                .order_by(Warehouse.created_at.asc(), Warehouse.name.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if warehouse is not None:
            return warehouse

        # No warehouse yet — create "Main" (race-safe: converge on one row).
        await session.execute(
            pg_insert(Warehouse)
            .values(tenant_id=tenant_id, name="Main", code="MAIN")
            .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        )
        # Retry the read: a competing bootstrap may still be uncommitted.
        for _attempt in range(3):
            try:
                return (
                    await session.execute(
                        select(Warehouse).where(
                            Warehouse.tenant_id == tenant_id,
                            Warehouse.code == "MAIN",
                        )
                    )
                ).scalar_one()
            except NoResultFound:
                await session.rollback()
                continue
        # Last-resort: try one more time without rollback
        return (
            await session.execute(
                select(Warehouse).where(
                    Warehouse.tenant_id == tenant_id,
                    Warehouse.code == "MAIN",
                )
            )
        ).scalar_one()

    @staticmethod
    async def _get_variant(session: AsyncSession, tenant_id: UUID, variant_id: UUID):
        """Existence + tenant check (inactive variants still hold stock).

        §8: delegates to CatalogService instead of importing catalog models.
        """
        from app.modules.catalog.service import CatalogService

        return await CatalogService.get_variant(
            session, tenant_id, variant_id, include_inactive=True
        )

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
        await BalanceServiceMixin._ensure_balance_row(session, tenant_id, variant_id, warehouse_id)
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
            .on_conflict_do_nothing(index_elements=["tenant_id", "warehouse_id", "variant_id"])
        )

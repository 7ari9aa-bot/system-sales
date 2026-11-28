"""Channel Allocation Service (§4 Phase 7).

Manages stock quota per sales channel (e.g. pos, website, whatsapp) so one channel
cannot exhaust the inventory reserved for other channels.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.applications.apparel.modules.inventory.models import InventoryChannelAllocation
from app.applications.apparel.modules.inventory.services._common import InsufficientStockError
from app.applications.apparel.modules.inventory.services.balances import BalanceServiceMixin


class ChannelAllocationService:
    """Channel allocation management: quotas, availability, channel reservations."""

    @staticmethod
    async def set_allocation(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        variant_id: UUID,
        channel: str,
        quantity: int,
    ) -> InventoryChannelAllocation:
        """Set or update the allocated quantity for a channel."""
        if quantity < 0:
            raise ValidationError("quantity must be non-negative")
        channel = (channel or "").strip().lower()
        if not channel:
            raise ValidationError("channel cannot be empty")

        await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)
        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)

        balance = await BalanceServiceMixin._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )
        sellable = balance.on_hand - balance.quarantined

        # Other channels' allocations for this variant at this warehouse
        allocations = list(
            (
                await session.execute(
                    select(InventoryChannelAllocation)
                    .where(
                        InventoryChannelAllocation.tenant_id == tenant_id,
                        InventoryChannelAllocation.warehouse_id == warehouse_id,
                        InventoryChannelAllocation.variant_id == variant_id,
                    )
                    .with_for_update()
                )
            ).scalars()
        )

        other_allocated = sum(a.allocated_quantity for a in allocations if a.channel != channel)
        if other_allocated + quantity > sellable:
            raise InsufficientStockError(
                f"Cannot allocate {quantity} to channel {channel!r}: "
                f"total allocations ({other_allocated + quantity}) "
                f"would exceed sellable stock ({sellable})"
            )

        allocation = next((a for a in allocations if a.channel == channel), None)
        if allocation is None:
            allocation = InventoryChannelAllocation(
                tenant_id=tenant_id,
                warehouse_id=warehouse_id,
                variant_id=variant_id,
                channel=channel,
                allocated_quantity=quantity,
                reserved_in_channel=0,
            )
            session.add(allocation)
        else:
            if quantity < allocation.reserved_in_channel:
                raise ConflictError(
                    f"cannot reduce allocation to {quantity} below currently "
                    f"reserved units ({allocation.reserved_in_channel})"
                )
            allocation.allocated_quantity = quantity

        await session.flush()
        return allocation

    @staticmethod
    async def get_allocation(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        allocation_id: UUID,
    ) -> InventoryChannelAllocation | None:
        return (
            await session.execute(
                select(InventoryChannelAllocation).where(
                    InventoryChannelAllocation.tenant_id == tenant_id,
                    InventoryChannelAllocation.id == allocation_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_allocations(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID | None = None,
        variant_id: UUID | None = None,
        channel: str | None = None,
    ) -> list[InventoryChannelAllocation]:
        q = select(InventoryChannelAllocation).where(
            InventoryChannelAllocation.tenant_id == tenant_id
        )
        if warehouse_id:
            q = q.where(InventoryChannelAllocation.warehouse_id == warehouse_id)
        if variant_id:
            q = q.where(InventoryChannelAllocation.variant_id == variant_id)
        if channel:
            q = q.where(InventoryChannelAllocation.channel == channel.strip().lower())
        q = q.order_by(InventoryChannelAllocation.channel.asc())
        return list((await session.execute(q)).scalars())

    @staticmethod
    async def delete_allocation(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        allocation_id: UUID,
    ) -> None:
        alloc = await ChannelAllocationService.get_allocation(
            session, tenant_id, allocation_id=allocation_id
        )
        if alloc is None:
            raise NotFoundError(f"channel allocation {allocation_id} not found")
        if alloc.reserved_in_channel > 0:
            raise ConflictError(
                f"cannot delete channel allocation with {alloc.reserved_in_channel} reserved units"
            )
        await session.execute(
            delete(InventoryChannelAllocation).where(
                InventoryChannelAllocation.tenant_id == tenant_id,
                InventoryChannelAllocation.id == allocation_id,
            )
        )
        await session.flush()

    @staticmethod
    async def get_channel_availability(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        variant_id: UUID,
        channel: str,
    ) -> dict:
        """Calculate available stock for a specific sales channel."""
        channel = (channel or "").strip().lower()
        balance = await BalanceServiceMixin.get_balance(
            session, tenant_id, variant_id, warehouse_id
        )
        global_available = max(0, balance.on_hand - balance.quarantined - balance.reserved)

        allocations = list(
            (
                await session.execute(
                    select(InventoryChannelAllocation).where(
                        InventoryChannelAllocation.tenant_id == tenant_id,
                        InventoryChannelAllocation.warehouse_id == warehouse_id,
                        InventoryChannelAllocation.variant_id == variant_id,
                    )
                )
            ).scalars()
        )

        # If NO allocations exist for this variant, all unreserved stock is free for any channel
        if not allocations:
            return {
                "variant_id": variant_id,
                "warehouse_id": warehouse_id,
                "channel": channel,
                "available_quantity": global_available,
                "allocated_quantity": None,
                "reserved_in_channel": 0,
                "global_available": global_available,
            }

        target_alloc = next((a for a in allocations if a.channel == channel), None)
        if target_alloc is not None:
            channel_avail = max(
                0, target_alloc.allocated_quantity - target_alloc.reserved_in_channel
            )
            return {
                "variant_id": variant_id,
                "warehouse_id": warehouse_id,
                "channel": channel,
                "available_quantity": min(channel_avail, global_available),
                "allocated_quantity": target_alloc.allocated_quantity,
                "reserved_in_channel": target_alloc.reserved_in_channel,
                "global_available": global_available,
            }

        # Other channels have allocations, but this channel has no specific quota.
        # It can only draw from the unallocated pool.
        sellable = max(0, balance.on_hand - balance.quarantined)
        total_allocated = sum(a.allocated_quantity for a in allocations)
        unallocated_stock = max(0, sellable - total_allocated)

        alloc_reserved = sum(a.reserved_in_channel for a in allocations)
        unallocated_reserved = max(0, balance.reserved - alloc_reserved)
        unallocated_available = max(0, unallocated_stock - unallocated_reserved)

        return {
            "variant_id": variant_id,
            "warehouse_id": warehouse_id,
            "channel": channel,
            "available_quantity": min(unallocated_available, global_available),
            "allocated_quantity": 0,
            "reserved_in_channel": 0,
            "global_available": global_available,
        }

    @staticmethod
    async def reserve_in_channel(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        variant_id: UUID,
        channel: str,
        quantity: int,
    ) -> InventoryChannelAllocation | None:
        """Reserve stock inside a channel's quota under lock."""
        channel = (channel or "").strip().lower()
        if not channel:
            return None

        allocations = list(
            (
                await session.execute(
                    select(InventoryChannelAllocation)
                    .where(
                        InventoryChannelAllocation.tenant_id == tenant_id,
                        InventoryChannelAllocation.warehouse_id == warehouse_id,
                        InventoryChannelAllocation.variant_id == variant_id,
                    )
                    .with_for_update()
                )
            ).scalars()
        )

        if not allocations:
            # No channel quotas configured for this item: legacy shared behavior
            return None

        target = next((a for a in allocations if a.channel == channel), None)
        if target is not None:
            channel_avail = target.allocated_quantity - target.reserved_in_channel
            if channel_avail < quantity:
                raise InsufficientStockError(
                    f"cannot reserve {quantity} in channel {channel!r}: "
                    f"allocated={target.allocated_quantity}, "
                    f"reserved={target.reserved_in_channel}, "
                    f"available={channel_avail}"
                )
            target.reserved_in_channel += quantity
            await session.flush()
            return target

        # If allocations exist for other channels, verify unallocated capacity
        balance = await BalanceServiceMixin._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )
        sellable = balance.on_hand - balance.quarantined
        total_allocated = sum(a.allocated_quantity for a in allocations)
        unallocated_stock = max(0, sellable - total_allocated)
        alloc_reserved = sum(a.reserved_in_channel for a in allocations)
        unallocated_reserved = max(0, balance.reserved - alloc_reserved)
        unallocated_avail = unallocated_stock - unallocated_reserved
        if unallocated_avail < quantity:
            raise InsufficientStockError(
                f"cannot reserve {quantity} in unallocated channel {channel!r}: "
                f"unallocated pool available={unallocated_avail}"
            )
        return None

    @staticmethod
    async def release_from_channel(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        variant_id: UUID,
        channel: str,
        quantity: int,
    ) -> None:
        """Release previously reserved units in a channel quota."""
        channel = (channel or "").strip().lower()
        if not channel:
            return

        target = (
            await session.execute(
                select(InventoryChannelAllocation)
                .where(
                    InventoryChannelAllocation.tenant_id == tenant_id,
                    InventoryChannelAllocation.warehouse_id == warehouse_id,
                    InventoryChannelAllocation.variant_id == variant_id,
                    InventoryChannelAllocation.channel == channel,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

        if target is not None:
            target.reserved_in_channel = max(0, target.reserved_in_channel - quantity)
            await session.flush()

    @staticmethod
    async def deduct_channel_allocation(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        variant_id: UUID,
        channel: str,
        quantity: int,
    ) -> None:
        """When an allocated unit is sold, decrease both allocation and channel reservation."""
        channel = (channel or "").strip().lower()
        if not channel:
            return

        target = (
            await session.execute(
                select(InventoryChannelAllocation)
                .where(
                    InventoryChannelAllocation.tenant_id == tenant_id,
                    InventoryChannelAllocation.warehouse_id == warehouse_id,
                    InventoryChannelAllocation.variant_id == variant_id,
                    InventoryChannelAllocation.channel == channel,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

        if target is not None:
            target.allocated_quantity = max(0, target.allocated_quantity - quantity)
            target.reserved_in_channel = max(0, target.reserved_in_channel - quantity)
            await session.flush()

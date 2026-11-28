"""Inventory services package — combines mixins into InventoryService."""

from __future__ import annotations

from ._common import (
    AVAILABILITY_MOVEMENT_REASONS,
    MOVEMENT_DIRECTION_PATTERN,
    MOVEMENT_REASON_FILTER_PATTERN,
    MOVEMENT_REASON_PATTERN,
    MOVEMENT_REASONS,
    PHYSICAL_MOVEMENT_REASONS,
    RESERVATION_REFERENCE,
    ConflictError,
    InsufficientStockError,
    NotFoundError,
    ValidationError,
    check_movement_shape,
    check_physical_settlement,
)
from .balances import BalanceServiceMixin
from .bundles import InventoryBundleService
from .channel_allocation import ChannelAllocationService
from .locations import WarehouseLocationService
from .movements import MovementServiceMixin
from .quality import QualityInspectionService
from .replenishment import ReplenishmentService
from .reporting import InventoryReportingService
from .reservations import InventoryReservationService
from .stocktakes import StocktakeService
from .traceability import TraceabilityService
from .transfers import TransferServiceMixin
from .valuation import ValuationService


class InventoryService(BalanceServiceMixin, MovementServiceMixin, TransferServiceMixin):
    """All stock business rules; static methods taking (session, tenant_id)."""


__all__ = [
    "InventoryService",
    "InventoryReservationService",
    "StocktakeService",
    "QualityInspectionService",
    "WarehouseLocationService",
    "ReplenishmentService",
    "ValuationService",
    "InventoryBundleService",
    "TraceabilityService",
    "InventoryReportingService",
    "ChannelAllocationService",
    "ConflictError",
    "NotFoundError",
    "ValidationError",
    "InsufficientStockError",
    "check_movement_shape",
    "check_physical_settlement",
    "PHYSICAL_MOVEMENT_REASONS",
    "AVAILABILITY_MOVEMENT_REASONS",
    "MOVEMENT_REASONS",
    "RESERVATION_REFERENCE",
    "MOVEMENT_DIRECTION_PATTERN",
    "MOVEMENT_REASON_PATTERN",
    "MOVEMENT_REASON_FILTER_PATTERN",
    "BalanceServiceMixin",
    "MovementServiceMixin",
    "TransferServiceMixin",
]

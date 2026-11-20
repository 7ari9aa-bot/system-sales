"""INVENTORY domain service — the stock ledger and its rules.

.. deprecated:: refactored
   Domain logic now lives under ``app.modules.inventory.services.*``.
   This file is a backward-compatible aggregator that re-exports ``InventoryService``,
   ``InventoryReservationService``, and ledger constants/helpers so existing imports
   keep working.
"""

from __future__ import annotations

from app.modules.inventory.services import (
    AVAILABILITY_MOVEMENT_REASONS,
    MOVEMENT_DIRECTION_PATTERN,
    MOVEMENT_REASON_FILTER_PATTERN,
    MOVEMENT_REASON_PATTERN,
    MOVEMENT_REASONS,
    PHYSICAL_MOVEMENT_REASONS,
    RESERVATION_REFERENCE,
    ChannelAllocationService,
    ConflictError,
    InsufficientStockError,
    InventoryBundleService,
    InventoryReportingService,
    InventoryReservationService,
    InventoryService,
    NotFoundError,
    QualityInspectionService,
    ReplenishmentService,
    StocktakeService,
    TraceabilityService,
    ValidationError,
    ValuationService,
    WarehouseLocationService,
    check_movement_shape,
    check_physical_settlement,
)
from app.modules.inventory.services.expiry import find_or_create_lot

# Preserve __module__ for test reflection and introspection
InventoryService.__module__ = "app.modules.inventory.service"
InventoryReservationService.__module__ = "app.modules.inventory.service"
InventoryService.QualityInspectionService = QualityInspectionService  # type: ignore[attr-defined]
InventoryService.ReplenishmentService = ReplenishmentService  # type: ignore[attr-defined]
InventoryService.StocktakeService = StocktakeService  # type: ignore[attr-defined]
InventoryService.WarehouseLocationService = WarehouseLocationService  # type: ignore[attr-defined]
InventoryService.ValuationService = ValuationService  # type: ignore[attr-defined]
InventoryService.InventoryBundleService = InventoryBundleService  # type: ignore[attr-defined]
InventoryService.TraceabilityService = TraceabilityService  # type: ignore[attr-defined]
InventoryService.InventoryReportingService = InventoryReportingService  # type: ignore[attr-defined]
InventoryService.ChannelAllocationService = ChannelAllocationService  # type: ignore[attr-defined]
InventoryService.find_or_create_lot = staticmethod(find_or_create_lot)  # type: ignore[attr-defined]

__all__ = [
    "InventoryService",
    "InventoryReservationService",
    "QualityInspectionService",
    "ReplenishmentService",
    "StocktakeService",
    "WarehouseLocationService",
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
]

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
    ConflictError,
    InsufficientStockError,
    InventoryReservationService,
    InventoryService,
    NotFoundError,
    ValidationError,
    check_movement_shape,
    check_physical_settlement,
)

# Preserve __module__ for test reflection and introspection
InventoryService.__module__ = "app.modules.inventory.service"
InventoryReservationService.__module__ = "app.modules.inventory.service"

__all__ = [
    "InventoryService",
    "InventoryReservationService",
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

"""Common constants, helpers, and validation for inventory services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

# These four are pure re-exports: services/__init__.py pulls them from this
# module — removing them (a ruff F401 sweep read them as dead) broke the
# package import chain for every inventory consumer.
from app.modules.errors import (  # noqa: F401
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.modules.orders.errors import InsufficientStockError  # noqa: F401

_DIRECTIONS = {"in", "out", "adjust"}
# Availability directions: they change `reserved`, never `on_hand`, and are
# written only by reserve()/release() — hence their absence from
# _DIRECTIONS and from the route's direction pattern.
_AVAILABILITY_DIRECTIONS = {"hold", "release"}

# The ledger's reason vocabulary — a CLOSED set (M9).
PHYSICAL_MOVEMENT_REASONS: frozenset[str] = frozenset(
    {
        "purchase",
        "sale",
        "return",
        "return_reversal",
        "transfer_in",
        "transfer_out",
        "adjustment",
        "damage",
        # Goods LEAVING the shop back to a supplier (`return` is a CUSTOMER bringing goods in).
        # Written only by the purchasing service (reference_type='supplier_return'); it is
        # deliberately NOT in the hand-written API pattern below.
        "supplier_return",
        # The supplier REFUSED those goods and they went back on the shelf. Not `return_reversal`:
        # that one undoes a CUSTOMER return, and a report filtering on it must not mix the two.
        "supplier_return_reversal",
    }
)
#: Reasons only a domain service may write. A person typing one into POST /inventory/movements
#: would fake goods leaving to a supplier that no document claims.
SERVICE_ONLY_MOVEMENT_REASONS: frozenset[str] = frozenset(
    {"supplier_return", "supplier_return_reversal"}
)
AVAILABILITY_MOVEMENT_REASONS: frozenset[str] = frozenset({"reservation", "reservation_release"})
MOVEMENT_REASONS: frozenset[str] = PHYSICAL_MOVEMENT_REASONS | AVAILABILITY_MOVEMENT_REASONS
#: `reference_type` of a durable reservation, so a release names what it freed.
RESERVATION_REFERENCE = "inventory_reservation"

#: Patterns for the request models: a whitelist the API document can show.
MOVEMENT_DIRECTION_PATTERN = "^(?:" + "|".join(sorted(_DIRECTIONS)) + ")$"
MOVEMENT_REASON_PATTERN = (
    "^(?:" + "|".join(sorted(PHYSICAL_MOVEMENT_REASONS - SERVICE_ONLY_MOVEMENT_REASONS)) + ")$"
)
#: The read filter may name ANY reason — the hold rows are what an auditor
#: reconciling on_hand against available has to be able to ask for.
MOVEMENT_REASON_FILTER_PATTERN = "^(?:" + "|".join(sorted(MOVEMENT_REASONS)) + ")$"

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


def check_movement_shape(direction: str, reason: str) -> None:
    """Reject a reason/direction pair the ledger cannot be read back.

    Runs BEFORE any session access, so junk input is a 400 rather than a query
    that happens to fail later. A physical reason must ride a physical direction
    and an availability reason must ride `hold`/`release`: mixing them is how a
    hold would read as goods leaving the warehouse. An unknown direction stays a
    ValueError, which is what `move` has always raised for it.
    """
    if reason not in MOVEMENT_REASONS:
        raise ValidationError(
            f"reason must be one of {sorted(MOVEMENT_REASONS)}",
            details={"reason": reason},
        )
    if direction not in _DIRECTIONS | _AVAILABILITY_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(_DIRECTIONS | _AVAILABILITY_DIRECTIONS)}"
        )
    physical = direction in _DIRECTIONS
    if physical == (reason in AVAILABILITY_MOVEMENT_REASONS):
        raise ValidationError(
            f"direction {direction!r} does not pair with reason {reason!r}: "
            f"'in|out|adjust' take {sorted(PHYSICAL_MOVEMENT_REASONS)}, "
            f"'hold|release' take {sorted(AVAILABILITY_MOVEMENT_REASONS)}",
            details={"direction": direction, "reason": reason},
        )


def check_physical_settlement(
    *,
    on_hand: int,
    quantity: int,
    variant_id: UUID,
    warehouse_id: UUID,
    context: str | None = None,
) -> int:
    """The `out` quantity a settling event may book, or a loud refusal."""
    if quantity > on_hand:
        raise InsufficientStockError(
            f"cannot settle {quantity} of variant {variant_id} in warehouse "
            f"{warehouse_id}: on_hand={on_hand}, sale={quantity}, "
            f"shortfall={quantity - on_hand}" + (f" ({context})" if context else "")
        )
    return quantity

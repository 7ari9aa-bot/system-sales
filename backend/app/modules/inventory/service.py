"""INVENTORY domain service — the stock ledger and its rules.

inventory_movements is the append-only ledger; inventory_balances holds the
current position and is always mutated under SELECT ... FOR UPDATE so
concurrent checkouts serialize. Every method takes the caller's session and
tenant and NEVER commits.

The promise both tables keep is `on_hand == Σ signed physical movements` (and
`reserved == Σ hold - Σ release`). Every writer therefore either moves the
column and the row by the SAME quantity, or refuses — a `max(0, …)` on one side
only is what turns a transient drift into a permanently unreconcilable ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.models import (
    InventoryBalance,
    InventoryMovement,
    InventoryReservation,
    InventoryTransfer,
    Warehouse,
)
from app.modules.orders.errors import InsufficientStockError

_DIRECTIONS = {"in", "out", "adjust"}
# Availability directions: they change `reserved`, never `on_hand`, and are
# written only by reserve()/release() below — hence their absence from
# _DIRECTIONS and from the route's direction pattern.
_AVAILABILITY_DIRECTIONS = {"hold", "release"}

# The ledger's reason vocabulary — a CLOSED set (M9). It was free text, so
# "what happened to this stock" could not be grouped, filtered or reconciled.
# Enumerated from the writers that exist:
#   purchase / adjustment  restock intake and the manual stocktake route
#   sale                   InventoryReservationService.convert
#   return / return_reversal   orders/returns (the order_return saga, ADR-052)
#   transfer_in / transfer_out complete_transfer
#   damage   documented shrinkage (models.py)
#   reservation / reservation_release  the hold pair (this module)
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
    }
)
AVAILABILITY_MOVEMENT_REASONS: frozenset[str] = frozenset({"reservation", "reservation_release"})
MOVEMENT_REASONS: frozenset[str] = PHYSICAL_MOVEMENT_REASONS | AVAILABILITY_MOVEMENT_REASONS
#: `reference_type` of a durable reservation, so a release names what it freed.
RESERVATION_REFERENCE = "inventory_reservation"

#: Patterns for the request models: a whitelist the API document can show.
MOVEMENT_DIRECTION_PATTERN = "^(?:" + "|".join(sorted(_DIRECTIONS)) + ")$"
MOVEMENT_REASON_PATTERN = "^(?:" + "|".join(sorted(PHYSICAL_MOVEMENT_REASONS)) + ")$"
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
    """The `out` quantity a settling event may book, or a loud refusal.

    A balance that has drifted below what a reservation holds — someone
    hand-corrected the row, a stocktake counted part of the shelf, a race moved
    the same units twice — is a real and recurring state in this system. The
    question is what the LEDGER does about it, because `inventory_movements` is
    the only reason `on_hand` is auditable: the invariant the whole module
    exists to keep is

        on_hand == Σ signed physical movements

    This refuses (raising the module's existing `InsufficientStockError`, the
    same one `move(direction="out")` and `reserve()` raise for this exact
    condition) rather than the two alternatives:

    * clamp the ROW to the applied delta: the sums would keep agreeing, but a
      2-unit `out`/sale would be booked against a 3-unit order line, and the
      order's reservations would still flip to CONVERTED — the short-ship would
      be invisible, and unrecoverable, because returns restock the LINE
      quantity. Absorbing a drift here therefore grows stock out of nothing on
      the way back. (A clamped column plus a clamped row is also still a lie
      about what left the warehouse; it just balances.)
    * clamp and append a COMPENSATING row: honest, but the schema has no
      zero-delta movement — every row's `quantity` moves a balance, so a
      compensation either double-counts the sale or re-breaks the sum. And the
      drift already has a first-class, self-documenting writer:
      `move(direction="adjust")`, which carries the absolute count and its own
      `balance_after`. Fixing the position through that keeps the audit trail
      in the ledger instead of in a side channel.

    Refusal is the module's own established rule, so it is also the consistent
    one: the identical sale was a 409 through `POST /inventory/movements` and a
    silent rewrite of history through payment capture. And it is safe for money
    — `convert()` runs inside `add_payment`/`reconcile_payment`, neither of
    which commits (this module never commits), so the rejection rolls the
    capture back whole: no payment is recorded against stock that is not there,
    the operator restocks or adjusts, and the same capture then settles.

    Returns the quantity unchanged when the position covers it, so the caller
    books the value it checked instead of re-deriving it.
    """
    if quantity > on_hand:
        raise InsufficientStockError(
            f"cannot settle {quantity} of variant {variant_id} in warehouse "
            f"{warehouse_id}: on_hand={on_hand}, sale={quantity}, "
            f"shortfall={quantity - on_hand}" + (f" ({context})" if context else "")
        )
    return quantity


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

        The `hold`/`release` availability rows are NOT written here: a hold that
        did not move `reserved` would be a ledger lie, so they come from
        reserve()/release() only.
        """
        check_movement_shape(direction, reason)
        if direction in _AVAILABILITY_DIRECTIONS:
            raise ValidationError(
                f"direction {direction!r} is a reservation row: write it with "
                "reserve()/release(), which moves the balance as well"
            )
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
        return await InventoryService._append(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            direction=direction,
            quantity=quantity,
            reason=reason,
            balance_after=new_on_hand,
            reference_type=reference_type,
            reference_id=reference_id,
        )

    @staticmethod
    async def _append(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        *,
        direction: str,
        quantity: int,
        reason: str,
        balance_after: int,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> InventoryMovement:
        """Append one ledger row (the single writer of the append-only ledger).

        `balance_after` is ALWAYS the on-hand position, including on the
        availability rows — a hold changes `reserved`, not `on_hand`, so an
        unchanged figure there is the truth, not a missing update.
        """
        check_movement_shape(direction, reason)
        movement = InventoryMovement(
            tenant_id=tenant_id,
            variant_id=variant_id,
            warehouse_id=warehouse_id,
            direction=direction,
            quantity=quantity,
            reason=reason,
            reference_type=reference_type,
            reference_id=reference_id,
            balance_after=balance_after,
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
        """Hold stock for an order: on_hand - reserved must cover quantity.

        The hold is an accounting event and writes a ledger row (M9): without
        one, nothing explained the gap between on_hand and available.
        """
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
        # No reservation id yet: OrderService creates the durable row after the
        # order exists, and links it back (create_reservation.hold_movement_id).
        await InventoryService._append(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            direction="hold",
            quantity=quantity,
            reason="reservation",
            balance_after=balance.on_hand,
        )
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
        """Give reserved stock back; never drops reserved below zero.

        The ledger row states what was ACTUALLY freed, not what was asked: a
        redundant release (nothing left held) records nothing, so the sum of a
        reservation's releases can never exceed its hold.
        """
        quantity = _positive_int(quantity)
        await InventoryService._get_variant(session, tenant_id, variant_id)
        await InventoryService._get_warehouse(session, tenant_id, warehouse_id)
        balance = await InventoryService._locked_balance(
            session, tenant_id, variant_id, warehouse_id
        )

        freed = min(quantity, balance.reserved)
        if freed == 0:
            return balance
        balance.reserved -= freed
        await InventoryService._append_release(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            quantity=freed,
            balance_after=balance.on_hand,
        )
        await session.flush()
        return balance

    @staticmethod
    async def _append_release(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        *,
        quantity: int,
        balance_after: int,
        reservation: InventoryReservation | None = None,
    ) -> InventoryMovement:
        """Append the `release` row for `quantity` units of held stock.

        Attributes it to the reservation it freed when one can be named, so
        'what reserved this, and was it released' is answerable from the ledger.
        """
        target = reservation or await InventoryService._pair_release_with_reservation(
            session, tenant_id, variant_id, warehouse_id
        )
        return await InventoryService._append(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            direction="release",
            quantity=quantity,
            reason="reservation_release",
            balance_after=balance_after,
            reference_type=RESERVATION_REFERENCE if target else None,
            reference_id=target.id if target else None,
        )

    @staticmethod
    async def _pair_release_with_reservation(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
    ) -> InventoryReservation | None:
        """The ACTIVE reservation this release belongs to, oldest first.

        The balance holds an aggregate number and callers (OrderService,
        ReturnsService) release per line without naming a reservation, so the
        best available attribution is FIFO over the reservations still held for
        this (variant, warehouse), skipping any whose recorded releases already
        cover its quantity. The caller holds the balance row FOR UPDATE, which
        serialises this against every other hold/release on the same position.

        Known limit: one release row carries one reference, so a release larger
        than the oldest reservation's remaining hold is attributed whole to it,
        not split. Every caller today releases per reservation line (exact
        quantity), which is the case the pairing is built for.
        """
        candidates = list(
            (
                await session.execute(
                    select(InventoryReservation)
                    .where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.variant_id == variant_id,
                        InventoryReservation.warehouse_id == warehouse_id,
                        InventoryReservation.status == "ACTIVE",
                    )
                    .order_by(
                        InventoryReservation.created_at.asc(),
                        InventoryReservation.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidates:
            return None
        released = dict(
            (
                await session.execute(
                    select(
                        InventoryMovement.reference_id,
                        func.sum(InventoryMovement.quantity),
                    )
                    .where(
                        InventoryMovement.tenant_id == tenant_id,
                        InventoryMovement.reason == "reservation_release",
                        InventoryMovement.reference_type == RESERVATION_REFERENCE,
                        InventoryMovement.reference_id.in_([r.id for r in candidates]),
                    )
                    .group_by(InventoryMovement.reference_id)
                )
            ).all()
        )
        for reservation in candidates:
            if int(released.get(reservation.id) or 0) < reservation.quantity:
                return reservation
        return None

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
        await InventoryService._ensure_balance_row(session, tenant_id, variant_id, warehouse_id)
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
        variant_id: UUID | None = None,
        *,
        reason: str | None = None,
        reservation_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InventoryMovement]:
        """Ledger, newest first — one variant, or the whole tenant's when None.

        `None` is "no filter", not `== NULL`: the route's optional variant filter
        arrives as None, and comparing a column to NULL matches no row, which
        made the unfiltered ledger always empty.

        `reservation_id` answers "what reserved this, and was it released": it
        returns the hold row (linked from the reservation row's
        `hold_movement_id`, since the hold is written before the durable row
        exists) plus every release row that names the reservation.
        """
        stmt = select(InventoryMovement).where(InventoryMovement.tenant_id == tenant_id)
        if variant_id is not None:
            stmt = stmt.where(InventoryMovement.variant_id == variant_id)
        if reason is not None:
            if reason not in MOVEMENT_REASONS:
                raise ValidationError(
                    f"reason must be one of {sorted(MOVEMENT_REASONS)}",
                    details={"reason": reason},
                )
            stmt = stmt.where(InventoryMovement.reason == reason)
        if reservation_id is not None:
            hold_movement_id = (
                await session.execute(
                    select(InventoryReservation.hold_movement_id).where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.id == reservation_id,
                    )
                )
            ).scalar_one_or_none()
            # BOTH halves of the polymorphic pair, not the type alone: OR-ing on
            # `reference_type` would leak every other reservation's releases.
            linked = [
                and_(
                    InventoryMovement.reference_type == RESERVATION_REFERENCE,
                    InventoryMovement.reference_id == reservation_id,
                )
            ]
            if hold_movement_id is not None:
                linked.append(InventoryMovement.id == hold_movement_id)
            stmt = stmt.where(or_(*linked))
        stmt = (
            stmt.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
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
        transfer = await InventoryService.get_transfer(session, tenant_id, transfer_id)
        if transfer.status not in _TRANSFER_STATUSES:
            raise ConflictError(
                f"transfer {transfer_id} cannot be completed from status '{transfer.status}'"
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
        await InventoryService._ensure_balance_row(session, tenant_id, variant_id, warehouse_id)
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

    @staticmethod
    async def list_balances(session: AsyncSession, tenant_id: UUID, *, limit: int = 200) -> list:
        from app.modules.inventory.models import InventoryBalance

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

    # --------------------------------------------------- public warehouse ---

    @staticmethod
    async def get_warehouse(
        session: AsyncSession, tenant_id: UUID, warehouse_id: UUID
    ) -> Warehouse:
        """Public cross-module accessor — delegates to the private helper (§8)."""
        return await InventoryService._get_warehouse(session, tenant_id, warehouse_id)

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
    async def create_reservation(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
        order_id: UUID,
        quantity: int,
        expires_at: datetime,
    ) -> None:
        """Create a durable reservation row (§140) — cross-module safe (§8).

        Orders calls this instead of touching InventoryReservation directly. The
        balance hold was already taken by InventoryService.reserve (which needed
        to abort the order on insufficient stock, before this row or the order
        existed), so this links the durable row back to that ledger row.
        """
        from app.modules.inventory.models import InventoryReservation

        reservation = InventoryReservation(
            tenant_id=tenant_id,
            variant_id=variant_id,
            warehouse_id=warehouse_id,
            order_id=order_id,
            quantity=quantity,
            status="ACTIVE",
            expires_at=expires_at,
        )
        session.add(reservation)
        reservation.hold_movement_id = await InventoryService._unclaimed_hold(
            session, tenant_id, variant_id, warehouse_id, quantity
        )
        await session.flush()

    @staticmethod
    async def _unclaimed_hold(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
    ) -> UUID | None:
        """The oldest `hold` row not yet owned by a reservation, or None.

        Oldest-first because the caller holds and then registers lines in the
        same order, so the pairing is stable; None is tolerated (a hold written
        before this ledger existed simply stays unlinked).
        """
        claimed = select(InventoryReservation.hold_movement_id).where(
            InventoryReservation.tenant_id == tenant_id,
            InventoryReservation.hold_movement_id.is_not(None),
        )
        return (
            await session.execute(
                select(InventoryMovement.id)
                .where(
                    InventoryMovement.tenant_id == tenant_id,
                    InventoryMovement.variant_id == variant_id,
                    InventoryMovement.warehouse_id == warehouse_id,
                    InventoryMovement.reason == "reservation",
                    InventoryMovement.quantity == quantity,
                    ~InventoryMovement.id.in_(claimed),
                )
                .order_by(InventoryMovement.created_at.asc(), InventoryMovement.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()


class InventoryReservationService:
    """Lifecycle of the durable reservation rows (spec §140).

    Rows are created by OrderService.create_order next to the balance hold;
    CONVERTED on payment capture, CANCELLED on order cancellation, EXPIRED by
    the maintenance worker. Only ACTIVE reservations count against
    availability (the balances above are the operational truth).
    """

    @staticmethod
    async def convert(session: AsyncSession, tenant_id: UUID, order_id: UUID) -> int:
        """Mark the order's ACTIVE reservations CONVERTED (payment captured).

        Conversion settles the stock: the hold is released (reserved -= qty)
        AND the goods leave the warehouse (on_hand -= qty), with an `out`/sale
        movement recording the new balance. The earlier attempt released the
        hold but never decremented on_hand — the movement said "goods left"
        while the stock stayed, so the same unit could be sold again.

        A capture that the shelf cannot cover — a reservation larger than
        `on_hand` because the position drifted after the hold — is REFUSED with
        `InsufficientStockError` before any row or column moves, so the whole
        payment capture rolls back and the ledger keeps reconciling. It used to
        clamp the column to zero and book the full sale, which hid the drift and
        broke the sum. Restock or adjust the position through `move()` (which
        records why) and the same capture settles.

        NOTE: this treats a captured payment as the moment stock moves. If
        fulfilment should instead move stock (payment captured but goods still
        in the warehouse), revert this to flip the row only and move the
        decrement to a fulfilment step — but that step does not exist yet, and
        without it paid orders leak available stock forever (C9).
        """
        reservations = (
            (
                await session.execute(
                    select(InventoryReservation)
                    .where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.order_id == order_id,
                        InventoryReservation.status == "ACTIVE",
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )

        for reservation in reservations:
            balance = await InventoryService._locked_balance(
                session, tenant_id, reservation.variant_id, reservation.warehouse_id
            )
            # Settle the physical half against what the shelf ACTUALLY holds,
            # and check it before anything is mutated: a position that drifted
            # below the hold is a refusal (`InsufficientStockError`, i.e. a 409),
            # not a `max(0, …)` clamp. The clamp used to zero the column while
            # appending the full quantity, so the row and the column disagreed
            # by the shortfall and `on_hand == Σ movements` broke silently —
            # the drift the clamp hid became a ledger that could never be
            # reconciled. See `check_physical_settlement` for why neither
            # clamping the row nor a compensating row was chosen.
            sold = check_physical_settlement(
                on_hand=balance.on_hand,
                quantity=reservation.quantity,
                variant_id=reservation.variant_id,
                warehouse_id=reservation.warehouse_id,
                context=f"converting reservation {reservation.id} for order {order_id}",
            )
            # The hold and the sale are two separate facts and both are
            # recorded: the units stop being held (`release` row, availability
            # only) and they leave the warehouse (`out`/sale row, on_hand). Only
            # the second one moves stock, so capture cannot double-count.
            freed = min(balance.reserved, reservation.quantity)
            balance.reserved -= freed
            balance.on_hand -= sold
            if freed:
                await InventoryService._append_release(
                    session,
                    tenant_id,
                    reservation.variant_id,
                    reservation.warehouse_id,
                    quantity=freed,
                    balance_after=balance.on_hand,
                    reservation=reservation,
                )
            # The physical half goes through `_append` too — it is the single
            # writer of the ledger, and every row must pass the shape check.
            # `sold` is the checked delta, so the row and the column it explains
            # can never disagree.
            await InventoryService._append(
                session,
                tenant_id,
                reservation.variant_id,
                reservation.warehouse_id,
                direction="out",
                quantity=sold,
                reason="sale",
                balance_after=balance.on_hand,
                reference_type="order",
                reference_id=order_id,
            )
            reservation.status = "CONVERTED"
            reservation.converted_at = _now()
        return len(reservations)

    @staticmethod
    async def cancel_for_order(session: AsyncSession, tenant_id: UUID, order_id: UUID) -> int:
        """Mark the order's ACTIVE reservations CANCELLED (order cancelled).

        The balance-level stock release itself stays the caller's job
        (InventoryService.release) — this only flips the durable rows.
        """
        result = await session.execute(
            update(InventoryReservation)
            .where(
                InventoryReservation.tenant_id == tenant_id,
                InventoryReservation.order_id == order_id,
                InventoryReservation.status == "ACTIVE",
            )
            .values(status="CANCELLED", cancelled_at=_now())
        )
        return result.rowcount or 0

    @staticmethod
    async def expire_stale(session: AsyncSession, tenant_id: UUID) -> int:
        """Expire past-TTL ACTIVE reservations and release their holds.

        The maintenance sweep (scheduler job `expire_reservations`). Without
        it every abandoned checkout permanently shrank availability.
        """
        reservations = (
            (
                await session.execute(
                    select(InventoryReservation)
                    .where(
                        InventoryReservation.tenant_id == tenant_id,
                        InventoryReservation.status == "ACTIVE",
                        InventoryReservation.expires_at.is_not(None),
                        InventoryReservation.expires_at < _now(),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )

        for reservation in reservations:
            balance = await InventoryService._locked_balance(
                session, tenant_id, reservation.variant_id, reservation.warehouse_id
            )
            freed = min(balance.reserved, reservation.quantity)
            balance.reserved -= freed
            if freed:
                # The sweep released real availability, so it is a ledger event
                # too — named to the reservation it expired.
                await InventoryService._append_release(
                    session,
                    tenant_id,
                    reservation.variant_id,
                    reservation.warehouse_id,
                    quantity=freed,
                    balance_after=balance.on_hand,
                    reservation=reservation,
                )
            reservation.status = "EXPIRED"
            reservation.cancelled_at = _now()
        return len(reservations)

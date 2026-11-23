"""Physical stocktake: count a warehouse against a book snapshot, then approve into the ledger.

The shop keeps selling while it is counted, so the count is compared with the book quantity as it
stood WHEN COUNTING STARTED (``expected_qty``), and approval moves only that difference, as a
relative ``in``/``out`` movement on today's balance. Writing the counted figure as an absolute
``adjust`` would erase every sale rung up between the snapshot and the approval.

A line that was not counted (``counted_qty`` NULL) is never adjusted: not counted is not zero.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.models import (
    InventoryBalance,
    Stocktake,
    StocktakeAssignment,
    StocktakeLine,
)

from ._common import _now
from .balances import BalanceServiceMixin
from .movements import MovementServiceMixin

_MAX_COUNT = 1_000_000
_VALID_KINDS = frozenset({"full", "cycle", "blind", "spot", "abc"})


def _qty(value: object, field: str) -> int:
    """A whole, non-negative count. ``True`` and ``"3"`` are not counts."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be a whole number")
    if value < 0 or value > _MAX_COUNT:
        raise ValidationError(f"{field} must be between 0 and {_MAX_COUNT}")
    return value


class StocktakeService:
    @staticmethod
    async def open(
        session: AsyncSession,
        tenant_id: UUID,
        warehouse_id: UUID,
        *,
        kind: str = "full",
        scope: list | None = None,
        blind: bool = False,
        recount_threshold_pct: int = 10,
        user_id: UUID | None = None,
        note: str | None = None,
    ) -> Stocktake:
        """Start a count: one line per variant in scope, holding book quantity."""
        if kind not in _VALID_KINDS:
            raise ValidationError(f"kind must be one of {sorted(_VALID_KINDS)}")
        if kind == "blind":
            blind = True
        recount_threshold = max(1, min(int(recount_threshold_pct), 100))

        await BalanceServiceMixin._get_warehouse(session, tenant_id, warehouse_id)
        existing = (
            await session.execute(
                select(Stocktake.id).where(
                    Stocktake.tenant_id == tenant_id,
                    Stocktake.warehouse_id == warehouse_id,
                    Stocktake.status == "OPEN",
                )
            )
        ).first()
        if existing is not None:
            raise ConflictError("this warehouse already has an open stocktake")

        stocktake = Stocktake(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            status="OPEN",
            kind=kind,
            scope=scope or [],
            blind=blind,
            recount_threshold_pct=recount_threshold,
            note=(note or "").strip()[:255] or None,
            opened_by_user_id=user_id,
        )
        session.add(stocktake)
        try:
            await session.flush()
        except IntegrityError as exc:  # two people pressed "start" together
            raise ConflictError("this warehouse already has an open stocktake") from exc

        on_hand = {
            vid: int(qty)
            for vid, qty in (
                await session.execute(
                    select(InventoryBalance.variant_id, InventoryBalance.on_hand).where(
                        InventoryBalance.tenant_id == tenant_id,
                        InventoryBalance.warehouse_id == warehouse_id,
                    )
                )
            ).all()
        }

        # Determine which variants are in scope
        scoped_variants: list[UUID] | None = None
        if scope and isinstance(scope, list):
            v_ids: list[UUID] = []
            for item in scope:
                raw = item.get("variant_id") if isinstance(item, dict) else item
                if not isinstance(raw, (str, UUID)):
                    raise ValidationError(f"stocktake scope entry has no variant id: {item!r}")
                try:
                    v_ids.append(UUID(str(raw)))
                except ValueError:
                    # Skipping it would silently widen a partial count to the whole warehouse.
                    raise ValidationError(
                        f"stocktake scope has an invalid variant id: {raw!r}"
                    ) from None
            if v_ids:
                scoped_variants = v_ids

        variant_ids = (
            scoped_variants
            if scoped_variants is not None
            else await BalanceServiceMixin._active_variant_ids(session, tenant_id)
        )

        for variant_id in variant_ids:
            session.add(
                StocktakeLine(
                    tenant_id=tenant_id,
                    stocktake_id=stocktake.id,
                    variant_id=variant_id,
                    expected_qty=max(on_hand.get(variant_id, 0), 0),
                    recount_count=0,
                )
            )
        await session.flush()
        return stocktake

    @staticmethod
    async def _get(
        session: AsyncSession, tenant_id: UUID, stocktake_id: UUID, *, lock: bool = False
    ) -> Stocktake:
        stmt = select(Stocktake).where(
            Stocktake.tenant_id == tenant_id, Stocktake.id == stocktake_id
        )
        if lock:
            stmt = stmt.with_for_update()
        found = (await session.execute(stmt)).scalar_one_or_none()
        if found is None:
            raise NotFoundError("stocktake not found")
        return found

    @staticmethod
    async def record_counts(
        session: AsyncSession,
        tenant_id: UUID,
        stocktake_id: UUID,
        counts: list[dict],
        *,
        user_id: UUID | None = None,
    ) -> int:
        """Save counted quantities (``{"variant_id", "counted_qty"}``; ``None`` un-counts a line).

        Only an OPEN count takes figures, and only for variants that are in it. Returns how many
        lines were written. One bad entry rejects the whole request so a half-saved sheet cannot
        look complete.
        """
        stocktake = await StocktakeService._get(session, tenant_id, stocktake_id, lock=True)
        if stocktake.status != "OPEN":
            raise ConflictError(f"the stocktake is {stocktake.status}, it takes no more counts")
        if not counts:
            return 0
        if len(counts) > 5000:
            raise ValidationError("at most 5000 lines per request")

        wanted: dict[UUID, int | None] = {}
        for entry in counts:
            try:
                variant_id = UUID(str(entry["variant_id"]))
            except (KeyError, ValueError):
                raise ValidationError("every count needs a valid variant_id") from None
            raw = entry.get("counted_qty")
            wanted[variant_id] = None if raw is None else _qty(raw, "counted_qty")

        lines = (
            (
                await session.execute(
                    select(StocktakeLine)
                    .where(
                        StocktakeLine.tenant_id == tenant_id,
                        StocktakeLine.stocktake_id == stocktake_id,
                        StocktakeLine.variant_id.in_(list(wanted)),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        missing = set(wanted) - {line.variant_id for line in lines}
        if missing:
            raise ValidationError(
                "some variants are not part of this stocktake", details={"count": len(missing)}
            )
        # The book quantity the counter was looking at, read once for the whole sheet. This is the
        # figure approval reconciles against, so a sale made after the count is not subtracted a
        # second time at approval.
        books = {
            row.variant_id: int(row.on_hand)
            for row in (
                await session.execute(
                    select(InventoryBalance.variant_id, InventoryBalance.on_hand).where(
                        InventoryBalance.tenant_id == tenant_id,
                        InventoryBalance.warehouse_id == stocktake.warehouse_id,
                        InventoryBalance.variant_id.in_(list(wanted)),
                    )
                )
            ).all()
        }
        for line in lines:
            new_qty = wanted[line.variant_id]
            # If changing an already-counted value, track it as a recount
            if line.counted_qty is not None and new_qty != line.counted_qty:
                line.recount_count = (line.recount_count or 0) + 1
            line.counted_qty = new_qty
            # The moment this figure became true, and the book it was measured against. Un-counting
            # clears both, so a line with no figure has neither.
            line.counted_at = _now() if new_qty is not None else None
            line.counted_book_qty = books.get(line.variant_id, 0) if new_qty is not None else None
            if user_id:
                line.counted_by_user_id = user_id

        # Update counter's assignment progress if assigned
        if user_id:
            asgn = (
                await session.execute(
                    select(StocktakeAssignment).where(
                        StocktakeAssignment.tenant_id == tenant_id,
                        StocktakeAssignment.stocktake_id == stocktake_id,
                        StocktakeAssignment.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if asgn:
                asgn.status = "counted"
                asgn.counted_at = _now()
                asgn.counted_lines = len(lines)

        await session.flush()
        return len(lines)

    @staticmethod
    async def assign_counter(
        session: AsyncSession,
        tenant_id: UUID,
        stocktake_id: UUID,
        *,
        user_id: UUID,
        location_id: UUID | None = None,
    ) -> StocktakeAssignment:
        """Assign a team member to count this stocktake or a specific warehouse location."""
        stocktake = await StocktakeService._get(session, tenant_id, stocktake_id)
        if stocktake.status != "OPEN":
            raise ConflictError(f"cannot assign counter to a {stocktake.status} stocktake")

        assignment = (
            await session.execute(
                select(StocktakeAssignment).where(
                    StocktakeAssignment.tenant_id == tenant_id,
                    StocktakeAssignment.stocktake_id == stocktake_id,
                    StocktakeAssignment.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if assignment is None:
            assignment = StocktakeAssignment(
                tenant_id=tenant_id,
                stocktake_id=stocktake_id,
                user_id=user_id,
                location_id=location_id,
                status="assigned",
            )
            session.add(assignment)
        else:
            assignment.location_id = location_id
            assignment.status = "assigned"

        await session.flush()
        return assignment

    @staticmethod
    async def cancel(
        session: AsyncSession,
        tenant_id: UUID,
        stocktake_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> Stocktake:
        """Throw an open count away. Nothing in stock moves."""
        stocktake = await StocktakeService._get(session, tenant_id, stocktake_id, lock=True)
        if stocktake.status != "OPEN":
            raise ConflictError(f"the stocktake is already {stocktake.status}")
        stocktake.status = "CANCELLED"
        stocktake.closed_at = _now()
        stocktake.closed_by_user_id = user_id
        await session.flush()
        return stocktake

    @staticmethod
    async def approve(
        session: AsyncSession,
        tenant_id: UUID,
        stocktake_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> dict:
        """Apply every counted line's difference to the ledger, once.

        The stocktake row is locked first, so a double click or two managers cannot apply it
        twice: the second sees APPROVED and is refused.

        For each counted line the difference is ``counted - book_at_count``, where
        ``book_at_count`` is the balance rebuilt at the moment the line was counted: the balance
        now, minus everything that moved in or out since. A shop sells while the sheet is being
        filled, and comparing against the count's START snapshot subtracted those sales twice (the
        dress left once and was written off as missing as well). With the rebuild, a sale during
        the count moves nothing at approval.

        The movement is ``in`` or ``out`` with reason ``adjustment``. A removal is clamped at the
        balance so approval never fails on stock a later sale already took; ``applied_delta``
        records what really moved. A line with no ``counted_at`` (counted before this column
        existed) falls back to the start snapshot.
        """
        stocktake = await StocktakeService._get(session, tenant_id, stocktake_id, lock=True)
        if stocktake.status != "OPEN":
            raise ConflictError(f"the stocktake is already {stocktake.status}")

        lines = (
            (
                await session.execute(
                    select(StocktakeLine)
                    .where(
                        StocktakeLine.tenant_id == tenant_id,
                        StocktakeLine.stocktake_id == stocktake_id,
                    )
                    .order_by(StocktakeLine.variant_id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        counted = [line for line in lines if line.counted_qty is not None]
        if not counted:
            raise ValidationError("nothing was counted yet, there is nothing to approve")

        adjusted = clamped = 0
        for line in counted:
            book_at_count = await StocktakeService._book_qty_at_count(
                session, tenant_id, line, stocktake.warehouse_id
            )
            wanted = line.counted_qty - book_at_count
            if wanted == 0:
                line.applied_delta = 0
                continue
            balance = await BalanceServiceMixin._locked_balance(
                session, tenant_id, line.variant_id, stocktake.warehouse_id
            )
            delta = wanted
            if wanted < 0 and -wanted > balance.on_hand:
                delta = -max(balance.on_hand, 0)
                clamped += 1
            line.applied_delta = delta
            if delta == 0:
                continue
            await MovementServiceMixin.move(
                session,
                tenant_id,
                line.variant_id,
                stocktake.warehouse_id,
                direction="in" if delta > 0 else "out",
                quantity=abs(delta),
                reason="adjustment",
                reference_type="stocktake",
                reference_id=stocktake.id,
                actor_user_id=user_id,
            )
            adjusted += 1

        stocktake.status = "APPROVED"
        stocktake.closed_at = _now()
        stocktake.closed_by_user_id = user_id
        await session.flush()
        return {
            "stocktake_id": str(stocktake.id),
            "counted": len(counted),
            "adjusted": adjusted,
            "clamped": clamped,
            "not_counted": len(lines) - len(counted),
        }

    @staticmethod
    async def _book_qty_at_count(
        session: AsyncSession,
        tenant_id: UUID,
        line: StocktakeLine,
        warehouse_id: UUID,
    ) -> int:
        """The book quantity this line was measured against.

        Stored when the figure was taken (``counted_book_qty``), so approval compares like with
        like whatever happened in between. A line counted before that column existed falls back to
        the count's start snapshot.
        """
        if line.counted_book_qty is not None:
            return int(line.counted_book_qty)
        return line.expected_qty

    @staticmethod
    async def list_recent(session: AsyncSession, tenant_id: UUID, *, limit: int = 20) -> list[dict]:
        """Newest counts first, each with how many lines there are and how many were counted."""
        limit = max(1, min(int(limit), 100))
        rows = (
            await session.execute(
                select(
                    Stocktake,
                    func.count(StocktakeLine.id),
                    func.count(StocktakeLine.counted_qty),
                )
                .outerjoin(StocktakeLine, StocktakeLine.stocktake_id == Stocktake.id)
                .where(Stocktake.tenant_id == tenant_id)
                .group_by(Stocktake.id)
                .order_by(Stocktake.created_at.desc(), Stocktake.id)
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": str(st.id),
                "warehouse_id": str(st.warehouse_id),
                "status": st.status,
                "note": st.note,
                "created_at": st.created_at.isoformat() if st.created_at else None,
                "closed_at": st.closed_at.isoformat() if st.closed_at else None,
                "lines": int(total),
                "counted": int(counted),
            }
            for st, total, counted in rows
        ]

    @staticmethod
    async def detail(
        session: AsyncSession,
        tenant_id: UUID,
        stocktake_id: UUID,
        *,
        for_counter: bool = False,
    ) -> dict:
        """The count with its lines, each next to today's balance so the screen can show drift.

        A blind count hides expected_qty and current_qty when accessed by a counter.
        """
        stocktake = await StocktakeService._get(session, tenant_id, stocktake_id)
        rows = (
            await session.execute(
                select(StocktakeLine, InventoryBalance.on_hand)
                .outerjoin(
                    InventoryBalance,
                    (InventoryBalance.variant_id == StocktakeLine.variant_id)
                    & (InventoryBalance.tenant_id == tenant_id)
                    & (InventoryBalance.warehouse_id == stocktake.warehouse_id),
                )
                .where(
                    StocktakeLine.tenant_id == tenant_id,
                    StocktakeLine.stocktake_id == stocktake_id,
                )
                .order_by(StocktakeLine.variant_id)
            )
        ).all()

        assignments = list(
            (
                await session.execute(
                    select(StocktakeAssignment).where(
                        StocktakeAssignment.tenant_id == tenant_id,
                        StocktakeAssignment.stocktake_id == stocktake_id,
                    )
                )
            ).scalars()
        )

        hide_book = stocktake.blind and for_counter
        threshold = stocktake.recount_threshold_pct or 10

        lines_out = []
        for line, current in rows:
            needs_recount = False
            if line.counted_qty is not None and line.expected_qty > 0:
                variance_pct = abs(line.counted_qty - line.expected_qty) / line.expected_qty * 100
                if variance_pct >= threshold:
                    needs_recount = True

            lines_out.append(
                {
                    "variant_id": str(line.variant_id),
                    "expected_qty": None if hide_book else line.expected_qty,
                    "counted_qty": line.counted_qty,
                    "current_qty": None
                    if hide_book
                    else (int(current) if current is not None else 0),
                    "applied_delta": line.applied_delta,
                    "recount_count": line.recount_count or 0,
                    "needs_recount": needs_recount,
                }
            )

        return {
            "id": str(stocktake.id),
            "warehouse_id": str(stocktake.warehouse_id),
            "status": stocktake.status,
            "kind": stocktake.kind,
            "blind": stocktake.blind,
            "scope": stocktake.scope,
            "recount_threshold_pct": threshold,
            "note": stocktake.note,
            "created_at": stocktake.created_at.isoformat() if stocktake.created_at else None,
            "closed_at": stocktake.closed_at.isoformat() if stocktake.closed_at else None,
            "assignments": [
                {
                    "user_id": str(a.user_id),
                    "location_id": str(a.location_id) if a.location_id else None,
                    "status": a.status,
                    "counted_lines": a.counted_lines,
                }
                for a in assignments
            ],
            "lines": lines_out,
        }

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
from app.modules.inventory.models import InventoryBalance, Stocktake, StocktakeLine

from ._common import _now
from .balances import BalanceServiceMixin
from .movements import MovementServiceMixin

_MAX_COUNT = 1_000_000


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
        user_id: UUID | None = None,
        note: str | None = None,
    ) -> Stocktake:
        """Start a count: one line per active variant, each holding today's book quantity."""
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
        variant_ids = await BalanceServiceMixin._active_variant_ids(session, tenant_id)
        for variant_id in variant_ids:
            session.add(
                StocktakeLine(
                    tenant_id=tenant_id,
                    stocktake_id=stocktake.id,
                    variant_id=variant_id,
                    expected_qty=max(on_hand.get(variant_id, 0), 0),
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
        for line in lines:
            line.counted_qty = wanted[line.variant_id]
        await session.flush()
        return len(lines)

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
        twice: the second sees APPROVED and is refused. For each counted line the difference is
        ``counted - expected`` (the snapshot), moved as ``in`` or ``out`` with reason
        ``adjustment`` on whatever the balance is NOW. If a sale since the snapshot already took
        the stock the count says is missing, the removal is clamped at zero rather than failing
        the whole approval; ``applied_delta`` records what really moved.
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
            wanted = line.counted_qty - line.expected_qty
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
    async def detail(session: AsyncSession, tenant_id: UUID, stocktake_id: UUID) -> dict:
        """The count with its lines, each next to today's balance so the screen can show drift."""
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
        return {
            "id": str(stocktake.id),
            "warehouse_id": str(stocktake.warehouse_id),
            "status": stocktake.status,
            "note": stocktake.note,
            "created_at": stocktake.created_at.isoformat() if stocktake.created_at else None,
            "closed_at": stocktake.closed_at.isoformat() if stocktake.closed_at else None,
            "lines": [
                {
                    "variant_id": str(line.variant_id),
                    "expected_qty": line.expected_qty,
                    "counted_qty": line.counted_qty,
                    "current_qty": int(current) if current is not None else 0,
                    "applied_delta": line.applied_delta,
                }
                for line, current in rows
            ],
        }

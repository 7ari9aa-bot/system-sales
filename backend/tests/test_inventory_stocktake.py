"""Physical stocktake: a count against a book snapshot, approved into the ledger.

What these pin down, because each one is a way a count quietly corrupts stock:
  * the shop keeps selling while it is counted: approval moves (counted - snapshot) RELATIVE to
    today's balance, so a sale made during the count is never erased by an absolute overwrite
  * a line nobody counted is never adjusted (not counted is not zero)
  * approving twice must not move stock twice
  * a removal larger than what is left is clamped at zero and recorded, not a failed approval
  * one open count per warehouse, enforced by the database, not only by the service
"""

from __future__ import annotations

import pytest
from sqlalchemy import case, func, select

from app.core.errors import ValidationError
from app.modules.errors import ConflictError, NotFoundError
from app.modules.inventory.models import InventoryMovement
from app.modules.inventory.service import InventoryService
from app.modules.inventory.services import StocktakeService
from tests.test_inventory_stock_view import _variant

pytestmark = pytest.mark.asyncio


async def _on_hand(db, tenant_ctx, variant, warehouse) -> int:
    balance = await InventoryService.get_balance(db, tenant_ctx.tenant_id, variant.id, warehouse.id)
    return int(balance.on_hand)


async def _line(detail: dict, variant) -> dict:
    return next(row for row in detail["lines"] if row["variant_id"] == str(variant.id))


async def _count(db, tenant_ctx, stocktake, variant, qty):
    return await StocktakeService.record_counts(
        db,
        tenant_ctx.tenant_id,
        stocktake.id,
        [{"variant_id": str(variant.id), "counted_qty": qty}],
    )


async def test_open_snapshots_the_book_quantity(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=12)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    detail = await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id)
    line = await _line(detail, variant)
    assert (line["expected_qty"], line["counted_qty"], line["current_qty"]) == (12, None, 12)
    assert detail["status"] == "OPEN"


async def test_a_shortage_is_removed_and_a_surplus_is_added(db, tenant_ctx):
    _, short, wh = await _variant(db, tenant_ctx, stock=10)
    _, over, _ = await _variant(db, tenant_ctx, stock=4)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, short, 7)  # 3 missing
    await _count(db, tenant_ctx, st, over, 6)  # 2 extra
    result = await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert result["adjusted"] == 2 and result["clamped"] == 0
    assert await _on_hand(db, tenant_ctx, short, wh) == 7
    assert await _on_hand(db, tenant_ctx, over, wh) == 6


async def test_a_sale_made_during_the_count_is_not_erased(db, tenant_ctx):
    """Snapshot 10, a sale takes 2 (balance 8), the shelf is counted at 9: the right answer is 9
    minus the sale's effect, i.e. +1 relative to the snapshot is NOT what happened. The count says
    the shelf held 9 when counted against a book of 10, so one unit was missing: 8 - 1 = 7."""
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, wh.id, direction="out", quantity=2, reason="sale"
    )
    await _count(db, tenant_ctx, st, variant, 9)  # one fewer than the snapshot of 10
    await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert await _on_hand(db, tenant_ctx, variant, wh) == 7  # an absolute overwrite would give 9


async def test_a_line_nobody_counted_is_left_alone(db, tenant_ctx):
    _, counted, wh = await _variant(db, tenant_ctx, stock=5)
    _, skipped, _ = await _variant(db, tenant_ctx, stock=9)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, counted, 4)
    result = await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert await _on_hand(db, tenant_ctx, skipped, wh) == 9  # not zeroed
    assert result["not_counted"] >= 1


async def test_a_counted_zero_is_a_real_zero(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=6)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 0)
    await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert await _on_hand(db, tenant_ctx, variant, wh) == 0


async def test_approving_twice_moves_stock_once(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 8)
    await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    with pytest.raises(ConflictError):
        await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert await _on_hand(db, tenant_ctx, variant, wh) == 8


async def test_a_removal_larger_than_what_is_left_is_clamped_and_recorded(db, tenant_ctx):
    """Snapshot 5, sales take 4 (1 left), the count says 0 (5 missing): only 1 can still go."""
    _, variant, wh = await _variant(db, tenant_ctx, stock=5)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, wh.id, direction="out", quantity=4, reason="sale"
    )
    await _count(db, tenant_ctx, st, variant, 0)
    result = await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert result["clamped"] == 1
    assert await _on_hand(db, tenant_ctx, variant, wh) == 0  # never negative
    line = await _line(await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id), variant)
    assert line["applied_delta"] == -1  # what really moved, not the -5 the count wanted


async def test_every_adjustment_is_a_ledger_row_pointing_at_the_stocktake(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 6)
    await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    rows = (
        (
            await db.execute(
                select(InventoryMovement).where(
                    InventoryMovement.tenant_id == tenant_ctx.tenant_id,
                    InventoryMovement.reference_id == st.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert (rows[0].direction, rows[0].quantity, rows[0].reason) == ("out", 4, "adjustment")
    assert rows[0].reference_type == "stocktake" and rows[0].balance_after == 6


async def test_cancel_moves_nothing_and_frees_the_warehouse(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 1)
    await StocktakeService.cancel(db, tenant_ctx.tenant_id, st.id)
    assert await _on_hand(db, tenant_ctx, variant, wh) == 10
    with pytest.raises(ConflictError):
        await _count(db, tenant_ctx, st, variant, 2)  # a closed count takes no figures
    again = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    assert again.id != st.id


async def test_one_open_count_per_warehouse(db, tenant_ctx):
    _, _, wh = await _variant(db, tenant_ctx, stock=1)
    await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    with pytest.raises(ConflictError):
        await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)


async def test_nothing_counted_cannot_be_approved(db, tenant_ctx):
    _, _, wh = await _variant(db, tenant_ctx, stock=3)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    with pytest.raises(ValidationError):
        await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)


@pytest.mark.parametrize("bad", [-1, 1_000_001, 2.5, "3", True])
async def test_a_count_must_be_a_whole_non_negative_number(db, tenant_ctx, bad):
    _, variant, wh = await _variant(db, tenant_ctx, stock=3)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    with pytest.raises(ValidationError):
        await _count(db, tenant_ctx, st, variant, bad)


async def test_a_bad_entry_rejects_the_whole_sheet(db, tenant_ctx):
    _, good, wh = await _variant(db, tenant_ctx, stock=3)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    with pytest.raises(ValidationError):
        await StocktakeService.record_counts(
            db,
            tenant_ctx.tenant_id,
            st.id,
            [
                {"variant_id": str(good.id), "counted_qty": 2},
                {"variant_id": "00000000-0000-0000-0000-000000000000", "counted_qty": 1},
            ],
        )
    line = await _line(await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id), good)
    assert line["counted_qty"] is None  # the valid entry was not half-saved


async def test_none_uncounts_a_line(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=3)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 2)
    await _count(db, tenant_ctx, st, variant, None)
    line = await _line(await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id), variant)
    assert line["counted_qty"] is None


async def test_unknown_stocktake_is_not_found(db, tenant_ctx):
    import uuid

    with pytest.raises(NotFoundError):
        await StocktakeService.detail(db, tenant_ctx.tenant_id, uuid.uuid4())


async def test_the_ledger_total_matches_the_balance_after_a_count(db, tenant_ctx):
    """Replaying the ledger must still equal the balance: the stocktake writes through move()."""
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 13)
    await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    net = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (InventoryMovement.direction == "in", InventoryMovement.quantity),
                            else_=-InventoryMovement.quantity,
                        )
                    ),
                    0,
                )
            ).where(
                InventoryMovement.tenant_id == tenant_ctx.tenant_id,
                InventoryMovement.variant_id == variant.id,
                InventoryMovement.direction.in_(("in", "out")),
            )
        )
    ).scalar()
    assert int(net) == await _on_hand(db, tenant_ctx, variant, wh) == 13

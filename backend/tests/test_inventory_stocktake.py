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


async def test_a_sale_made_before_the_count_is_not_subtracted_twice(db, tenant_ctx):
    """§4.1: the shop keeps selling while the sheet is filled.

    Book 10 at the start, a dress is sold (book 8), the counter then counts the shelf at 9. The
    count is TRUE at the moment it was taken, so the book becomes 9. Comparing against the START
    snapshot of 10 made the difference -1 and landed on 7: the dress left once and was written off
    as missing as well.
    """
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, wh.id, direction="out", quantity=2, reason="sale"
    )
    await _count(db, tenant_ctx, st, variant, 9)
    await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert await _on_hand(db, tenant_ctx, variant, wh) == 9


async def test_a_sale_made_after_the_count_moves_nothing_at_approval(db, tenant_ctx):
    """The count was right when it was taken; a later sale already moved the book itself."""
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 10)
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, wh.id, direction="out", quantity=2, reason="sale"
    )
    result = await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert result["adjusted"] == 0
    assert await _on_hand(db, tenant_ctx, variant, wh) == 8
    line = await _line(await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id), variant)
    assert line["applied_delta"] == 0


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
    """A count of 0 when the book says 5, and a sale of the last 5 lands before approval: the
    adjustment cannot go below zero, and the line records what really moved."""
    _, variant, wh = await _variant(db, tenant_ctx, stock=5)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 0)
    # Everything still on the shelf sells between the count and the approval.
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, wh.id, direction="out", quantity=5, reason="sale"
    )
    result = await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id)
    assert result["clamped"] == 1
    assert await _on_hand(db, tenant_ctx, variant, wh) == 0  # never negative
    line = await _line(await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id), variant)
    assert line["applied_delta"] == 0  # what really moved, not the -5 the count wanted


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


async def test_the_count_keeps_the_book_it_was_measured_against(db, tenant_ctx):
    """A sale between the snapshot and the count must not become a difference nobody applied.

    The screen used to diff against the count's START snapshot while approval compared against the
    book at COUNT time, so the sheet showed a shortage the server never applied. Both figures now
    travel, and the recount flag is computed on the same basis.
    """
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)

    # The shop sells 2 while the count is open: the snapshot says 10, the shelf now holds 8.
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        wh.id,
        direction="out",
        quantity=2,
        reason="sale",
    )

    await _count(db, tenant_ctx, st, variant, 8)
    line = await _line(await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id), variant)

    assert line["expected_qty"] == 10  # the opening snapshot
    assert line["counted_book_qty"] == 8  # what the counter actually saw
    assert line["counted_at"] is not None
    assert line["needs_recount"] is False  # 8 vs 8 is no variance, whatever the snapshot says


async def test_the_recount_flag_uses_the_counted_book(db, tenant_ctx):
    """A real shortage still flags a recount, against the counted book, not the snapshot."""
    _, variant, wh = await _variant(db, tenant_ctx, stock=20)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        wh.id,
        direction="out",
        quantity=10,
        reason="sale",
    )
    # Counted 4 against a book of 10 at that moment: a 60% shortage, well past the 10% threshold.
    await _count(db, tenant_ctx, st, variant, 4)
    line = await _line(await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id), variant)
    assert line["counted_book_qty"] == 10
    assert line["needs_recount"] is True


async def test_uncounting_clears_the_time_and_the_book(db, tenant_ctx):
    """A cleared box is not a count: neither the moment nor the basis survives it."""
    _, variant, wh = await _variant(db, tenant_ctx, stock=5)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await _count(db, tenant_ctx, st, variant, 5)
    await _count(db, tenant_ctx, st, variant, None)
    line = await _line(await StocktakeService.detail(db, tenant_ctx.tenant_id, st.id), variant)
    assert line["counted_qty"] is None
    assert line["counted_at"] is None
    assert line["counted_book_qty"] is None

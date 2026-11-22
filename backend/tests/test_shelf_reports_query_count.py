"""The two shelf reports must answer in a fixed number of questions, however big the shelf is.

Sell-through and dead stock are the screens an owner opens on a shop with thousands of variants,
so the thing that must never creep back is a query inside the row loop: the report would then take
one round trip per size and get slower every season the shop grows.

Measured on 3000 variants (1500 of them sold) against local Postgres after ANALYZE: sell-through
2 statements in 0.135 s, dead stock 1 statement in 0.054 s. A fresh database without planner
statistics made the same query look slow (2.9 s for 1500), which is the measuring environment, not
the query, so nothing was changed in the code: these tests pin the SHAPE (statement count does not
grow with the number of variants) and the row count, not a wall-clock number a busy machine would
make flaky.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import event

from app.core.dead_stock_report import DeadStockReportService
from app.core.sell_through_report import SellThroughReportService
from app.modules.inventory.service import InventoryService
from tests.test_profit_report import DAY, NOW, _sale, _variant, _wh

pytestmark = pytest.mark.asyncio


@contextmanager
def _statements(db) -> Iterator[list[str]]:
    """Every statement the session sends while the block runs. Removed in a finally, always."""
    seen: list[str] = []

    def spy(_conn, _cursor, statement, *_a):
        seen.append(statement)

    bind = db.get_bind()
    engine = getattr(bind, "sync_engine", bind)
    event.listen(engine, "before_cursor_execute", spy)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", spy)


async def _shelved_variant(db, tid, wh, *, title, sold_days_ago=0):
    """One variant with ten on the shelf and, unless ``sold_days_ago`` is None, a sale of two."""
    _prod, variant = await _variant(db, tid, title=title)
    await InventoryService.move(
        db, tid, variant.id, wh.id, direction="in", quantity=10, reason="purchase"
    )
    if sold_days_ago is not None:
        await _sale(
            db,
            type("C", (), {"tenant_id": tid})(),
            wh,
            variant,
            qty=2,
            net="200",
            cost="80",
            when=NOW - timedelta(days=sold_days_ago),
        )
    return variant


async def _sell_through_statements(db, tid):
    with _statements(db) as seen:
        report = await SellThroughReportService.by_variant(
            db, tid, start=DAY - timedelta(days=200), end=DAY + timedelta(days=1)
        )
    return report, [s for s in seen if s.lstrip().upper().startswith(("SELECT", "WITH"))]


async def _dead_stock_statements(db, tid):
    with _statements(db) as seen:
        report = await DeadStockReportService.report(db, tid, days=30)
    return report, [s for s in seen if s.lstrip().upper().startswith(("SELECT", "WITH"))]


async def test_sell_through_asks_the_same_two_questions_for_one_variant_and_for_a_dozen(
    db, tenant_ctx
):
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)

    await _shelved_variant(db, tid, wh, title="موديل وحيد")
    small, small_queries = await _sell_through_statements(db, tid)

    for i in range(11):
        await _shelved_variant(db, tid, wh, title=f"موديل{i}")
    large, large_queries = await _sell_through_statements(db, tid)

    assert len(small["rows"]) == 1
    assert len(large["rows"]) == 12
    assert len(large_queries) == len(small_queries), (
        f"sell-through asked {len(small_queries)} questions for 1 variant and "
        f"{len(large_queries)} for 12: a query crept into the row loop"
    )
    assert len(large_queries) == 2, (
        f"expected the profit query and the shelf query, got {len(large_queries)}"
    )


async def test_dead_stock_asks_the_same_one_question_for_one_variant_and_for_a_dozen(
    db, tenant_ctx
):
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)

    await _shelved_variant(db, tid, wh, title="راكد وحيد", sold_days_ago=100)
    small, small_queries = await _dead_stock_statements(db, tid)

    for i in range(11):
        await _shelved_variant(db, tid, wh, title=f"راكد{i}", sold_days_ago=100)
    large, large_queries = await _dead_stock_statements(db, tid)

    assert len(small["rows"]) == 1
    assert len(large["rows"]) == 12
    assert len(large_queries) == len(small_queries), (
        f"dead stock asked {len(small_queries)} questions for 1 variant and "
        f"{len(large_queries)} for 12: a query crept into the row loop"
    )
    assert len(large_queries) == 1, f"expected one grouped query, got {len(large_queries)}"


async def test_sell_through_never_sends_a_query_per_row(db, tenant_ctx):
    """The statement count is flat: 24 variants must not cost more than 12."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    for i in range(24):
        await _shelved_variant(db, tid, wh, title=f"قطعة{i}")

    report, queries = await _sell_through_statements(db, tid)

    assert len(report["rows"]) == 24
    assert len(queries) <= 2, f"{len(queries)} statements for 24 variants: one per row?"

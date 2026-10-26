"""The day log can be paged past its first page.

``GET /pos/sessions`` capped at 500 rows with no way to ask for older ones, so a register with a
longer history lost its oldest days for good. ``offset`` walks the whole history newest-first; the
default (0) keeps the existing response unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.pos.models import PosSession
from app.modules.pos.service import PosService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def _register_with_days(db, tenant_ctx, days: int):
    shift, _v, _c = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    base = datetime.now(UTC) - timedelta(days=days + 5)
    ids = []
    for i in range(days):
        row = PosSession(
            tenant_id=tenant_ctx.tenant_id,
            register_id=shift.register_id,
            status="CLOSED",
            opening_float=0,
            opened_at=base + timedelta(days=i),
            closed_at=base + timedelta(days=i, hours=8),
        )
        db.add(row)
        await db.flush()
        ids.append(row.id)
    return shift.register_id, ids


async def test_offset_walks_the_whole_history_newest_first(db, tenant_ctx) -> None:
    register_id, ids = await _register_with_days(db, tenant_ctx, 7)
    tid = tenant_ctx.tenant_id
    page1 = await PosService.list_sessions(db, tid, register_id=register_id, limit=3, offset=0)
    page2 = await PosService.list_sessions(db, tid, register_id=register_id, limit=3, offset=3)
    page3 = await PosService.list_sessions(db, tid, register_id=register_id, limit=3, offset=6)
    seen = [s.id for s in page1 + page2 + page3]
    assert len(seen) == len(set(seen))  # no row twice across pages
    assert set(ids) <= set(seen)  # every seeded day is reachable
    mine = [i for i in seen if i in set(ids)]
    assert mine == list(reversed(ids))  # newest first


async def test_without_an_offset_the_first_page_is_unchanged(db, tenant_ctx) -> None:
    register_id, ids = await _register_with_days(db, tenant_ctx, 4)
    rows = await PosService.list_sessions(db, tenant_ctx.tenant_id, register_id=register_id)
    assert [r.id for r in rows if r.id in set(ids)] == list(reversed(ids))

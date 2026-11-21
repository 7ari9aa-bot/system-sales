"""A receipt number is a fiscal sequence: consecutive, no gaps, per tenant and year."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.core.errors import InsufficientStockError
from app.modules.pos.models import PosReceipt
from tests._pos_helpers import sell, start_day, till

pytestmark = pytest.mark.asyncio


async def _ready(db, tenant_ctx):
    shift, variant, customer = await till(db, tenant_ctx)
    await start_day(db, tenant_ctx, shift.register_id)
    return shift, variant, customer


async def _one(db, tenant_ctx, shift, variant, customer, qty=1):
    return await sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        customer_id=customer.id,
    )


async def _seqs(db) -> list[int]:
    rows = (await db.execute(select(PosReceipt.number))).scalars().all()
    out = []
    for number in rows:
        match = re.fullmatch(r"POS-\d{4}-(\d{4,})", number)
        assert match, f"receipt number {number!r} is not POS-<year>-<sequence>"
        out.append(int(match.group(1)))
    return sorted(out)


async def test_receipts_are_numbered_one_after_another(db, tenant_ctx) -> None:
    shift, variant, customer = await _ready(db, tenant_ctx)
    for _ in range(3):
        await _one(db, tenant_ctx, shift, variant, customer)
    assert await _seqs(db) == [1, 2, 3]


async def test_a_refused_sale_gives_its_number_back(db, tenant_ctx) -> None:
    shift, variant, customer = await _ready(db, tenant_ctx)
    await _one(db, tenant_ctx, shift, variant, customer)
    with pytest.raises(InsufficientStockError):
        async with db.begin_nested():
            await _one(db, tenant_ctx, shift, variant, customer, qty=9999)
    await _one(db, tenant_ctx, shift, variant, customer)
    assert await _seqs(db) == [1, 2]

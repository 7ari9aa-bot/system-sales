"""Real concurrency for the stocktake: separate committed connections racing for one count.

The per-test `db` fixture is one rolled-back connection, so it cannot show a race. The throw-away
tenant is committed, raced, then removed through the owner connection (behind a name guard).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa

from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError
from app.modules.inventory.service import InventoryService
from app.modules.inventory.services import StocktakeService
from tests import test_purchasing_concurrency as pc
from tests.test_purchasing_concurrency import (  # noqa: F401  (fixtures are used by name)
    _in_tx,
    admin_url,
    committed_tenant,
)

pytestmark = pytest.mark.asyncio

RACERS = 8
# stocktakes first: its lines point at product_variants, which the purge deletes next.
pc._TENANT_TABLES = ("stocktake_lines", "stocktakes", *pc._TENANT_TABLES)


async def _setup(factory, tenant_id, stock=10):
    async def go(s):
        product = await CatalogService.create_product(
            s, tenant_id, title="جرد", slug=f"s-{uuid.uuid4().hex[:8]}"
        )
        variant = await CatalogService.add_variant(s, tenant_id, product.id, price="100.00")
        wh = await InventoryService.get_default_warehouse(s, tenant_id)
        await InventoryService.move(
            s, tenant_id, variant.id, wh.id, direction="in", quantity=stock, reason="purchase"
        )
        return variant.id, wh.id

    return await _in_tx(factory, tenant_id, go)


async def _on_hand(factory, tenant_id, variant_id) -> int:
    async def read(s):
        return await InventoryService.total_on_hand(s, tenant_id, variant_id)

    return await _in_tx(factory, tenant_id, read)


async def test_parallel_approvals_apply_the_count_once(committed_tenant) -> None:  # noqa: F811
    factory, tenant_id = committed_tenant
    variant_id, wh_id = await _setup(factory, tenant_id, stock=10)

    async def prepare(s):
        st = await StocktakeService.open(s, tenant_id, wh_id)
        await StocktakeService.record_counts(
            s, tenant_id, st.id, [{"variant_id": str(variant_id), "counted_qty": 6}]
        )
        return st.id

    stocktake_id = await _in_tx(factory, tenant_id, prepare)
    results = await asyncio.gather(
        *[
            _in_tx(
                factory, tenant_id, lambda s: StocktakeService.approve(s, tenant_id, stocktake_id)
            )
            for _ in range(RACERS)
        ]
    )
    assert len([r for r in results if isinstance(r, dict)]) == 1
    assert len([r for r in results if isinstance(r, ConflictError)]) == RACERS - 1
    assert await _on_hand(factory, tenant_id, variant_id) == 6  # one adjustment of -4, never -32


async def test_parallel_opens_leave_exactly_one_open_count(committed_tenant) -> None:  # noqa: F811
    factory, tenant_id = committed_tenant
    _, wh_id = await _setup(factory, tenant_id)
    results = await asyncio.gather(
        *[
            _in_tx(factory, tenant_id, lambda s: StocktakeService.open(s, tenant_id, wh_id))
            for _ in range(RACERS)
        ]
    )
    assert len([r for r in results if not isinstance(r, Exception)]) == 1
    assert len([r for r in results if isinstance(r, ConflictError)]) == RACERS - 1

    async def open_rows(s):
        return (
            await s.execute(sa.text("SELECT count(*) FROM stocktakes WHERE status = 'OPEN'"))
        ).scalar_one()

    assert await _in_tx(factory, tenant_id, open_rows) == 1


async def test_a_sale_racing_the_approval_is_never_lost(committed_tenant) -> None:  # noqa: F811
    """Approve (-4) while sales take 3 more: 10 - 3 - 4 = 3, whichever order the locks pick."""
    factory, tenant_id = committed_tenant
    variant_id, wh_id = await _setup(factory, tenant_id, stock=10)

    async def prepare(s):
        st = await StocktakeService.open(s, tenant_id, wh_id)
        await StocktakeService.record_counts(
            s, tenant_id, st.id, [{"variant_id": str(variant_id), "counted_qty": 6}]
        )
        return st.id

    stocktake_id = await _in_tx(factory, tenant_id, prepare)

    async def sell(s):
        await InventoryService.move(
            s, tenant_id, variant_id, wh_id, direction="out", quantity=1, reason="sale"
        )

    results = await asyncio.gather(
        _in_tx(factory, tenant_id, lambda s: StocktakeService.approve(s, tenant_id, stocktake_id)),
        *[_in_tx(factory, tenant_id, sell) for _ in range(3)],
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    assert await _on_hand(factory, tenant_id, variant_id) == 3

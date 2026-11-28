"""What a spreadsheet row carries besides the name: category, brand, cost and status.

A merchant's file says "بناطيل" and "نايك", not uuids, and it usually has no status column at all.
Three things used to be dropped on the floor: the category and the brand were parsed and never
written, and a product with a blank status stayed a draft, so an import that looked successful
produced a catalog nobody could sell. The cost column had no home either: cost lives in FIFO layers
here, so it now travels with the opening stock the same file declares.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.platform.imports import apply as apply_mod
from app.platform.imports.apply import apply_batch
from app.platform.imports.fields import SHEET_PRODUCTS, SHEET_STOCK, SHEET_VARIANTS
from app.platform.imports.models import ImportRow, ImportSession
from app.platform.imports.verdicts import encode_values, values_of
from app.applications.apparel.modules.inventory.models import Warehouse
from app.workers.import_runner import PORTS

pytestmark = pytest.mark.asyncio


async def _session(db, tenant_id) -> ImportSession:
    s = ImportSession(tenant_id=tenant_id, kind="products", file_name="f.xlsx", status="validated")
    db.add(s)
    await db.flush()
    return s


def _row(s, sheet, number, values, action="create") -> ImportRow:
    return ImportRow(
        tenant_id=s.tenant_id,
        session_id=s.id,
        sheet=sheet,
        row_number=number,
        raw={},
        status="valid",
        parsed={"action": action, "values": encode_values(values)},
    )


async def _apply(db, tenant_id, s):
    """Apply until the session is empty: the worker walks one sheet at a time."""
    result = await apply_batch(
        db, tenant_id, s.id, PORTS, values_of=values_of, limit=10 * apply_mod.BATCH_LIMIT
    )
    total = result
    while result.taken:
        result = await apply_batch(
            db, tenant_id, s.id, PORTS, values_of=values_of, limit=10 * apply_mod.BATCH_LIMIT
        )
        total.applied += result.applied
        total.failed += result.failed
        total.skipped += result.skipped
    return total


async def _product(db, tenant_id, slug):
    row = (
        await db.execute(
            sa.text(
                "select id, status, category_id, brand_id from products "
                "where tenant_id = :t and slug = :s"
            ),
            {"t": tenant_id, "s": slug},
        )
    ).one()
    return row


async def _named(db, table, tenant_id, name):
    return (
        await db.execute(
            sa.text(f"select id, name from {table} where tenant_id = :t"), {"t": tenant_id}
        )
    ).all()


async def test_the_files_category_and_brand_become_the_shops_own(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _session(db, t)
    db.add_all(
        [
            _row(
                s,
                SHEET_PRODUCTS,
                1,
                {
                    "product_ref": "jeans-1",
                    "title": "بنطلون",
                    "category": "بناطيل",
                    "brand": "نايك",
                },
            ),
            _row(
                s,
                SHEET_PRODUCTS,
                2,
                {
                    "product_ref": "jeans-2",
                    "title": "بنطلون تاني",
                    "category": " بناطيل ",
                    "brand": "نايك",
                },
            ),
        ]
    )
    await db.flush()

    result = await _apply(db, t, s)
    assert (result.applied, result.failed) == (2, 0)

    first = await _product(db, t, "jeans-1")
    second = await _product(db, t, "jeans-2")
    assert first.category_id is not None and first.brand_id is not None
    # A name written twice (with a stray space) is one category, not two.
    assert first.category_id == second.category_id
    assert first.brand_id == second.brand_id
    assert [r.name for r in await _named(db, "categories", t, "بناطيل")] == ["بناطيل"]
    assert [r.name for r in await _named(db, "brands", t, "نايك")] == ["نايك"]


async def test_an_existing_category_is_reused_not_forked(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    from app.applications.apparel.modules.catalog.service import CatalogService

    existing = await CatalogService.create_category(db, t, name="بناطيل")
    await db.flush()
    s = await _session(db, t)
    db.add(
        _row(s, SHEET_PRODUCTS, 1, {"product_ref": "p-1", "title": "بنطلون", "category": "بناطيل"})
    )
    await db.flush()

    assert (await _apply(db, t, s)).applied == 1
    rows = [r for r in await _named(db, "categories", t, "بناطيل") if r.name == "بناطيل"]
    assert len(rows) == 1
    assert (await _product(db, t, "p-1")).category_id == existing.id


async def test_a_blank_status_means_sell_it_not_draft_it(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _session(db, t)
    db.add(_row(s, SHEET_PRODUCTS, 1, {"product_ref": "tee-1", "title": "تيشيرت"}))
    await db.flush()

    assert (await _apply(db, t, s)).applied == 1
    assert (await _product(db, t, "tee-1")).status == "active"


async def test_a_stated_status_is_kept_and_a_blank_one_never_resurrects_it(db, tenant_ctx):
    """Re-importing a price list must not un-archive what the shop archived on purpose."""
    t = tenant_ctx.tenant_id
    s = await _session(db, t)
    db.add(
        _row(
            s,
            SHEET_PRODUCTS,
            1,
            {"product_ref": "old-1", "title": "قديم", "status": "archived"},
        )
    )
    await db.flush()
    assert (await _apply(db, t, s)).applied == 1
    assert (await _product(db, t, "old-1")).status == "archived"

    again = await _session(db, t)
    db.add(
        _row(
            again,
            SHEET_PRODUCTS,
            1,
            {"product_ref": "old-1", "title": "قديم", "status": ""},
            action="update",
        )
    )
    await db.flush()
    assert (await _apply(db, t, again)).applied == 1
    assert (await _product(db, t, "old-1")).status == "archived"


async def test_the_cost_column_lands_in_the_layer_the_stock_creates(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = Warehouse(tenant_id=t, name="الدرج", code="DRAWER")
    db.add(wh)
    await db.flush()

    s = await _session(db, t)
    db.add_all(
        [
            _row(
                s,
                SHEET_VARIANTS,
                1,
                {
                    "product_ref": "coat-1",
                    "sku": "SKU-COAT-1",
                    "price": Decimal("900.00"),
                    "cost": Decimal("540.00"),
                },
            ),
            _row(
                s,
                SHEET_STOCK,
                2,
                {"sku": "SKU-COAT-1", "warehouse": "DRAWER", "quantity": Decimal("6")},
            ),
        ]
    )
    await db.flush()
    # the variants row needs its product first: apply creates it from the same file order
    db.add(_row(s, SHEET_PRODUCTS, 3, {"product_ref": "coat-1", "title": "بالطو"}))
    await db.flush()

    result = await _apply(db, t, s)
    assert result.failed == 0, result

    layer = (
        await db.execute(
            sa.text(
                "select unit_cost, remaining_quantity from inventory_cost_layers "
                "where tenant_id = :t order by created_at desc limit 1"
            ),
            {"t": t},
        )
    ).one_or_none()
    assert layer is not None
    assert layer.unit_cost == Decimal("540.0000")
    assert layer.remaining_quantity == 6

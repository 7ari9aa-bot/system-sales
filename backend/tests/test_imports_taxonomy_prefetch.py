"""The shop's categories and brands are read once per run, not once per row.

A 10,000-row file used to ask the database for the whole category list and the whole brand list
for every row it applied, and those lists are capped at 200 rows. So a big import was quadratic in
round trips, and a shop that owns more than 200 categories could not match one of its own names:
the import created a duplicate of a category it already had. The maps are now built once for the
run (paged past the cap) and reused for every row, and a name created mid-run joins the map.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.applications.apparel.modules.catalog.models import Category
from app.applications.apparel.modules.catalog.service import CatalogService
from app.platform.imports import apply as apply_mod
from app.platform.imports.apply import apply_batch
from app.platform.imports.fields import SHEET_PRODUCTS
from app.platform.imports.models import ImportRow, ImportSession
from app.platform.imports.verdicts import encode_values, values_of
from app.workers import import_runner
from app.workers.import_runner import PORTS

pytestmark = pytest.mark.asyncio


async def _session(db, tenant_id) -> ImportSession:
    s = ImportSession(tenant_id=tenant_id, kind="products", file_name="f.xlsx", status="validated")
    db.add(s)
    await db.flush()
    return s


def _row(s, number, values, sheet=SHEET_PRODUCTS, action="create") -> ImportRow:
    return ImportRow(
        tenant_id=s.tenant_id,
        session_id=s.id,
        sheet=sheet,
        row_number=number,
        raw={},
        status="valid",
        parsed={"action": action, "values": encode_values(values)},
    )


async def _apply_with_prefetch(db, tenant_id, s):
    """Apply the session the way the worker does: one taxonomy read, then the rows."""
    token = import_runner._TAXONOMY_MAPS.set(await import_runner._load_taxonomy(db, tenant_id))
    try:
        total = await apply_batch(
            db, tenant_id, s.id, PORTS, values_of=values_of, limit=10 * apply_mod.BATCH_LIMIT
        )
        while total.taken and total.remaining:
            more = await apply_batch(
                db, tenant_id, s.id, PORTS, values_of=values_of, limit=10 * apply_mod.BATCH_LIMIT
            )
            total.applied += more.applied
            total.failed += more.failed
            total.skipped += more.skipped
            total.taken = more.taken
        return total
    finally:
        import_runner._TAXONOMY_MAPS.reset(token)


async def _count(db, table: str, tenant_id) -> int:
    return int(
        (
            await db.execute(
                sa.text(f"select count(*) from {table} where tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar_one()
    )


async def test_a_batch_reads_the_taxonomy_once_not_once_per_row(db, tenant_ctx, monkeypatch):
    """Five rows, one list query for categories and one for brands, not ten."""
    t = tenant_ctx.tenant_id
    db.add(Category(tenant_id=t, name="بناطيل"))
    await db.flush()
    s = await _session(db, t)
    for number in range(1, 6):
        db.add(
            _row(
                s,
                number,
                {
                    "product_ref": f"jeans-{number}",
                    "title": f"بنطلون {number}",
                    "category": "بناطيل",
                    "brand": "نايك",
                },
            )
        )
    await db.flush()

    calls = {"category": 0, "brand": 0}
    real_categories = CatalogService.list_categories
    real_brands = CatalogService.list_brands

    async def counted_categories(session, tenant, **kwargs):
        calls["category"] += 1
        return await real_categories(session, tenant, **kwargs)

    async def counted_brands(session, tenant, **kwargs):
        calls["brand"] += 1
        return await real_brands(session, tenant, **kwargs)

    monkeypatch.setattr(CatalogService, "list_categories", counted_categories)
    monkeypatch.setattr(CatalogService, "list_brands", counted_brands)

    result = await _apply_with_prefetch(db, t, s)

    assert result.applied == 5, result.as_dict()
    assert calls == {"category": 1, "brand": 1}, calls
    assert await _count(db, "brands", t) == 1


async def test_a_category_past_the_two_hundred_cap_is_matched_not_duplicated(db, tenant_ctx):
    """A shop with 251 categories keeps 251: the import finds its own name however it sorts."""
    t = tenant_ctx.tenant_id
    wanted = "zzz مقاس كبير"
    for index in range(250):
        db.add(Category(tenant_id=t, name=f"تصنيف {index:03d}"))
    held = Category(tenant_id=t, name=wanted)
    db.add(held)
    await db.flush()

    s = await _session(db, t)
    db.add(_row(s, 1, {"product_ref": "tee-1", "title": "تيشيرت", "category": wanted}))
    await db.flush()

    result = await _apply_with_prefetch(db, t, s)

    assert result.applied == 1, result.as_dict()
    assert await _count(db, "categories", t) == 251
    attached = (
        await db.execute(
            sa.text("select category_id from products where tenant_id = :t and title = 'تيشيرت'"),
            {"t": t},
        )
    ).scalar_one()
    assert attached == held.id


async def test_a_name_created_mid_run_is_reused_by_the_next_row(db, tenant_ctx):
    """Two rows naming the same new shelf create it once, because it joins the map."""
    t = tenant_ctx.tenant_id
    s = await _session(db, t)
    db.add(_row(s, 1, {"product_ref": "tee-1", "title": "تيشيرت", "category": "جديد"}))
    db.add(_row(s, 2, {"product_ref": "jeans-1", "title": "بنطلون", "category": "جديد"}))
    await db.flush()

    result = await _apply_with_prefetch(db, t, s)

    assert result.applied == 2, result.as_dict()
    assert await _count(db, "categories", t) == 1

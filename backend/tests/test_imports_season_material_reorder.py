"""The import carries the same fields the add-product screen does.

The spreadsheet template had no season, no fabric and no alert level, so a merchant who imported
a thousand products had to open every one of them afterwards to say "SS26", "cotton" and "alert me
at five". Both are plain columns now, on the same sheets the rest of the file already uses.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.modules.imports import apply as apply_mod
from app.modules.imports.apply import apply_batch
from app.modules.imports.fields import (
    PRODUCT_FIELDS,
    SHEET_PRODUCTS,
    SHEET_VARIANTS,
    VARIANT_FIELDS,
)
from app.modules.imports.models import ImportRow, ImportSession
from app.modules.imports.normalize import CellError, parse_reorder_level
from app.modules.imports.verdicts import encode_values, values_of
from app.modules.inventory.stock_view import StockLevelService
from app.workers.import_runner import PORTS

pytestmark = pytest.mark.asyncio


async def _session(db, tenant_id) -> ImportSession:
    s = ImportSession(tenant_id=tenant_id, kind="products", file_name="f.xlsx", status="validated")
    db.add(s)
    await db.flush()
    return s


def _row(s, sheet, number, values) -> ImportRow:
    return ImportRow(
        tenant_id=s.tenant_id,
        session_id=s.id,
        sheet=sheet,
        row_number=number,
        raw={},
        status="valid",
        parsed={"action": "create", "values": encode_values(values)},
    )


async def _apply(db, tenant_id, s):
    total = await apply_batch(
        db, tenant_id, s.id, PORTS, values_of=values_of, limit=10 * apply_mod.BATCH_LIMIT
    )
    while total.taken and total.remaining:
        more = await apply_batch(
            db, tenant_id, s.id, PORTS, values_of=values_of, limit=10 * apply_mod.BATCH_LIMIT
        )
        total.applied += more.applied
        total.failed += more.failed
        total.taken = more.taken
    return total


async def test_the_template_offers_the_columns_the_screen_offers():
    product_keys = {f.key for f in PRODUCT_FIELDS}
    variant_keys = {f.key for f in VARIANT_FIELDS}
    assert {"season", "material"} <= product_keys
    assert "reorder_level" in variant_keys


async def test_a_blank_alert_level_means_no_alert_and_a_bad_one_is_refused():
    assert parse_reorder_level("") is None
    assert parse_reorder_level("  ") is None
    assert parse_reorder_level("7") == 7
    assert parse_reorder_level("0") == 0
    with pytest.raises(CellError):
        parse_reorder_level("-2")
    with pytest.raises(CellError):
        parse_reorder_level("2.5")


async def test_a_row_with_season_fabric_and_alert_level_lands_all_three(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _session(db, t)
    db.add(
        _row(
            s,
            SHEET_PRODUCTS,
            1,
            {
                "product_ref": "tee-1",
                "title": "تيشيرت قطن",
                "season": "SS26",
                "material": "قطن",
            },
        )
    )
    db.add(
        _row(
            s,
            SHEET_VARIANTS,
            1,
            {
                "product_ref": "tee-1",
                "sku": "TEE-BK-L",
                "price": "250.00",
                "color": "أسود",
                "size": "L",
                "reorder_level": "5",
            },
        )
    )
    await db.flush()

    result = await _apply(db, t, s)
    assert (result.applied, result.failed) == (2, 0), result.as_dict()

    product = (
        await db.execute(
            sa.text(
                "select id, season, material from products where tenant_id = :t and slug = 'tee-1'"
            ),
            {"t": t},
        )
    ).one()
    assert (product.season, product.material) == ("SS26", "قطن")

    variant_id = (
        await db.execute(
            sa.text("select id from product_variants where tenant_id = :t and sku = 'TEE-BK-L'"),
            {"t": t},
        )
    ).scalar_one()
    assert await StockLevelService.get_reorder_level(db, t, variant_id) == 5


async def test_a_variant_without_the_column_keeps_no_alert(db, tenant_ctx):
    """A file that says nothing about alerts must not silently invent one."""
    t = tenant_ctx.tenant_id
    s = await _session(db, t)
    db.add(_row(s, SHEET_PRODUCTS, 1, {"product_ref": "tee-2", "title": "تيشيرت تاني"}))
    db.add(
        _row(
            s,
            SHEET_VARIANTS,
            1,
            {"product_ref": "tee-2", "sku": "TEE-2-M", "price": "200.00", "size": "M"},
        )
    )
    await db.flush()

    result = await _apply(db, t, s)
    assert (result.applied, result.failed) == (2, 0), result.as_dict()

    variant_id = (
        await db.execute(
            sa.text("select id from product_variants where tenant_id = :t and sku = 'TEE-2-M'"),
            {"t": t},
        )
    ).scalar_one()
    assert await StockLevelService.get_reorder_level(db, t, variant_id) == 0

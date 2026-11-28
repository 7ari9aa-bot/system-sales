"""دفعة الاستيراد بتجيب منتجاتها وأكوادها مرة واحدة، مش استعلامين لكل صف.

كل صف تركيبة كان بيعمل استعلام للمنتج (بالـslug) واستعلام للكود (بالـSKU) قبل الحفظ، فدفعة
500 صف كانت بتضيف ألف استعلام. الدفعة بقت تجهّز الخريطتين مرة واحدة، والصف بيدور فيهم.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.applications.apparel.modules.catalog.service import CatalogService
from app.platform.imports.fields import SHEET_VARIANTS
from app.workers.import_runner import run_batch
from tests.test_imports_run import _job, _row, _session

pytestmark = pytest.mark.asyncio

ROWS = 12


async def _shop_with_variants(db, tenant_ctx, existing=3):
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="تيشيرت", slug="tee"
    )
    for i in range(existing):
        await CatalogService.add_variant(
            db, tenant_ctx.tenant_id, product.id, sku=f"OLD-{i}", price=Decimal("50")
        )
    return product


def _spy(monkeypatch, db):
    """Count every statement the batch runs and remember which ones ran."""
    statements: list[str] = []
    real = type(db).execute

    async def _execute(self, statement, *args, **kwargs):
        statements.append(" ".join(str(statement).split()))
        return await real(self, statement, *args, **kwargs)

    monkeypatch.setattr(type(db), "execute", _execute)
    return statements


async def test_a_batch_looks_its_products_and_skus_up_once(db, tenant_ctx, monkeypatch):
    t = tenant_ctx.tenant_id
    await _shop_with_variants(db, tenant_ctx)
    s = await _session(db, t)
    rows = [
        _row(
            s,
            SHEET_VARIANTS,
            2 + i,
            "create",
            {"product_ref": "tee", "sku": f"NEW-{i}", "price": Decimal("120")},
        )
        for i in range(ROWS)
    ]
    db.add_all(rows)
    await db.flush()

    statements = _spy(monkeypatch, db)
    result = await run_batch(db, await _job(db, t, s))

    assert result["applied"] == ROWS, result
    # مفيش استعلام منتج لكل صف، ومفيش استعلام كود لكل صف
    assert not [q for q in statements if q.startswith("SELECT id FROM products WHERE")]
    assert not [q for q in statements if q.startswith("SELECT id FROM product_variants")]
    # الخريطتين اتجمعوا مرة واحدة
    assert len([q for q in statements if "ANY(" in q]) == 2
    # والسقف: الدفعة مش خطية بنفس الشكل القديم (كانت ~6 استعلامات للصف)
    assert len(statements) < ROWS * 4


async def test_an_existing_sku_is_updated_through_the_batch_map(db, tenant_ctx, monkeypatch):
    """الصنف الموجود بيتلقي في الخريطة ويتحدّث، مش بيتعمل استعلام عنه في كل صف."""
    t = tenant_ctx.tenant_id
    await _shop_with_variants(db, tenant_ctx, existing=1)
    s = await _session(db, t)
    db.add_all(
        [
            _row(
                s,
                SHEET_VARIANTS,
                2 + i,
                "update",
                {"product_ref": "tee", "sku": "OLD-0", "price": Decimal("70")},
            )
            for i in range(3)
        ]
    )
    await db.flush()

    statements = _spy(monkeypatch, db)
    result = await run_batch(db, await _job(db, t, s))

    assert result["applied"] == 3, result
    assert not [q for q in statements if q.startswith("SELECT id FROM product_variants")]
    price = await db.scalar(
        sa.text(
            "SELECT price FROM product_variants WHERE tenant_id = :t AND sku = :sku"
        ).bindparams(t=t, sku="OLD-0")
    )
    assert str(price) == "70.00"

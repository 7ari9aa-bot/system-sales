"""رقم الـSKU الأساسي بيتخصص ذريًا: طلبين شافوا نفس الرقم مابياخدوش نفس النتيجة.

الشاشة كانت بتعرض max+1 من غير حجز، فموظفين في نفس اللحظة بياخدوا نفس الرقم وواحد منهم يفشل
عند الحفظ. العدّاد في sku_counters بيتزق بجملة واحدة (INSERT ... ON CONFLICT ... RETURNING)،
والـintake بيطلب رقم جديد بدل ما يفشل.
"""

from __future__ import annotations

import uuid

import pytest

from app.applications.apparel.modules.catalog.service import CatalogService
from tests._pos_helpers import _warehouse, ctx_for
from tests.test_catalog_product_intake import _body, _call

pytestmark = pytest.mark.asyncio


async def test_the_counter_hands_out_a_new_number_every_time(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    first = await CatalogService.allocate_sku_base(db, t)
    second = await CatalogService.allocate_sku_base(db, t)
    third = await CatalogService.allocate_sku_base(db, t)
    assert [first, second, third] == ["SKU-0001", "SKU-0002", "SKU-0003"]


async def test_two_requests_that_saw_the_same_highest_number_get_different_ones(db, tenant_ctx):
    """ده بالظبط سباق الموظفين: الاتنين شافوا نفس أعلى رقم، والعدّاد بيدي كل واحد رقم مختلف."""
    t = tenant_ctx.tenant_id
    product = await CatalogService.create_product(
        db, t, title="تيشيرت", slug=f"race-{uuid.uuid4().hex[:8]}"
    )
    await CatalogService.add_variant(db, t, product.id, sku="SKU-0007-0101", price=10)

    shown = await CatalogService.next_sku_base(db, t)  # اللي الشاشة بتعرضه للاتنين
    assert shown == "SKU-0008"

    one = await CatalogService.allocate_sku_base(db, t)
    two = await CatalogService.allocate_sku_base(db, t)
    assert one != two
    assert {one, two} == {"SKU-0008", "SKU-0009"}


async def test_a_taken_number_is_replaced_at_save_time_not_refused(db, tenant_ctx):
    """الحفظ بينجح برقم جديد بدل ما يفشل بتعارض، والتركيبة بتحتفظ بنهايتها (‑0101)."""
    owner = await ctx_for(db, tenant_ctx, "owner")
    t = tenant_ctx.tenant_id
    product = await CatalogService.create_product(
        db, t, title="تيشيرت قديم", slug=f"old-{uuid.uuid4().hex[:8]}"
    )
    await CatalogService.add_variant(db, t, product.id, sku="SKU-0001-0101", price=10)

    wh = await _warehouse(db, tenant_ctx)
    body = _body(warehouse_id=str(wh.id))
    body["variants"] = [
        {
            "sku": "SKU-0001-0101",
            "price": "250.00",
            "option_values": {"color": "أسود", "size": "M"},
            "stock": 1,
            "auto_barcode": False,
        }
    ]
    r = await _call(owner, "POST", "/api/v1/products/intake", body)
    assert r.status_code == 201, r.text
    skus = [v["sku"] for v in r.json()["variants"]]
    assert skus == ["SKU-0002-0101"]


async def test_a_duplicated_vendor_code_is_still_a_real_error(db, tenant_ctx):
    """كود المورد مش من سلسلة المحل: تكراره خطأ حقيقي بيتقال للتاجر، مش بيتغيّر لوحده."""
    owner = await ctx_for(db, tenant_ctx, "owner")
    t = tenant_ctx.tenant_id
    product = await CatalogService.create_product(
        db, t, title="تيشيرت مورد", slug=f"vendor-{uuid.uuid4().hex[:8]}"
    )
    await CatalogService.add_variant(db, t, product.id, sku="TEE-BK-M", price=10)

    wh = await _warehouse(db, tenant_ctx)
    body = _body(warehouse_id=str(wh.id))
    body["variants"] = [
        {
            "sku": "TEE-BK-M",
            "price": "250.00",
            "option_values": {},
            "stock": 1,
            "auto_barcode": False,
        }
    ]
    r = await _call(owner, "POST", "/api/v1/products/intake", body)
    assert r.status_code in (409, 400), r.text

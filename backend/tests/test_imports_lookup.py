"""The import's read-model against a real database (raw SQL: a renamed column fails here)."""

from __future__ import annotations

import uuid

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.core.db import bind_tenant
from app.applications.apparel.modules.catalog.service import CatalogService
from app.platform.identity.models import Tenant
from app.platform.imports import lookup
from app.platform.imports.validation import Existing
from app.applications.apparel.modules.inventory.models import Warehouse
from app.applications.apparel.modules.inventory.service import InventoryService
from app.platform.settings.service import SettingsService


async def _warehouse(db, tenant_id, code: str, *, active: bool = True) -> Warehouse:
    wh = Warehouse(tenant_id=tenant_id, name=code, code=code, is_active=active)
    db.add(wh)
    await db.flush()
    return wh


async def _product(db, tenant_id, slug: str, *skus: str):
    product = await CatalogService.create_product(db, tenant_id, title=slug, slug=slug)
    variants = [
        await CatalogService.add_variant(db, tenant_id, product.id, sku=sku, price="10.00")
        for sku in skus
    ]
    return product, variants


async def test_existing_reports_products_skus_barcodes_and_active_warehouses(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    _, (v,) = await _product(db, t, "tee", "TEE-1")
    await CatalogService.add_identifier(db, t, v.id, "barcode", "6221")
    await CatalogService.add_identifier(db, t, v.id, "ean", "EAN-ONLY")  # other type: not a barcode
    await _warehouse(db, t, "MAIN")
    await _warehouse(db, t, "OLD", active=False)

    ex = await lookup.load_existing(
        db,
        t,
        product_refs=["tee", "nope"],
        skus=["TEE-1", "GHOST"],
        barcodes=["6221", "EAN-ONLY", "0000"],
    )

    assert ex.product_slugs == {"tee"}
    assert ex.sku_owner == {"TEE-1": "tee"}
    assert ex.barcode_owner == {"6221": "TEE-1"}
    assert ex.warehouse_codes == {"MAIN"}


async def test_another_shops_data_is_never_visible(db, tenant_ctx):
    mine = tenant_ctx.tenant_id
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Shop")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    await _product(db, other.id, "secret", "SECRET-1")
    await _warehouse(db, other.id, "THEIRS")
    await bind_tenant(db, mine)

    ex = await lookup.load_existing(
        db, mine, product_refs=["secret"], skus=["SECRET-1"], barcodes=[]
    )
    assert ex == Existing()
    assert await lookup.known_variant_skus(db, mine, ["SECRET-1"]) == set()


async def test_more_keys_than_one_chunk_are_all_found(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    n = lookup.CHUNK + 37
    # catalog.max_variants_per_product caps variants at 100 by default; this test is about
    # reading more SKUs than one chunk, so it lifts the cap to what it needs instead of
    # shrinking the chunk. 0 is not "no cap" — the registry's minimum is 1, and asking for it
    # raised ValidationError before a single variant was created.
    await SettingsService(db, t).set("catalog.max_variants_per_product", n, scope="tenant")
    product = await CatalogService.create_product(db, t, title="Bulk", slug="bulk")
    for i in range(n):
        await CatalogService.add_variant(db, t, product.id, sku=f"B-{i:04d}", price="1.00")

    wanted = [f"B-{i:04d}" for i in range(n)] + ["MISSING"]
    found = await lookup.known_variant_skus(db, t, wanted)

    assert len(found) == n and "MISSING" not in found


async def test_opening_stock_done_sees_only_opening_stock_movements(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t, "MAIN")
    _, (a, b) = await _product(db, t, "p", "A", "B")
    await InventoryService.move(
        db, t, a.id, wh.id, direction="in", quantity=3, reason="opening_stock"
    )
    await InventoryService.move(db, t, b.id, wh.id, direction="in", quantity=3, reason="purchase")

    assert await lookup.load_opening_stock_done(db, t, ["A", "B", "C"]) == {("A", "MAIN")}


async def test_empty_inputs_do_no_work(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    ex = await lookup.load_existing(db, t, product_refs=[], skus=[], barcodes=[])
    assert ex == Existing()
    assert await lookup.load_opening_stock_done(db, t, []) == set()


def test_default_warehouse_is_explicit_choice_or_the_only_one_never_a_guess():
    one, many = Existing(warehouse_codes={"MAIN"}), Existing(warehouse_codes={"A", "B"})
    assert lookup.default_warehouse(many, "B") == "B"
    assert lookup.default_warehouse(one, None) == "MAIN"
    assert lookup.default_warehouse(many, None) is None
    assert lookup.default_warehouse(Existing(), None) is None


def test_keys_are_split_into_chunks_no_larger_than_the_batch_limit():
    batches = list(lookup._chunks(range(lookup.CHUNK * 2 + 1)))
    assert [len(b) for b in batches] == [lookup.CHUNK, lookup.CHUNK, 1]
    assert list(lookup._chunks([])) == []
    assert lookup.CHUNK == 500  # the standing batch ceiling for imports

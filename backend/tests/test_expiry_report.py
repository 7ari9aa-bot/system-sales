"""The expiry report: which batches the shop must sell, return or throw away, and by when.

The window ("how many days ahead is *soon*") is the owner's decision, not a number in the code.
A shop that is not a pharmacy-like business (the capability is off) gets no report to act on, so
the screen and the API agree about who sees it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import app.applications.apparel.modules.purchasing.models  # noqa: F401 - registers the suppliers table
from app.applications.apparel.modules.catalog.models import Product, ProductVariant
from app.applications.apparel.modules.inventory.models import InventoryLot
from app.applications.apparel.modules.inventory.services.expiry import expiry_report
from app.platform.settings.service import SettingsService

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


async def _variant(db, tid, sku="PARA-500"):
    prod = Product(tenant_id=tid, title="Paracetamol", slug=f"p-{sku}", status="active")
    db.add(prod)
    await db.flush()
    var = ProductVariant(
        tenant_id=tid,
        product_id=prod.id,
        sku=sku,
        title="500mg",
        price=Decimal("20"),
        is_active=True,
    )
    db.add(var)
    await db.flush()
    return var


async def _lot(db, tid, var, code, days):
    lot = InventoryLot(
        tenant_id=tid,
        variant_id=var.id,
        lot_code=code,
        expires_at=None if days is None else NOW + timedelta(days=days),
    )
    db.add(lot)
    await db.flush()
    return lot


async def _on(db, tid, days=None):
    s = SettingsService(db, tid)
    await s.set("business.vertical", "pharmacy")
    if days is not None:
        await s.set("inventory.expiry_alert_days", days)


async def test_a_shop_without_the_capability_gets_no_report(db, tenant_ctx) -> None:
    var = await _variant(db, tenant_ctx.tenant_id)
    await _lot(db, tenant_ctx.tenant_id, var, "L1", -5)
    out = await expiry_report(db, tenant_ctx.tenant_id, now=NOW)
    assert out["enabled"] is False
    assert out["expired"] == [] and out["expiring"] == []


async def test_batches_split_into_expired_soon_and_fine(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _on(db, tid)  # default window
    var = await _variant(db, tid)
    await _lot(db, tid, var, "OLD", -3)
    await _lot(db, tid, var, "SOON", 10)
    await _lot(db, tid, var, "LATER", 400)
    out = await expiry_report(db, tid, now=NOW)
    assert out["enabled"] is True
    assert [r["lot_code"] for r in out["expired"]] == ["OLD"]
    assert [r["lot_code"] for r in out["expiring"]] == ["SOON"]
    assert out["fine_count"] == 1


async def test_the_owners_window_decides_what_counts_as_soon(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _on(db, tid, days=5)
    var = await _variant(db, tid)
    await _lot(db, tid, var, "D4", 4)
    await _lot(db, tid, var, "D10", 10)
    assert [r["lot_code"] for r in (await expiry_report(db, tid, now=NOW))["expiring"]] == ["D4"]
    await SettingsService(db, tid).set("inventory.expiry_alert_days", 30)
    got = await expiry_report(db, tid, now=NOW)
    assert [r["lot_code"] for r in got["expiring"]] == ["D4", "D10"]
    assert got["window_days"] == 30


async def test_a_batch_expiring_exactly_at_the_edge_counts_as_soon_not_fine(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _on(db, tid, days=7)
    var = await _variant(db, tid)
    await _lot(db, tid, var, "EDGE", 7)
    await _lot(db, tid, var, "PAST-EDGE", 8)
    out = await expiry_report(db, tid, now=NOW)
    assert [r["lot_code"] for r in out["expiring"]] == ["EDGE"]
    assert out["fine_count"] == 1


async def test_a_batch_that_expires_right_now_is_expired(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _on(db, tid)
    var = await _variant(db, tid)
    await _lot(db, tid, var, "NOW", 0)
    out = await expiry_report(db, tid, now=NOW)
    assert [r["lot_code"] for r in out["expired"]] == ["NOW"]
    assert out["expiring"] == []


async def test_a_batch_with_no_expiry_date_is_never_listed(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _on(db, tid)
    var = await _variant(db, tid)
    await _lot(db, tid, var, "NODATE", None)
    out = await expiry_report(db, tid, now=NOW)
    assert out["expired"] == [] and out["expiring"] == [] and out["fine_count"] == 0


async def test_lists_are_soonest_first_and_carry_what_the_shop_needs_to_act(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _on(db, tid, days=60)
    var = await _variant(db, tid)
    await _lot(db, tid, var, "B", 20)
    await _lot(db, tid, var, "A", 5)
    await _lot(db, tid, var, "X2", -1)
    await _lot(db, tid, var, "X1", -9)
    out = await expiry_report(db, tid, now=NOW)
    assert [r["lot_code"] for r in out["expiring"]] == ["A", "B"]
    assert [r["lot_code"] for r in out["expired"]] == ["X1", "X2"]
    row = out["expiring"][0]
    assert row["sku"] == "PARA-500" and row["product"] == "Paracetamol"
    assert row["days_left"] == 5
    assert out["expired"][0]["days_left"] == -9


async def test_one_shop_never_sees_anothers_batches(db, tenant_ctx) -> None:
    import uuid

    tid = tenant_ctx.tenant_id
    await _on(db, tid)
    var = await _variant(db, tid)
    await _lot(db, tid, var, "MINE", -2)
    out = await expiry_report(db, uuid.uuid4(), now=NOW)
    assert out["expired"] == [] and out["expiring"] == []


async def test_the_query_is_scoped_to_the_shop_in_the_statement_itself(
    db, tenant_ctx, monkeypatch
) -> None:
    """Row-level security is the backstop; the query must also name the shop on its own."""
    tid = tenant_ctx.tenant_id
    await _on(db, tid)
    seen: list[str] = []
    real = db.execute

    async def spy(stmt, *a, **k):
        seen.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        return await real(stmt, *a, **k)

    monkeypatch.setattr(db, "execute", spy)
    await expiry_report(db, tid, now=NOW)
    lot_queries = [q for q in seen if "inventory_lots" in q]
    assert lot_queries and all("inventory_lots.tenant_id =" in q for q in lot_queries)


async def test_each_batch_reports_the_units_it_still_holds(db, tenant_ctx) -> None:
    from app.applications.apparel.modules.inventory.services.valuation import ValuationService

    tid = tenant_ctx.tenant_id
    await _on(db, tid)
    var = await _variant(db, tid)
    from app.applications.apparel.modules.inventory.models import Warehouse

    wh = Warehouse(tenant_id=tid, name="M", code="WH-Q", is_active=True)
    db.add(wh)
    await db.flush()
    lot = await _lot(db, tid, var, "HOLDS", 5)
    layer = await ValuationService.create_cost_layer(
        db,
        tid,
        variant_id=var.id,
        warehouse_id=wh.id,
        quantity=10,
        unit_cost=Decimal("3"),
        lot_id=lot.id,
    )
    layer.remaining_quantity = 6  # four already sold out of it
    await db.flush()
    await _lot(db, tid, var, "UNTRACKED", 6)  # a batch no layer names: quantity unknown
    out = await expiry_report(db, tid, now=NOW)
    qty = {r["lot_code"]: r["quantity"] for r in out["expiring"]}
    assert qty == {"HOLDS": 6, "UNTRACKED": None}


async def test_the_report_totals_the_units_at_risk(db, tenant_ctx) -> None:
    from app.applications.apparel.modules.inventory.models import Warehouse
    from app.applications.apparel.modules.inventory.services.valuation import ValuationService

    tid = tenant_ctx.tenant_id
    await _on(db, tid)
    var = await _variant(db, tid)
    wh = Warehouse(tenant_id=tid, name="M", code="WH-T", is_active=True)
    db.add(wh)
    await db.flush()
    for code, days, qty in (("X", -3, 4), ("S", 5, 7), ("F", 400, 9)):
        lot = await _lot(db, tid, var, code, days)
        await ValuationService.create_cost_layer(
            db,
            tid,
            variant_id=var.id,
            warehouse_id=wh.id,
            quantity=qty,
            unit_cost=Decimal("3"),
            lot_id=lot.id,
        )
    out = await expiry_report(db, tid, now=NOW)
    assert out["expired_units"] == 4
    assert out["expiring_units"] == 7

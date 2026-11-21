"""A goods receipt can say which batch the stock arrived in.

The receipt line optionally carries a batch code and an expiry date. With a code, the batch is
found (or created) and the cost layer the receipt makes names it, so a batch's quantity is what its
layers have left. Without a code nothing changes at all: a clothing shop that never sends one gets
exactly the layers it always got.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import app.modules.purchasing.models  # noqa: F401 - registers the suppliers table
from app.core.errors import ValidationError
from app.modules.catalog.service import CatalogService
from app.modules.inventory.models import InventoryCostLayer, InventoryLot, Warehouse
from app.modules.purchasing.service import (
    GoodsReceiptService,
    PurchaseService,
    SupplierService,
)

pytestmark = pytest.mark.asyncio

EXP = datetime(2027, 6, 1, tzinfo=UTC)


async def _po(db, tid):
    wh = Warehouse(tenant_id=tid, name="W", code=f"W-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(wh)
    await db.flush()
    prod = await CatalogService.create_product(
        db, tid, title="Coat", slug=f"c-{uuid.uuid4().hex[:8]}"
    )
    var = await CatalogService.add_variant(db, tid, prod.id, price="500.00")
    sup = await SupplierService.create(db, tid, name=f"S-{uuid.uuid4().hex[:4]}")
    po = await PurchaseService.create(
        db,
        tid,
        supplier_id=sup.id,
        warehouse_id=wh.id,
        lines=[{"variant_id": str(var.id), "quantity": 20, "unit_cost": "100.00"}],
    )
    pol = (await PurchaseService._lines_in(db, tid, po.id))[0]
    return po, pol, var, wh


def _line(pol, var, qty, **extra):
    return {
        "purchase_order_line_id": str(pol.id),
        "variant_id": str(var.id),
        "quantity": qty,
        "unit_cost": "100.00",
        **extra,
    }


async def _layers(db, tid, var):
    return list(
        (
            await db.execute(
                select(InventoryCostLayer).where(
                    InventoryCostLayer.tenant_id == tid, InventoryCostLayer.variant_id == var.id
                )
            )
        ).scalars()
    )


async def _post(db, tid, uid, po, lines):
    r = await GoodsReceiptService.create(db, tid, purchase_order_id=po.id, lines=lines)
    await GoodsReceiptService.post(db, tid, r.id, actor_user_id=uid)
    return r


async def test_a_receipt_line_with_a_batch_code_makes_the_layer_name_that_batch(
    db, tenant_ctx
) -> None:
    tid, uid = tenant_ctx.tenant_id, tenant_ctx.user.id
    po, pol, var, _ = await _po(db, tid)
    await _post(
        db, tid, uid, po, [_line(pol, var, 8, lot_code="WINTER-26", lot_expires_at=EXP.isoformat())]
    )
    (layer,) = await _layers(db, tid, var)
    lot = (
        await db.execute(select(InventoryLot).where(InventoryLot.id == layer.lot_id))
    ).scalar_one()
    assert (lot.lot_code, lot.expires_at, layer.remaining_quantity) == ("WINTER-26", EXP, 8)


async def test_a_receipt_line_without_a_batch_code_changes_nothing(db, tenant_ctx) -> None:
    tid, uid = tenant_ctx.tenant_id, tenant_ctx.user.id
    po, pol, var, _ = await _po(db, tid)
    await _post(db, tid, uid, po, [_line(pol, var, 8)])
    (layer,) = await _layers(db, tid, var)
    assert layer.lot_id is None
    assert (await db.execute(select(InventoryLot))).first() is None


async def test_a_second_delivery_of_the_same_batch_joins_the_batch_already_there(
    db, tenant_ctx
) -> None:
    tid, uid = tenant_ctx.tenant_id, tenant_ctx.user.id
    po, pol, var, _ = await _po(db, tid)
    await _post(
        db, tid, uid, po, [_line(pol, var, 5, lot_code="B1", lot_expires_at=EXP.isoformat())]
    )
    await _post(
        db, tid, uid, po, [_line(pol, var, 4, lot_code="B1", lot_expires_at=EXP.isoformat())]
    )
    layers = await _layers(db, tid, var)
    lots = list(
        (await db.execute(select(InventoryLot).where(InventoryLot.variant_id == var.id))).scalars()
    )
    assert len(lots) == 1
    assert len({layer.lot_id for layer in layers}) == 1
    assert sum(layer.remaining_quantity for layer in layers) == 9


async def test_two_codes_make_two_batches(db, tenant_ctx) -> None:
    tid, uid = tenant_ctx.tenant_id, tenant_ctx.user.id
    po, pol, var, _ = await _po(db, tid)
    await _post(db, tid, uid, po, [_line(pol, var, 5, lot_code="A")])
    await _post(db, tid, uid, po, [_line(pol, var, 4, lot_code="B")])
    codes = {
        row.lot_code
        for row in (
            await db.execute(select(InventoryLot).where(InventoryLot.variant_id == var.id))
        ).scalars()
    }
    assert codes == {"A", "B"}


async def test_the_same_batch_code_with_a_different_expiry_is_refused(db, tenant_ctx) -> None:
    tid, uid = tenant_ctx.tenant_id, tenant_ctx.user.id
    po, pol, var, _ = await _po(db, tid)
    await _post(
        db, tid, uid, po, [_line(pol, var, 5, lot_code="B1", lot_expires_at=EXP.isoformat())]
    )
    later = (EXP + timedelta(days=90)).isoformat()
    with pytest.raises(ValidationError, match="B1"):
        await _post(db, tid, uid, po, [_line(pol, var, 4, lot_code="B1", lot_expires_at=later)])


async def test_an_expiry_date_without_a_batch_code_is_refused(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    po, pol, var, _ = await _po(db, tid)
    with pytest.raises(ValidationError):
        await GoodsReceiptService.create(
            db,
            tid,
            purchase_order_id=po.id,
            lines=[_line(pol, var, 5, lot_expires_at=EXP.isoformat())],
        )


async def test_a_batch_code_may_have_no_expiry_date(db, tenant_ctx) -> None:
    """A clothing shop labels a delivery 'SPRING-26' and has no expiry to give."""
    tid, uid = tenant_ctx.tenant_id, tenant_ctx.user.id
    po, pol, var, _ = await _po(db, tid)
    await _post(db, tid, uid, po, [_line(pol, var, 5, lot_code="SPRING-26")])
    (layer,) = await _layers(db, tid, var)
    lot = (
        await db.execute(select(InventoryLot).where(InventoryLot.id == layer.lot_id))
    ).scalar_one()
    assert lot.expires_at is None


async def test_one_shipment_code_across_two_sizes_makes_a_batch_for_each_size(
    db, tenant_ctx
) -> None:
    """Clothing: the same delivery arrives in several sizes, each its own variant.

    The batch belongs to the variant, so 'SPRING-26' in size M and in size L are two batches and
    each size's quantity stays its own.
    """
    tid, uid = tenant_ctx.tenant_id, tenant_ctx.user.id
    po, pol_m, var_m, wh = await _po(db, tid)
    prod = await CatalogService.create_product(
        db, tid, title="Coat L", slug=f"l-{uuid.uuid4().hex[:8]}"
    )
    var_l = await CatalogService.add_variant(db, tid, prod.id, price="500.00")
    po2 = await PurchaseService.create(
        db,
        tid,
        supplier_id=po.supplier_id,
        warehouse_id=wh.id,
        lines=[{"variant_id": str(var_l.id), "quantity": 20, "unit_cost": "100.00"}],
    )
    pol_l = (await PurchaseService._lines_in(db, tid, po2.id))[0]
    await _post(db, tid, uid, po, [_line(pol_m, var_m, 6, lot_code="SPRING-26")])
    await _post(db, tid, uid, po2, [_line(pol_l, var_l, 3, lot_code="SPRING-26")])
    lots = list(
        (
            await db.execute(select(InventoryLot).where(InventoryLot.lot_code == "SPRING-26"))
        ).scalars()
    )
    assert {lot.variant_id for lot in lots} == {var_m.id, var_l.id}
    (lm,) = await _layers(db, tid, var_m)
    (ll,) = await _layers(db, tid, var_l)
    assert lm.lot_id != ll.lot_id


async def test_an_expiry_date_with_no_time_zone_is_read_as_utc(db, tenant_ctx) -> None:
    tid, uid = tenant_ctx.tenant_id, tenant_ctx.user.id
    po, pol, var, _ = await _po(db, tid)
    await _post(
        db,
        tid,
        uid,
        po,
        [_line(pol, var, 5, lot_code="NAIVE", lot_expires_at="2027-06-01T00:00:00")],
    )
    (layer,) = await _layers(db, tid, var)
    lot = (
        await db.execute(select(InventoryLot).where(InventoryLot.id == layer.lot_id))
    ).scalar_one()
    assert lot.expires_at == datetime(2027, 6, 1, tzinfo=UTC)
    assert lot.expires_at.utcoffset() == timedelta(0)


def test_clean_batch_gives_a_date_with_no_zone_the_utc_zone() -> None:
    """Pure check: the session's time zone must never decide what day a batch expires."""
    from app.modules.purchasing.service import _clean_batch

    _, naive = _clean_batch({"lot_code": "X", "lot_expires_at": "2027-06-01T00:00:00"}, 1)
    _, aware = _clean_batch({"lot_code": "X", "lot_expires_at": "2027-06-01T00:00:00+00:00"}, 1)
    assert naive == aware == datetime(2027, 6, 1, tzinfo=UTC)
    assert naive.tzinfo is not None


def test_clean_batch_rejects_text_that_is_not_a_date() -> None:
    from app.modules.purchasing.service import _clean_batch

    with pytest.raises(ValidationError, match="not a valid date"):
        _clean_batch({"lot_code": "X", "lot_expires_at": "next spring"}, 1)

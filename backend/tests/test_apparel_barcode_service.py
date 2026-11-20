"""Giving stock the shop's own barcodes, on a real database."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.catalog.apparel.barcode import is_internal, is_valid_ean13
from app.modules.catalog.apparel.barcode_service import MAX_BATCH
from app.modules.catalog.apparel.barcode_service import BarcodeService as B
from app.modules.catalog.apparel.service import ApparelMatrixService as M
from app.modules.catalog.models import ProductIdentifier
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, NotFoundError, ValidationError

pytestmark = pytest.mark.asyncio


async def _garment(db, tenant_ctx, sizes=("S", "M", "L"), colors=("x",)):
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="قميص", slug=f"b-{uuid.uuid4().hex[:10]}"
    )
    made = await M.generate(
        db,
        tenant_ctx.tenant_id,
        product.id,
        sizes=list(sizes),
        colors=list(colors),
        price="10",
        sku_prefix=f"B{uuid.uuid4().hex[:4]}",
    )
    return [v.id for v in made.created]


async def test_every_unlabelled_variant_gets_its_own_valid_barcode(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    ids = await _garment(db, tenant_ctx)
    result = await B.assign_missing(db, t, ids)
    assert set(result.assigned) == set(ids) and result.already == {}
    codes = list(result.assigned.values())
    assert len(set(codes)) == 3 and all(is_valid_ean13(c) and is_internal(c) for c in codes)
    # and a till scanning it finds exactly that variant
    for variant_id, code in result.assigned.items():
        found = await CatalogService.resolve_identifier(db, t, "barcode", code)
        assert found is not None and found.id == variant_id


async def test_a_manufacturers_barcode_is_never_replaced_and_uses_no_number(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    a, b, c = await _garment(db, tenant_ctx)
    await CatalogService.add_identifier(db, t, b, "ean", "4006381333931")
    result = await B.assign_missing(db, t, [a, b, c])
    assert set(result.assigned) == {a, c}
    assert result.already == {b: "4006381333931"}
    # b still has exactly its own code and nothing else
    rows = (
        (await db.execute(select(ProductIdentifier.value).where(ProductIdentifier.variant_id == b)))
        .scalars()
        .all()
    )
    assert rows == ["4006381333931"]
    # the two numbers used were consecutive: b did not burn one
    first, second = sorted(int(x[1:12]) for x in result.assigned.values())
    assert second == first + 1


async def test_running_it_again_assigns_nothing_new(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    ids = await _garment(db, tenant_ctx)
    first = await B.assign_missing(db, t, ids)
    again = await B.assign_missing(db, t, ids)
    assert again.assigned == {}
    assert set(again.already.values()) == set(first.assigned.values())
    count = (
        await db.execute(
            select(func.count())
            .select_from(ProductIdentifier)
            .where(ProductIdentifier.tenant_id == t)
        )
    ).scalar_one()
    assert count == 3


async def test_two_garments_labelled_one_after_the_other_never_share_a_number(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    one = await B.assign_missing(db, t, await _garment(db, tenant_ctx))
    two = await B.assign_missing(db, t, await _garment(db, tenant_ctx, sizes=("M", "L")))
    codes = list(one.assigned.values()) + list(two.assigned.values())
    assert len(codes) == 5 and len(set(codes)) == 5


async def test_the_sequence_does_not_restart_in_a_new_year(db, tenant_ctx) -> None:
    from app.modules.expenses.models import DocumentCounter

    t = tenant_ctx.tenant_id
    await B.assign_missing(db, t, await _garment(db, tenant_ctx))
    counters = (
        (
            await db.execute(
                select(DocumentCounter).where(
                    DocumentCounter.tenant_id == t, DocumentCounter.kind == "BC"
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(c.year, c.last_seq) for c in counters] == [(0, 3)]  # one endless counter


async def test_one_unknown_variant_labels_nothing_at_all(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    ids = await _garment(db, tenant_ctx)
    with pytest.raises(NotFoundError):
        await B.assign_missing(db, t, [*ids, uuid.uuid4()])
    count = (
        await db.execute(
            select(func.count())
            .select_from(ProductIdentifier)
            .where(ProductIdentifier.tenant_id == t)
        )
    ).scalar_one()
    assert count == 0


async def test_another_shops_variants_are_invisible(db, tenant_ctx) -> None:
    ids = await _garment(db, tenant_ctx)
    with pytest.raises(NotFoundError):
        await B.assign_missing(db, uuid.uuid4(), ids)


async def test_empty_and_oversized_requests_are_refused(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    with pytest.raises(ValidationError):
        await B.assign_missing(db, t, [])
    with pytest.raises(ValidationError):
        await B.assign_missing(db, t, [uuid.uuid4() for _ in range(MAX_BATCH + 1)])


async def test_a_repeated_id_in_the_request_is_labelled_once(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    ids = await _garment(db, tenant_ctx)
    result = await B.assign_missing(db, t, [ids[0], ids[0], ids[0]])
    assert list(result.assigned) == [ids[0]]
    # the dict above would hide a double label (same key twice): count the rows that exist
    rows = (
        await db.execute(
            select(func.count())
            .select_from(ProductIdentifier)
            .where(ProductIdentifier.variant_id == ids[0])
        )
    ).scalar_one()
    assert rows == 1
    # and no number was wasted on the repeats
    nxt = await B.assign_missing(db, t, [ids[1]])
    first = int(result.assigned[ids[0]][1:12])
    assert int(nxt.assigned[ids[1]][1:12]) == first + 1


async def test_a_clash_with_an_existing_identical_code_is_a_conflict_not_a_silent_skip(
    db, tenant_ctx
) -> None:
    from app.modules.catalog.apparel.barcode import internal_ean13

    t = tenant_ctx.tenant_id
    a, b, _ = await _garment(db, tenant_ctx)
    # somebody typed the very number the counter is about to hand out onto another variant
    await CatalogService.add_identifier(db, t, a, "barcode", internal_ean13(1))
    with pytest.raises(ConflictError):
        await B.assign_missing(db, t, [b])

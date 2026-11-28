"""The import session lifecycle on a real database: upload, map, check, preview, start, cancel."""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from openpyxl import Workbook

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.core.db import bind_tenant
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.applications.apparel.modules.catalog.service import CatalogService
from app.modules.identity.models import Tenant
from app.modules.imports import service
from app.applications.apparel.modules.inventory.models import Warehouse


def _xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


GOOD_FILE = {
    "Products": [["Product ref", "Name"], ["tee", "Tee"], ["cap", "Cap"]],
    "Variants": [
        ["Product ref", "SKU", "Price", "Barcode"],
        ["tee", "TEE-1", "99.50", "6221000000011"],
        ["cap", "CAP-1", "50", ""],
    ],
    "Opening Stock": [["SKU", "Warehouse", "Quantity"], ["TEE-1", "MAIN", 12]],
}


async def _enqueue(session, tenant_id, session_id, user_id):
    """Stands in for JobService.create: the service only needs a job with an id back."""
    return SimpleNamespace(id=None)


async def _upload(db, tenant_id, sheets=None, name="catalog.xlsx"):
    return await service.create_session(
        db, tenant_id, file_name=name, data=_xlsx(sheets or GOOD_FILE), user_id=None
    )


async def _row_statuses(db, imp) -> dict[str, int]:
    rows = await db.execute(
        sa.text("select status, count(*) from import_rows where session_id=:i group by 1"),
        {"i": imp.id},
    )
    return dict(rows.all())


async def test_uploading_a_file_keeps_its_rows_and_guesses_the_columns(db, tenant_ctx):
    imp = await _upload(db, tenant_ctx.tenant_id)

    assert imp.status == "analyzed"
    assert imp.file_size and len(imp.file_sha256) == 64
    assert imp.file_key is None  # the private price list is not kept, only its rows
    assert imp.stats["rows"] == {"Products": 2, "Variants": 2, "Opening Stock": 1}
    assert imp.mapping["Variants"]["SKU"] == "sku"
    assert imp.mapping["Variants"]["Price"] == "price"
    assert await _row_statuses(db, imp) == {"pending": 5}


async def test_a_csv_is_taken_as_the_product_list(db, tenant_ctx):
    data = "اسم المنتج,SKU,السعر\nقميص,S-1,100\n".encode("utf-8-sig")
    imp = await service.create_session(
        db, tenant_ctx.tenant_id, file_name="منتجات.csv", data=data, user_id=None
    )
    assert list(imp.mapping) == ["Products"]
    assert imp.stats["rows"] == {"Products": 1}


async def test_a_workbook_with_no_known_sheet_is_refused_with_a_reason(db, tenant_ctx):
    with pytest.raises(
        ValidationError, match="Products, Variants, Opening Stock, Images or Customers"
    ):
        await _upload(db, tenant_ctx.tenant_id, {"Sheet1": [["a"], ["b"]]})


async def test_sheet_names_match_loosely_and_unknown_sheets_are_reported_not_guessed(
    db, tenant_ctx
):
    sheets = {"opening  STOCK": [["SKU", "Quantity"], ["X", 1]], "Notes": [["hi"], ["there"]]}
    imp = await _upload(db, tenant_ctx.tenant_id, sheets)
    assert list(imp.mapping) == ["Opening Stock"]
    assert imp.stats["ignored_sheets"] == ["Notes"]


async def test_the_whole_flow_checks_every_row_and_starts_only_what_is_valid(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    db.add(Warehouse(tenant_id=t, name="Main", code="MAIN"))
    await db.flush()
    imp = await _upload(db, t)

    imp = await service.validate_session(db, t, imp.id)

    assert imp.status == "validated"
    assert await _row_statuses(db, imp) == {"valid": 5}
    assert imp.stats["sheets"]["Variants"]["create"] == 2
    started = await service.start(db, t, imp.id, user_id=None, enqueue=_enqueue)
    assert started.status == "running" and started.stats["to_apply"] == 5


async def test_a_variant_of_a_product_missing_from_the_file_and_shop_is_an_error_row(
    db, tenant_ctx
):
    t = tenant_ctx.tenant_id
    sheets = {
        "Variants": [["Product ref", "SKU", "Price"], ["ghost", "G-1", "5"], ["tee", "T-1", "5"]],
        "Products": [["Product ref", "Name"], ["tee", "Tee"]],
    }
    imp = await service.validate_session(db, t, (await _upload(db, t, sheets)).id)

    assert await _row_statuses(db, imp) == {"valid": 2, "error": 1}
    preview = await service.preview(db, t, imp.id)
    assert preview["sample_errors"][0]["errors"][0]["code"] == "unknown_product"
    assert (preview["sample_errors"][0]["sheet"], preview["sample_errors"][0]["row"]) == (
        "Variants",
        2,
    )


async def test_stock_for_a_sku_that_exists_only_in_the_shop_is_accepted(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    db.add(Warehouse(tenant_id=t, name="Main", code="MAIN"))
    p = await CatalogService.create_product(db, t, title="Old", slug="old")
    await CatalogService.add_variant(db, t, p.id, sku="OLD-1", price="1.00")
    sheets = {"Opening Stock": [["SKU", "Quantity"], ["OLD-1", 4], ["NOPE-1", 4]]}

    imp = await service.validate_session(db, t, (await _upload(db, t, sheets)).id)

    assert await _row_statuses(db, imp) == {"valid": 1, "error": 1}


async def test_starting_an_unchecked_or_empty_import_is_refused(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    imp = await _upload(db, t)
    with pytest.raises(ConflictError, match="check the file"):
        await service.start(db, t, imp.id, user_id=None, enqueue=_enqueue)

    sheets = {"Products": [["Product ref", "Name"], ["", ""]]}
    bad = await service.validate_session(db, t, (await _upload(db, t, sheets)).id)
    with pytest.raises(ValidationError, match="no row can be imported"):
        await service.start(db, t, bad.id, user_id=None, enqueue=_enqueue)


async def test_an_import_cannot_be_started_twice(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    db.add(Warehouse(tenant_id=t, name="Main", code="MAIN"))
    imp = await service.validate_session(db, t, (await _upload(db, t)).id)
    await service.start(db, t, imp.id, user_id=None, enqueue=_enqueue)

    calls = []

    async def counting(*a):
        calls.append(a)
        return SimpleNamespace(id=None)

    with pytest.raises(ConflictError, match="already running"):
        await service.start(db, t, imp.id, user_id=None, enqueue=counting)
    assert calls == []  # no second job was queued


async def test_remapping_makes_the_earlier_check_stale(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    db.add(Warehouse(tenant_id=t, name="Main", code="MAIN"))
    imp = await service.validate_session(db, t, (await _upload(db, t)).id)
    assert imp.status == "validated"

    imp = await service.set_mapping(
        db, t, imp.id, mapping={"Variants": {"Barcode": None}}, options=None
    )

    assert imp.status == "mapped"
    assert "sheets" not in imp.stats
    assert await _row_statuses(db, imp) == {"pending": 5}
    # nothing of the old verdict may linger on a row, or a preview could show a stale one
    leftover = await db.execute(
        sa.text("select count(*) from import_rows where session_id=:i and parsed is not null"),
        {"i": imp.id},
    )
    assert leftover.scalar_one() == 0
    with pytest.raises(ConflictError, match="check the file"):
        await service.start(db, t, imp.id, user_id=None, enqueue=_enqueue)


@pytest.mark.parametrize(
    ("mapping", "options", "message"),
    [
        ({"Nope": {"a": "sku"}}, None, "no sheet 'Nope'"),
        ({"Variants": {"Ghost": "sku"}}, None, "no column 'Ghost'"),
        ({"Variants": {"SKU": "colour_of_sky"}}, None, "not a field"),
        ({"Variants": {"SKU": "sku", "Barcode": "sku"}}, None, "same field"),
        (None, {"duplicate_policy": "delete_everything"}, "invalid option"),
        (None, {"surprise": "yes"}, "invalid option"),
    ],
)
async def test_a_bad_mapping_or_option_is_refused_before_anything_changes(
    db, tenant_ctx, mapping, options, message
):
    t = tenant_ctx.tenant_id
    imp = await _upload(db, t)
    before = dict(imp.mapping["Variants"])

    with pytest.raises(ValidationError, match=message):
        await service.set_mapping(db, t, imp.id, mapping=mapping, options=options)

    assert imp.mapping["Variants"] == before and imp.status == "analyzed"


async def test_the_check_refuses_a_file_whose_required_column_is_unmapped(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    imp = await _upload(db, t)
    await service.set_mapping(db, t, imp.id, mapping={"Variants": {"Price": None}}, options=None)
    with pytest.raises(ValidationError, match="Variants: price"):
        await service.validate_session(db, t, imp.id)


async def test_the_duplicate_policy_decides_what_happens_to_an_existing_product(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await CatalogService.create_product(db, t, title="Tee", slug="tee")
    sheets = {"Products": [["Product ref", "Name"], ["tee", "Tee v2"]]}

    # create_only leaves an existing product alone: a re-uploaded file is not a wall of red errors
    expected = {"create_only": "skipped", "update": "valid", "skip": "skipped"}
    for policy, status in expected.items():
        imp = await _upload(db, t, sheets)
        await service.set_mapping(db, t, imp.id, mapping=None, options={"duplicate_policy": policy})
        imp = await service.validate_session(db, t, imp.id)
        assert await _row_statuses(db, imp) == {status: 1}, policy


async def test_cancel_stops_an_import_and_a_finished_one_cannot_be_cancelled(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    imp = await _upload(db, t)
    assert (await service.cancel(db, t, imp.id)).status == "cancelled"
    with pytest.raises(ConflictError, match="already cancelled"):
        await service.cancel(db, t, imp.id)
    with pytest.raises(ConflictError, match="can no longer be changed"):
        await service.set_mapping(db, t, imp.id, mapping=None, options=None)


async def test_the_error_report_lists_each_refused_row_with_its_cells_and_reason(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    # a fully blank line is dropped by the reader; this row has a handle but no name
    sheets = {"Products": [["Product ref", "Name"], ["a", "Fine"], ["b", ""]]}
    imp = await service.validate_session(db, t, (await _upload(db, t, sheets)).id)

    report = await service.error_rows(db, t, imp.id)

    assert len(report) == 1
    assert report[0]["sheet"] == "Products" and report[0]["row"] == 3
    assert report[0]["raw"] == {"Product ref": "b", "Name": ""}
    assert report[0]["errors"][0]["code"] == "required"


async def test_one_shop_cannot_read_or_change_another_shops_import(db, tenant_ctx):
    mine = await _upload(db, tenant_ctx.tenant_id)
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Shop")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)

    for call in (
        service.get(db, other.id, mine.id),
        service.preview(db, other.id, mine.id),
        service.cancel(db, other.id, mine.id),
        service.error_rows(db, other.id, mine.id),
    ):
        with pytest.raises(NotFoundError):
            await call
    assert await service.list_sessions(db, other.id) == []


async def test_an_unknown_session_is_not_found(db, tenant_ctx):
    with pytest.raises(NotFoundError):
        await service.get(db, tenant_ctx.tenant_id, uuid.uuid4())


async def test_a_large_file_is_checked_in_chunks_and_every_verdict_lands(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    n = 1203  # not a multiple of 500: the last chunk is short
    sheets = {"Products": [["Product ref", "Name"], *[[f"p{i}", f"P{i}"] for i in range(n)]]}
    imp = await service.validate_session(db, t, (await _upload(db, t, sheets)).id)

    assert await _row_statuses(db, imp) == {"valid": n}
    assert imp.stats["sheets"]["Products"]["total"] == n
    stored = (
        await db.execute(
            sa.text("select parsed->'values'->>'title' from import_rows where row_number = :r"),
            {"r": n + 1},
        )
    ).scalar_one()
    assert stored == f"P{n - 1}"


async def test_row_level_security_alone_hides_another_shops_import(db, tenant_ctx):
    """Even a service call that names the wrong shop cannot reach a row the database hides."""
    mine = await _upload(db, tenant_ctx.tenant_id)
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Shop")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)

    # the caller claims to be MY shop while the connection is bound to the other one
    with pytest.raises(NotFoundError):
        await service.get(db, tenant_ctx.tenant_id, mine.id)


async def test_a_refused_row_has_no_parsed_value_not_a_json_null(db, tenant_ctx):
    """``parsed IS NULL`` is how "no usable verdict" is asked; a JSON null would slip past it."""
    t = tenant_ctx.tenant_id
    sheets = {"Products": [["Product ref", "Name"], ["ok", "Fine"], ["bad", ""]]}
    imp = await service.validate_session(db, t, (await _upload(db, t, sheets)).id)

    rows = await db.execute(
        sa.text(
            "select status, parsed is null from import_rows where session_id=:i order by row_number"
        ),
        {"i": imp.id},
    )
    assert rows.all() == [("valid", False), ("error", True)]

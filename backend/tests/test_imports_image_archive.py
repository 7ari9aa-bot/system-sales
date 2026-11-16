"""Pictures by .zip on a real database: upload, check by file name, apply, and clean up."""

# ruff: noqa: F811  (``api`` is a fixture imported from test_imports_http, then taken as a parameter)

from __future__ import annotations

import io
import zipfile

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.core.errors import ConflictError, ValidationError
from app.modules.imports import imagezip, service
from app.modules.imports.fields import SHEET_IMAGES
from app.modules.imports.models import ImportRow, ImportSession
from app.workers import import_runner
from app.workers.import_runner import run_batch
from tests.test_imports_http import api  # noqa: F401  (the fixture the route tests use)
from tests.test_imports_images import PNG, FakeStorage, _job, _session, _shop_with_sku

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


async def _checked_session(db, t, rows):
    s = await _session(db, t, status="analyzed")
    s.mapping = {SHEET_IMAGES: {"SKU": "sku", "Image": "file_name"}}
    db.add_all(
        ImportRow(
            tenant_id=t,
            session_id=s.id,
            sheet=SHEET_IMAGES,
            row_number=i + 2,
            raw={"SKU": sku, "Image": img},
            status="pending",
        )
        for i, (sku, img) in enumerate(rows)
    )
    await db.flush()
    return s


async def _verdict_codes(db, s):
    got = await db.execute(
        sa.text(
            "select row_number, status, errors from import_rows where session_id=:i order by 1"
        ),
        {"i": s.id},
    )
    return [(r.status, [e["code"] for e in r.errors]) for r in got.all()]


async def test_a_file_name_is_found_in_the_uploaded_archive_and_applied(
    db, tenant_ctx, monkeypatch
):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _checked_session(db, t, [("TEE-1", "Tee-Red.JPG")])

    await service.attach_image_archive(
        db, t, s.id, data=_zip({"photos/tee-red.jpg": JPEG}), storage=storage
    )
    await service.validate_session(db, t, s.id, storage=storage)
    assert await _verdict_codes(db, s) == [("valid", [])]

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (1, 0)
    assert (await db.execute(sa.text("select count(*) from product_images"))).scalar_one() == 1
    assert storage.fetched == []  # nothing was downloaded: it came out of the archive


async def test_a_name_missing_from_the_archive_is_refused_at_the_check_not_at_the_run(
    db, tenant_ctx
):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({})
    s = await _checked_session(db, t, [("TEE-1", "gone.jpg")])
    await service.attach_image_archive(db, t, s.id, data=_zip({"other.jpg": JPEG}), storage=storage)

    await service.validate_session(db, t, s.id, storage=storage)

    assert await _verdict_codes(db, s) == [("error", ["not_in_archive"])]


async def test_file_names_without_any_archive_say_so_instead_of_failing_obscurely(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    s = await _checked_session(db, t, [("TEE-1", "tee.jpg")])

    await service.validate_session(db, t, s.id, storage=FakeStorage({}))

    assert await _verdict_codes(db, s) == [("error", ["no_archive"])]


async def test_a_link_and_a_file_name_can_share_one_sheet(db, tenant_ctx, monkeypatch):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({"https://x.io/a.png": (PNG, "image/png")})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _checked_session(db, t, [("TEE-1", "https://x.io/a.png"), ("TEE-1", "b.jpg")])
    await service.attach_image_archive(db, t, s.id, data=_zip({"b.jpg": JPEG}), storage=storage)
    await service.validate_session(db, t, s.id, storage=storage)

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (2, 0)
    assert storage.fetched == ["https://x.io/a.png"]  # only the link was downloaded


async def test_a_name_two_pictures_share_is_refused_not_guessed(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({})
    s = await _checked_session(db, t, [("TEE-1", "x.jpg")])
    await service.attach_image_archive(
        db, t, s.id, data=_zip({"a/x.jpg": JPEG, "b/X.jpg": JPEG + b"1"}), storage=storage
    )

    await service.validate_session(db, t, s.id, storage=storage)

    assert await _verdict_codes(db, s) == [("error", ["ambiguous_name"])]


async def test_a_file_in_the_archive_that_is_not_a_picture_fails_its_row_at_the_run(
    db, tenant_ctx, monkeypatch
):
    """The name says .jpg; the bytes are a page. Only reading the bytes can know."""
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _checked_session(db, t, [("TEE-1", "fake.jpg"), ("TEE-1", "real.png")])
    await service.attach_image_archive(
        db, t, s.id, data=_zip({"fake.jpg": b"<html>hi</html>", "real.png": PNG}), storage=storage
    )
    await service.validate_session(db, t, s.id, storage=storage)

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (1, 1)
    assert (await db.execute(sa.text("select count(*) from product_images"))).scalar_one() == 1


async def test_a_hostile_archive_is_refused_as_a_whole_and_nothing_is_kept(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    storage = FakeStorage({})
    s = await _checked_session(db, t, [("TEE-1", "a.jpg")])

    with pytest.raises(ValidationError):
        await service.attach_image_archive(db, t, s.id, data=b"not a zip", storage=storage)

    assert storage.stored == []
    assert (await db.get(ImportSession, s.id)).file_key is None


async def test_a_valid_zip_that_is_hostile_as_a_whole_is_refused_and_nothing_is_kept(
    db, tenant_ctx, monkeypatch
):
    """The magic bytes pass; only reading the directory can tell this is too many files."""
    t = tenant_ctx.tenant_id
    monkeypatch.setattr(imagezip, "MAX_ENTRIES", 2)
    storage = FakeStorage({})
    s = await _checked_session(db, t, [("TEE-1", "a.jpg")])

    with pytest.raises(ValidationError, match="more than 2 files"):
        await service.attach_image_archive(
            db, t, s.id, data=_zip({f"{i}.jpg": JPEG for i in range(3)}), storage=storage
        )

    assert storage.stored == []
    assert (await db.get(ImportSession, s.id)).file_key is None


async def test_a_second_archive_replaces_the_first_and_removes_it(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    storage = FakeStorage({})
    s = await _checked_session(db, t, [("TEE-1", "a.jpg")])

    await service.attach_image_archive(db, t, s.id, data=_zip({"a.jpg": JPEG}), storage=storage)
    first = (await db.get(ImportSession, s.id)).file_key
    await service.attach_image_archive(db, t, s.id, data=_zip({"b.jpg": JPEG}), storage=storage)

    assert (await db.get(ImportSession, s.id)).file_key != first
    assert storage.deleted == [first]


async def test_uploading_an_archive_sends_a_checked_import_back_to_be_checked_again(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    storage = FakeStorage({})
    s = await _checked_session(db, t, [("TEE-1", "a.jpg")])
    s.status = "validated"
    await db.flush()

    imp = await service.attach_image_archive(
        db, t, s.id, data=_zip({"a.jpg": JPEG}), storage=storage
    )

    assert imp.status == "analyzed"


async def test_a_running_import_refuses_a_new_archive(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _checked_session(db, t, [("TEE-1", "a.jpg")])
    s.status = "running"
    await db.flush()

    with pytest.raises(ConflictError):
        await service.attach_image_archive(
            db, t, s.id, data=_zip({"a.jpg": JPEG}), storage=FakeStorage({})
        )


async def test_the_archive_is_removed_when_the_import_completes(db, tenant_ctx, monkeypatch):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _checked_session(db, t, [("TEE-1", "a.png")])
    await service.attach_image_archive(db, t, s.id, data=_zip({"a.png": PNG}), storage=storage)
    key = (await db.get(ImportSession, s.id)).file_key
    await service.validate_session(db, t, s.id, storage=storage)

    await run_batch(db, await _job(db, t, s))

    assert (await db.get(ImportSession, s.id)).status == "completed"
    assert (await db.get(ImportSession, s.id)).file_key is None
    assert key in storage.deleted
    assert import_runner._archive_cache == {}


async def test_the_archive_is_read_back_from_storage_once_per_batch_not_once_per_picture(
    db, tenant_ctx, monkeypatch
):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    names = [f"{i}.png" for i in range(6)]
    s = await _checked_session(db, t, [("TEE-1", n) for n in names])
    await service.attach_image_archive(
        db, t, s.id, data=_zip({n: PNG + bytes([i]) for i, n in enumerate(names)}), storage=storage
    )
    await service.validate_session(db, t, s.id, storage=storage)
    reads = []
    real = storage.read_object

    async def counted(key, **kw):
        reads.append(key)
        return await real(key, **kw)

    storage.read_object = counted
    import_runner._archive_cache.clear()

    result = await run_batch(db, await _job(db, t, s))

    assert result["applied"] == 6
    assert len(reads) == 1


def test_the_archive_limits_are_the_ones_the_route_and_the_middleware_agree_on():
    from app.core.middleware import MAX_IMPORT_ARCHIVE_BYTES

    assert MAX_IMPORT_ARCHIVE_BYTES == imagezip.MAX_ZIP_BYTES


async def test_the_archive_route_takes_the_zip_as_the_body_and_reports_what_it_holds(
    api,
    monkeypatch,
):
    from tests.test_imports_http import BOTH, XLSX, _upload, _xlsx

    storage = FakeStorage({})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    sheet = [["SKU", "Image"], ["TEE-1", "a.jpg"]]
    async with api(BOTH) as client:
        created = await _upload(
            client,
            _xlsx(
                {
                    "Variants": [["معرّف المنتج", "SKU", "السعر"], ["t", "TEE-1", "9"]],
                    "Images": sheet,
                }
            ),
        )
        assert created.status_code == 201
        sid = created.json()["id"]

        sent = await client.post(
            f"/api/v1/imports/sessions/{sid}/images.zip",
            content=_zip({"a.jpg": JPEG, "run.exe": b"MZ"}),
            headers={"content-type": "application/zip"},
        )

        assert sent.status_code == 201
        archive = sent.json()["stats"]["image_archive"]
        assert archive["files"] == 1
        assert archive["refused"] == {"run.exe": "not a picture file name"}
        assert len(storage.stored) == 1
        assert XLSX  # the workbook type the sibling tests upload with


async def test_the_archive_route_refuses_something_that_is_not_a_zip_with_a_clear_400(
    api,
    monkeypatch,
):
    from tests.test_imports_http import BOTH, _upload, _xlsx

    monkeypatch.setattr("app.core.storage.get_storage", lambda: FakeStorage({}))
    async with api(BOTH) as client:
        sid = (
            await _upload(
                client, _xlsx({"Variants": [["معرّف المنتج", "SKU", "السعر"], ["t", "T", "9"]]})
            )
        ).json()["id"]
        got = await client.post(
            f"/api/v1/imports/sessions/{sid}/images.zip", content=b"%PDF-1.4 hello"
        )
        assert got.status_code in (400, 422)


async def test_the_archive_route_accepts_a_body_past_the_workbook_limit_but_not_past_its_own(
    api,
    monkeypatch,
):
    """The 20 MB cap is for workbooks. A pictures archive may be bigger, up to its own ceiling."""
    from app.core.middleware import MAX_IMPORT_ARCHIVE_BYTES, MAX_IMPORT_UPLOAD_BYTES
    from tests.test_imports_http import BOTH

    assert MAX_IMPORT_ARCHIVE_BYTES > MAX_IMPORT_UPLOAD_BYTES
    sid = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setattr("app.core.storage.get_storage", lambda: FakeStorage({}))
    async with api(BOTH) as client:
        past_workbook = await client.post(
            f"/api/v1/imports/sessions/{sid}/images.zip",
            content=b"PK\x03\x04" + b"x" * (MAX_IMPORT_UPLOAD_BYTES + 1),
        )
        past_archive = await client.post(
            f"/api/v1/imports/sessions/{sid}/images.zip",
            content=b"x" * (MAX_IMPORT_ARCHIVE_BYTES + 1),
        )
    assert past_workbook.status_code != 413  # got as far as the route (no such session: 404)
    assert past_archive.status_code == 413


async def test_the_workbook_route_keeps_its_own_smaller_limit(api):
    from app.core.middleware import MAX_IMPORT_UPLOAD_BYTES
    from tests.test_imports_http import BOTH

    async with api(BOTH) as client:
        got = await client.post(
            "/api/v1/imports/sessions?filename=a.xlsx", content=b"x" * (MAX_IMPORT_UPLOAD_BYTES + 1)
        )
    assert got.status_code == 413


async def test_checking_the_file_keeps_what_the_archive_card_shows(db, tenant_ctx):
    """The card reads ``stats.image_archive``. Checking the file rewrote ``stats`` and dropped it."""
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({})
    s = await _checked_session(db, t, [("TEE-1", "a.jpg")])
    await service.attach_image_archive(
        db, t, s.id, data=_zip({"a.jpg": JPEG, "run.exe": b"MZ"}), storage=storage
    )

    await service.validate_session(db, t, s.id, storage=storage)

    kept = (await db.get(ImportSession, s.id)).stats["image_archive"]
    assert kept["files"] == 1
    assert kept["refused"] == {"run.exe": "not a picture file name"}

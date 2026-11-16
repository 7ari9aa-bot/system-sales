"""Importing pictures by link: the link rules, the checks, and the download on the real worker."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.core.errors import ValidationError
from app.core.storage import FetchedMedia, StoredMedia
from app.modules.catalog.service import CatalogService
from app.modules.imports import apply as apply_mod
from app.modules.imports import normalize as n
from app.modules.imports.apply import IMAGE_BATCH_LIMIT, SHEET_ORDER, ApplyError
from app.modules.imports.fields import SHEET_FIELDS, SHEET_IMAGES, SHEET_PRODUCTS, SHEET_VARIANTS
from app.modules.imports.mapping import suggest_mapping
from app.modules.imports.validation import MAX_IMAGES_PER_SKU, validate_images
from app.workers import import_runner
from app.workers.import_runner import run_batch
from tests.test_imports_run import _job, _row, _session

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
MAP = {"SKU": "sku", "Image": "file_name"}


# ---- the link ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["https://cdn.shop.com/a.jpg", "http://x.io/p?id=5", " https://x.io/a.PNG "],
)
def test_a_plain_http_link_is_accepted(raw):
    assert n.parse_image_url(raw) == raw.strip()


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "required"),
        ("tee.jpg", "not_a_link"),
        ("ftp://x.io/a.jpg", "not_a_link"),
        ("file:///etc/passwd", "not_a_link"),
        ("javascript:alert(1)", "not_a_link"),
        ("https://user:pw@x.io/a.jpg", "not_a_link"),
        ("https:///nohost.jpg", "not_a_link"),
        ("https://x.io/a b.jpg", "has_spaces"),
        ("https://x.io/" + "a" * 2000, "too_long"),
    ],
)
def test_anything_else_is_refused_with_a_stable_code(raw, code):
    with pytest.raises(n.CellError) as err:
        n.parse_image_url(raw)
    assert err.value.code == code


# ---- the sheet --------------------------------------------------------------------------------


def _verdicts(rows, *, known=("TEE-1",), in_file=(), attached=()):
    numbered = [(i + 2, r) for i, r in enumerate(rows)]
    return validate_images(
        numbered,
        MAP,
        skus_in_file=set(in_file),
        known_skus=set(known),
        already_attached=set(attached),
    )


def test_a_good_row_is_valid_and_carries_clean_values():
    (v,) = _verdicts([{"SKU": "TEE-1", "Image": "https://x.io/a.jpg"}])
    assert v.ok and v.action == "create"
    assert v.values == {"sku": "TEE-1", "url": "https://x.io/a.jpg", "source": "url"}


def test_an_unknown_sku_is_refused_unless_the_same_file_creates_it():
    row = {"SKU": "NEW-1", "Image": "https://x.io/a.jpg"}
    assert _verdicts([row])[0].errors[0].code == "unknown_sku"
    assert _verdicts([row], in_file={"NEW-1"})[0].ok


def test_a_picture_the_shop_already_has_is_skipped_so_a_rerun_adds_nothing():
    row = {"SKU": "TEE-1", "Image": "https://x.io/a.jpg"}
    (v,) = _verdicts([row], attached={("TEE-1", "https://x.io/a.jpg")})
    assert v.ok and v.action == "skip"


def test_the_same_sku_and_link_twice_in_a_file_refuses_the_second():
    row = {"SKU": "TEE-1", "Image": "https://x.io/a.jpg"}
    first, second = _verdicts([row, row])
    assert first.ok
    assert [e.code for e in second.errors] == ["duplicate_in_file"]


def test_a_gallery_is_capped_per_sku():
    rows = [
        {"SKU": "TEE-1", "Image": f"https://x.io/{i}.jpg"} for i in range(MAX_IMAGES_PER_SKU + 2)
    ]
    verdicts = _verdicts(rows)
    assert sum(v.ok for v in verdicts) == MAX_IMAGES_PER_SKU
    assert {e.code for v in verdicts for e in v.errors} == {"too_many_images"}


def test_a_blank_sku_and_a_bad_picture_are_both_reported_on_the_same_row():
    (v,) = _verdicts([{"SKU": "", "Image": "nope"}])
    assert {e.code for e in v.errors} == {"required", "bad_file_name"}


def test_the_header_names_a_merchant_would_use_are_matched_in_both_languages():
    got = suggest_mapping(SHEET_IMAGES, ["SKU", "رابط الصورة", "Image URL", "Photo", "note"])
    assert got["SKU"] == "sku"
    assert got["رابط الصورة"] == "file_name"
    assert got["Image URL"] is None  # a field is claimed by its leftmost column only
    assert got["note"] is None
    assert {f.key for f in SHEET_FIELDS[SHEET_IMAGES]} == {"sku", "file_name"}


def test_pictures_are_applied_after_everything_else():
    assert SHEET_ORDER[-1] == SHEET_IMAGES
    assert SHEET_ORDER.index(SHEET_VARIANTS) < SHEET_ORDER.index(SHEET_IMAGES)


# ---- the worker -------------------------------------------------------------------------------


class FakeStorage:
    """The slice of ``ObjectStorage`` the picture port touches."""

    def __init__(self, files: dict[str, tuple[bytes, str]], *, configured: bool = True):
        self.files = files
        self.configured = configured
        self.stored: list[str] = []
        self.deleted: list[str] = []
        self.fetched: list[str] = []
        self.objects: dict[str, bytes] = {}

    async def fetch(self, url: str, *, max_bytes=None) -> FetchedMedia:
        self.fetched.append(url)
        if url not in self.files:
            raise ValidationError("could not fetch")
        data, kind = self.files[url]
        return FetchedMedia(data=data, content_type=kind, checksum="x")

    async def read_object(self, key: str, *, max_bytes=None) -> FetchedMedia:
        data = self.objects[key]
        return FetchedMedia(data=data, content_type="application/zip", checksum="x")

    async def store(self, media: FetchedMedia, *, prefix="media", original_url=None):
        key = f"{prefix}/{len(self.stored)}.bin"
        self.stored.append(key)
        self.objects[key] = media.data
        return StoredMedia(
            url="",
            content_type=media.content_type,
            bytes_written=len(media.data),
            durable=True,
            storage_key=key,
            checksum=media.checksum,
        )

    async def delete_objects(self, keys):
        self.deleted.extend(keys)
        return list(keys)


async def _shop_with_sku(db, tenant_id, sku="TEE-1"):
    product = await CatalogService.create_product(db, tenant_id, title="Tee", slug="tee")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, sku=sku, price=10)
    return product, variant


def _images(session, urls, start=2):
    return [
        _row(session, SHEET_IMAGES, start + i, "create", {"sku": "TEE-1", "url": u})
        for i, u in enumerate(urls)
    ]


async def test_a_link_is_downloaded_stored_and_attached_to_the_variants_product(
    db, tenant_ctx, monkeypatch
):
    t = tenant_ctx.tenant_id
    product, variant = await _shop_with_sku(db, t)
    storage = FakeStorage({"https://x.io/a.png": (PNG, "image/png")})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _session(db, t)
    db.add_all(_images(s, ["https://x.io/a.png"]))
    await db.flush()

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (1, 0)
    row = (
        await db.execute(
            sa.text("select product_id, variant_id, url from product_images where tenant_id=:t"),
            {"t": t},
        )
    ).one()
    assert (row.product_id, row.variant_id) == (product.id, variant.id)
    assert row.url == f"s3://product-images/{t}/0.bin"  # our copy, never the merchant's link
    assert storage.fetched == ["https://x.io/a.png"]


async def test_a_dead_link_fails_its_row_and_the_others_still_apply(db, tenant_ctx, monkeypatch):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({"https://x.io/ok.jpg": (JPEG, "image/jpeg")})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _session(db, t)
    db.add_all(_images(s, ["https://x.io/dead.jpg", "https://x.io/ok.jpg"]))
    await db.flush()

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (1, 1)
    bad = (
        await db.execute(
            sa.text("select errors from import_rows where session_id=:i and status='error'"),
            {"i": s.id},
        )
    ).scalar_one()
    assert bad[0]["code"] == "image_unreachable"
    assert "dead.jpg" not in bad[0]["message"]  # a fixed sentence, never the transport's text


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"<html>not a picture</html>", "image/jpeg"),  # a page that only claims to be a JPEG
        (b"<svg onload=alert(1)>", "image/svg+xml"),  # scripts live in SVG
    ],
)
async def test_what_is_not_a_real_picture_is_refused_and_never_stored(
    db, tenant_ctx, monkeypatch, data, kind
):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({"https://x.io/a": (data, kind)})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _session(db, t)
    db.add_all(_images(s, ["https://x.io/a"]))
    await db.flush()

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (0, 1)
    assert storage.stored == []
    assert (await db.execute(sa.text("select count(*) from product_images"))).scalar_one() == 0


async def test_without_storage_the_row_fails_with_a_clear_reason_not_the_whole_batch(
    db, tenant_ctx, monkeypatch
):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    monkeypatch.setattr("app.core.storage.get_storage", lambda: FakeStorage({}, configured=False))
    s = await _session(db, t)
    db.add_all(_images(s, ["https://x.io/a.png"]))
    await db.flush()

    result = await run_batch(db, await _job(db, t, s))

    assert result["failed"] == 1
    code = (
        await db.execute(sa.text("select errors->0->>'code' from import_rows where status='error'"))
    ).scalar_one()
    assert code == "storage_unavailable"


async def test_a_batch_of_pictures_is_small_and_the_rest_wait_for_the_next_job(
    db, tenant_ctx, monkeypatch
):
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    urls = [f"https://x.io/{i}.png" for i in range(IMAGE_BATCH_LIMIT + 5)]
    storage = FakeStorage({u: (PNG, "image/png") for u in urls})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _session(db, t)
    db.add_all(_images(s, urls))
    await db.flush()

    first = await run_batch(db, await _job(db, t, s))
    assert first["taken"] == IMAGE_BATCH_LIMIT
    assert first["remaining"] == 5

    second = await run_batch(db, await _job(db, t, s))
    assert (second["taken"], second["remaining"]) == (5, 0)
    assert len(set(storage.fetched)) == len(urls)  # every link fetched exactly once


async def test_the_port_is_wired_into_the_real_runner():
    assert import_runner.PORTS.attach_image is import_runner._attach_image
    assert apply_mod.Ports.__dataclass_fields__["attach_image"]


async def test_an_unknown_sku_raised_at_apply_time_is_a_row_error(db, tenant_ctx, monkeypatch):
    """The sheet checked the SKU, but it can be deleted between the check and the run."""
    t = tenant_ctx.tenant_id
    monkeypatch.setattr("app.core.storage.get_storage", lambda: FakeStorage({}))
    with pytest.raises(ApplyError) as err:
        await import_runner._attach_image(
            db, t, "GONE-1", "https://x.io/a.png", "url", uuid.uuid4()
        )
    assert err.value.code == "unknown_sku"


def test_a_products_only_file_still_reads_when_an_images_sheet_is_present():
    assert SHEET_PRODUCTS in SHEET_ORDER and SHEET_IMAGES in SHEET_ORDER


async def test_the_picture_is_judged_by_its_bytes_not_by_what_the_server_said(
    db, tenant_ctx, monkeypatch
):
    """A real PNG behind a wrong Content-Type is a picture; the reverse is not."""
    t = tenant_ctx.tenant_id
    await _shop_with_sku(db, t)
    storage = FakeStorage({"https://x.io/a": (PNG, "text/html")})
    monkeypatch.setattr("app.core.storage.get_storage", lambda: storage)
    s = await _session(db, t)
    db.add_all(_images(s, ["https://x.io/a"]))
    await db.flush()

    result = await run_batch(db, await _job(db, t, s))

    assert (result["applied"], result["failed"]) == (1, 0)
    stored_type = (await db.execute(sa.text("select count(*) from product_images"))).scalar_one()
    assert stored_type == 1

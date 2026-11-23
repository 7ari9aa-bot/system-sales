"""صور في ملف مضغوط: اسم الملف هو الـSKU.

التاجر بيسمّي الصور بأسماء الأصناف (TEE-BK-M.jpg، TEE-BK-M-2.jpg للزاوية التانية). الرفع بيربط
كل صورة بصنفها، واللي مالوش صنف أو مش صورة حقيقية بيرجع باسمه في التقرير بدل ما يختفي.
"""

from __future__ import annotations

import io
import zipfile

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

import app.core.storage as storage_module
from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.core.storage import StoredMedia
from app.main import create_app
from app.modules.identity.deps import get_db, get_tenant_ctx
from app.modules.imports.image_zip import plan_images, sku_candidates, sku_from_name
from tests._pos_helpers import ctx_for

pytestmark = pytest.mark.asyncio

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeStorage:
    """Stand-in for the bucket: keeps what was written and says it is durable."""

    configured = True

    def __init__(self):
        self.written: list[str] = []

    async def store(self, media, *, prefix, original_url=None):
        key = f"{prefix}/{len(self.written)}.png"
        self.written.append(key)
        return StoredMedia(
            url=f"s3://{key}",
            content_type=media.content_type,
            bytes_written=len(media.data),
            durable=True,
            storage_key=key,
        )

    async def delete_objects(self, keys):
        self.written = [k for k in self.written if k not in keys]


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _app(ctx):
    app = create_app()
    app.user_middleware = [
        m for m in app.user_middleware if m.cls not in {IdempotencyMiddleware, RateLimitMiddleware}
    ]
    app.middleware_stack = None

    async def _session():
        yield ctx.session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _session
    return app


async def _post_zip(ctx, payload: bytes):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.post("/api/v1/imports/images/zip?filename=images.zip", content=payload)


async def _variant(db, tenant_ctx, sku: str):
    from app.modules.catalog.service import CatalogService

    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title=f"منتج {sku}", slug=f"p-{sku.lower()}"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, sku=sku, title="افتراضي", price=100
    )
    await db.flush()
    return product.id, variant.id


# ------------------------------------------------------------------------------- file names


async def test_the_file_name_is_the_sku_however_the_camera_named_it(db, tenant_ctx):
    assert sku_from_name("TEE-BK-M.jpg") == "TEE-BK-M"
    assert sku_from_name("مجلد/فرعي/تيشيرت-أسود.png") == "تيشيرت-أسود"
    assert sku_from_name("notes.txt") == ""
    # الاسم بالظبط الأول: TEE-1 ممكن يكون SKU حقيقي.
    assert sku_candidates("TEE-1.jpg") == ["TEE-1", "TEE"]
    assert sku_candidates("TEE-BK-M-2.jpg") == ["TEE-BK-M-2", "TEE-BK-M"]
    assert sku_candidates("TEE-BK-M (1).JPG") == ["TEE-BK-M (1)", "TEE-BK-M"]


async def test_one_sku_collects_its_pictures_in_order(db, tenant_ctx):
    plan = plan_images(["B.jpg", "a.png", "B-2.jpg", "A-3.jpg", "readme.pdf"], known={"A", "B"})

    assert list(plan) == ["B", "A"]
    assert plan["B"] == ["B.jpg", "B-2.jpg"]
    assert plan["A"] == ["a.png", "A-3.jpg"]  # الحالة مش بتفرق في اسم الصنف


async def test_an_exact_sku_wins_over_the_base_name(db, tenant_ctx):
    # محل عنده TEE-1 و TEE: صورة TEE-1.jpg تروح لـTEE-1 مش لـTEE.
    plan = plan_images(["TEE-1.jpg"], known={"TEE", "TEE-1"})
    assert plan == {"TEE-1": ["TEE-1.jpg"]}


# ---------------------------------------------------------------------------------- upload


async def test_pictures_are_attached_to_the_variant_that_owns_the_sku(db, tenant_ctx, monkeypatch):
    owner = await ctx_for(db, tenant_ctx, "owner")
    product_id, variant_id = await _variant(db, tenant_ctx, "TEE-BK-M")
    await _variant(db, tenant_ctx, "JNS-32")
    fake = FakeStorage()
    monkeypatch.setattr(storage_module, "get_storage", lambda: fake)

    files = {"TEE-BK-M.png": PNG, "TEE-BK-M-2.png": PNG, "JNS-32.png": PNG}
    r = await _post_zip(owner, _zip(files))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stats"]["attached"] == 3
    assert {m["sku"] for m in body["matched"]} == {"TEE-BK-M", "JNS-32"}
    assert len(fake.written) == 3

    rows = (
        await db.execute(
            sa.text(
                "select variant_id, count(*) from product_images "
                "where tenant_id = :t and product_id = :p group by variant_id"
            ),
            {"t": tenant_ctx.tenant_id, "p": product_id},
        )
    ).all()
    assert {vid: count for vid, count in rows} == {variant_id: 2}


async def test_a_picture_for_a_sku_the_shop_does_not_have_is_reported_by_name(
    db, tenant_ctx, monkeypatch
):
    owner = await ctx_for(db, tenant_ctx, "owner")
    await _variant(db, tenant_ctx, "TEE-BK-M")
    monkeypatch.setattr(storage_module, "get_storage", lambda: FakeStorage())

    r = await _post_zip(
        owner, _zip({"TEE-BK-M.png": PNG, "GHOST-1.png": PNG, "readme.txt": b"hello"})
    )

    body = r.json()
    assert body["stats"]["attached"] == 1
    assert body["unknown_skus"] == ["GHOST-1"]
    assert body["not_pictures"] == ["readme.txt"]


async def test_a_file_that_is_not_really_a_picture_is_refused(db, tenant_ctx, monkeypatch):
    owner = await ctx_for(db, tenant_ctx, "owner")
    await _variant(db, tenant_ctx, "TEE-BK-M")
    monkeypatch.setattr(storage_module, "get_storage", lambda: FakeStorage())

    # امتداد .png على محتوى مش صورة: الامتداد لوحده مش دليل.
    r = await _post_zip(owner, _zip({"TEE-BK-M.png": b"<html>not an image</html>"}))

    body = r.json()
    assert body["stats"]["attached"] == 0
    assert body["failed"][0]["reason"] == "الملف مش صورة حقيقية"


async def test_more_than_ten_pictures_for_one_sku_is_capped_and_the_rest_is_named(
    db, tenant_ctx, monkeypatch
):
    owner = await ctx_for(db, tenant_ctx, "owner")
    await _variant(db, tenant_ctx, "TEE-BK-M")
    fake = FakeStorage()
    monkeypatch.setattr(storage_module, "get_storage", lambda: fake)
    files = {f"TEE-BK-M-{i}.png": PNG for i in range(1, 13)}

    r = await _post_zip(owner, _zip(files))

    body = r.json()
    assert body["stats"]["attached"] == 10
    assert len(body["over_limit"]) == 2


async def test_a_broken_archive_or_missing_storage_says_so(db, tenant_ctx, monkeypatch):
    owner = await ctx_for(db, tenant_ctx, "owner")

    broken = await _post_zip(owner, b"not a zip at all")
    assert broken.status_code == 400

    class NoStorage:
        configured = False

    monkeypatch.setattr(storage_module, "get_storage", lambda: NoStorage())
    unconfigured = await _post_zip(owner, _zip({"TEE-BK-M.png": PNG}))
    assert unconfigured.status_code == 409

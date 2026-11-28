"""There is ONE way to import: the Import Center.

The old door (``POST /imports/products``) took a CSV where one row was one product with a single
default variant, under rules of its own — no variants sheet, no opening stock, no season or
fabric. It is closed for the merchant behind a data key, and the code is kept. Even when the key
is turned on, the file is not applied by the old rules: it becomes an import session and is
checked by the same validation every other upload goes through.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.applications.apparel.modules.catalog.external.csv_import import CSVImportService
from app.platform.identity.deps import get_db, get_tenant_ctx
from app.platform.settings.service import SettingsService
from tests._pos_helpers import ctx_for

pytestmark = pytest.mark.asyncio

CSV = "title,price,sku\nقميص كتان,250.00,SHIRT-L\n"


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


async def _call(ctx, path, body):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.post(path, json=body)


async def _open_door(db, tenant_ctx, user_id):
    await SettingsService(db, tenant_ctx.tenant_id).set(
        "imports.legacy_csv_endpoint", True, user_id=user_id
    )
    await db.flush()


async def test_the_old_door_is_closed_by_default_and_says_where_to_go(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")

    r = await _call(owner, "/api/v1/imports/products", {"csv": CSV})

    assert r.status_code == 404, r.text
    assert "مركز الاستيراد" in r.text
    assert "/inventory/import" in r.text


async def test_a_closed_door_creates_nothing(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")

    await _call(owner, "/api/v1/imports/products", {"csv": CSV})

    import sqlalchemy as sa

    sessions = (
        await db.execute(
            sa.text("select count(*) from import_sessions where tenant_id = :t"),
            {"t": tenant_ctx.tenant_id},
        )
    ).scalar_one()
    assert sessions == 0
    products = (
        await db.execute(
            sa.text("select count(*) from products where tenant_id = :t"),
            {"t": tenant_ctx.tenant_id},
        )
    ).scalar_one()
    assert products == 0


async def test_the_open_door_hands_the_file_to_the_import_center(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    await _open_door(db, tenant_ctx, owner.user.id)

    r = await _call(owner, "/api/v1/imports/products", {"csv": CSV})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in {"validated", "analyzed"}
    assert body["import_center"] == "/inventory/import"
    assert body["stats"]["rows"]  # the rows were read into the same session table


async def test_both_doors_judge_a_file_the_same_way(db, tenant_ctx):
    """The proof of one pipeline: the same CSV gets the same verdict from either door."""
    owner = await ctx_for(db, tenant_ctx, "owner")
    await _open_door(db, tenant_ctx, owner.user.id)
    # A product row with no title is refused by the Import Center's own validation.
    bad = "title,price\n,250\n"

    legacy = await _call(owner, "/api/v1/imports/products", {"csv": bad})
    assert legacy.status_code == 200, legacy.text
    from_old_door = await _verdicts(db, tenant_ctx, legacy.json()["session_id"])

    # The same bytes dropped in the Import Center itself.
    async with AsyncClient(transport=ASGITransport(app=_app(owner)), base_url="http://t") as c:
        upload = await c.post(
            "/api/v1/imports/sessions?filename=products.csv", content=bad.encode()
        )
    assert upload.status_code == 201, upload.text
    center_id = upload.json()["id"]
    async with AsyncClient(transport=ASGITransport(app=_app(owner)), base_url="http://t") as c:
        await c.post(f"/api/v1/imports/sessions/{center_id}/validate")
    from_center = await _verdicts(db, tenant_ctx, center_id)

    assert from_old_door == from_center
    assert from_old_door["invalid"] == 1, from_old_door


async def _verdicts(db, tenant_ctx, session_id) -> dict:
    """How many rows of that session are valid and how many are not."""
    import sqlalchemy as sa

    rows = (
        await db.execute(
            sa.text(
                "select status, count(*) from import_rows "
                "where session_id = :s and tenant_id = :t group by status"
            ),
            {"s": session_id, "t": tenant_ctx.tenant_id},
        )
    ).all()
    counts = {status: count for status, count in rows}
    invalid = sum(count for status, count in counts.items() if status not in {"valid", "pending"})
    return {"invalid": invalid, "valid": counts.get("valid", 0)}


async def test_the_old_implementation_is_still_in_the_code(db, tenant_ctx):
    """Hidden, never deleted: the service that used to apply these files is still callable."""
    assert callable(CSVImportService.import_products)

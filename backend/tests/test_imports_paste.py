"""Pasting rows from Excel: one import, one set of rules, no file in between.

The merchant copies a block of cells — a header line and a line per variant — and the paste
becomes an ordinary import session. Nothing here validates on its own: the rows land in the same
tables an uploaded workbook lands in, so the mapping screen, the row verdicts and the apply are
the ones the Import Center already runs.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.core.errors import ValidationError
from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.identity.deps import get_db, get_tenant_ctx
from app.modules.imports.fields import SHEET_PRODUCTS, SHEET_STOCK, SHEET_VARIANTS
from app.modules.imports.paste import parse_pasted
from tests._pos_helpers import ctx_for

pytestmark = pytest.mark.asyncio

# ما يطلع من نسخ خلايا Excel: عناوين عربية وسطر لكل تركيبة.
PASTE = (
    "اسم المنتج\tالتصنيف\tالموسم\tاللون\tالمقاس\tالسعر\tSKU\tالرصيد\n"
    "تيشيرت قطن\tتيشيرتات\tSS26\tأسود\tM\t250\tTEE-BK-M\t4\n"
    "تيشيرت قطن\tتيشيرتات\tSS26\tأسود\tL\t250\tTEE-BK-L\t6\n"
    "بنطلون جينز\tبناطيل\tSS26\tكحلي\t32\t400\tJNS-32\t3\n"
)


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


async def _post(ctx, path, body):
    async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
        return await c.post(path, json=body)


# --------------------------------------------------------------------------------- the parser


async def test_a_variant_paste_becomes_products_and_variants(db, tenant_ctx):
    sheets = parse_pasted(PASTE)

    # الرصيد موجود في اللصق، فورقة رصيد أول المدة بتتكوّن معاهم.
    assert set(sheets) == {SHEET_PRODUCTS, SHEET_VARIANTS, SHEET_STOCK}
    # سطر واحد لكل منتج، مش سطر لكل تركيبة.
    assert [row["اسم المنتج"] for row in sheets[SHEET_PRODUCTS]] == ["تيشيرت قطن", "بنطلون جينز"]
    assert len(sheets[SHEET_VARIANTS]) == 3


async def test_two_hundred_rows_are_read_without_losing_one(db, tenant_ctx):
    lines = ["اسم المنتج\tالمقاس\tالسعر\tSKU"]
    lines += [f"منتج {i}\tM\t100\tSKU-{i}" for i in range(200)]

    sheets = parse_pasted("\n".join(lines))

    assert len(sheets[SHEET_VARIANTS]) == 200
    assert len(sheets[SHEET_PRODUCTS]) == 200


async def test_a_name_only_paste_is_a_product_list_not_a_variant_list(db, tenant_ctx):
    sheets = parse_pasted("اسم المنتج,الماركة\nقميص,نايك\n")

    assert set(sheets) == {SHEET_PRODUCTS}
    assert sheets[SHEET_PRODUCTS][0]["الماركة"] == "نايك"


async def test_a_paste_without_a_header_is_refused_in_the_merchant_s_words(db, tenant_ctx):
    with pytest.raises(ValidationError) as only_one_line:
        parse_pasted("تيشيرت قطن\t250")
    assert "سطر العناوين" in only_one_line.value.message

    with pytest.raises(ValidationError) as nothing_understood:
        parse_pasted("عمود\tعمود تاني\n1\t2\n")
    assert "مفيش عمود مفهوم" in nothing_understood.value.message


async def test_semicolons_and_commas_both_split(db, tenant_ctx):
    assert parse_pasted("اسم المنتج;السعر\nقميص;250\n")[SHEET_PRODUCTS]
    assert parse_pasted("اسم المنتج,السعر\nقميص,250\n")[SHEET_PRODUCTS]


# ------------------------------------------------------------------------------- the endpoint


async def test_the_paste_creates_an_import_session_with_both_sheets(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")

    r = await _post(owner, "/api/v1/imports/sessions/paste", {"text": PASTE})

    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "analyzed"
    assert out["stats"]["rows"] == {SHEET_PRODUCTS: 2, SHEET_VARIANTS: 3, SHEET_STOCK: 3}

    mapping = (
        await db.execute(
            sa.text("select mapping from import_sessions where id = :i"),
            {"i": out["id"]},
        )
    ).scalar_one()
    # الأعمدة اتربطت لوحدها، فالتاجر يوصل للمراجعة على طول.
    assert "title" in mapping[SHEET_PRODUCTS].values()
    assert {"sku", "price"} <= set(mapping[SHEET_VARIANTS].values())


async def test_the_pasted_session_is_checked_by_the_same_validation(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")
    created = await _post(owner, "/api/v1/imports/sessions/paste", {"text": PASTE})
    session_id = created.json()["id"]

    async with AsyncClient(
        transport=ASGITransport(app=_app(owner)), base_url="http://t"
    ) as c:
        checked = await c.post(f"/api/v1/imports/sessions/{session_id}/validate")

    assert checked.status_code == 200, checked.text
    assert checked.json()["status"] == "validated"

    rows = (
        await db.execute(
            sa.text(
                "select sheet, status, count(*) from import_rows "
                "where session_id = :i group by sheet, status"
            ),
            {"i": session_id},
        )
    ).all()
    by_sheet = {(sheet, status): count for sheet, status, count in rows}
    assert by_sheet[(SHEET_PRODUCTS, "valid")] == 2
    assert by_sheet[(SHEET_VARIANTS, "valid")] == 3
    # رصيد أول المدة بيتراجع بقواعد الاستيراد نفسها: صف لكل سطر، ومهما كان حكمه فهو حكم الاستيراد.
    stock_rows = sum(count for (sheet, _), count in by_sheet.items() if sheet == SHEET_STOCK)
    assert stock_rows == 3


async def test_an_empty_paste_is_refused_before_a_session_exists(db, tenant_ctx):
    owner = await ctx_for(db, tenant_ctx, "owner")

    r = await _post(owner, "/api/v1/imports/sessions/paste", {"text": "   "})

    assert r.status_code == 400, r.text
    sessions = (
        await db.execute(
            sa.text("select count(*) from import_sessions where tenant_id = :t"),
            {"t": tenant_ctx.tenant_id},
        )
    ).scalar_one()
    assert sessions == 0

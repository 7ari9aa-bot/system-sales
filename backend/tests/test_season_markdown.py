"""Season markdown: preview shows every size's old and new price, apply writes exactly that.

Money is exact: the percent is text, the maths is Decimal, rounding is half up to the cent. A float
would give 19.99 at 15% as 16.99149999... and 1.005 at 50% as 0.50 instead of 0.50 (and 10.05 at 50%
as 5.02 instead of 5.03).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.season_markdown import (
    SeasonMarkdownService,
    marked_down,
    parse_percent,
)
from app.modules.catalog.apparel.matrix import COLOR_AXIS, SIZE_AXIS
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, ValidationError
from app.modules.purchasing.models import VariantCost

pytestmark = pytest.mark.asyncio


async def _item(db, tid, *, title="قميص", season="SS26", size="M", price="100.00", cost=None):
    prod = await CatalogService.create_product(
        db, tid, title=title, slug=f"p-{uuid.uuid4().hex[:8]}"
    )
    prod.season = season
    v = await CatalogService.add_variant(
        db, tid, prod.id, price=price, option_values={SIZE_AXIS: size, COLOR_AXIS: "أسود"}
    )
    if cost is not None:
        db.add(VariantCost(tenant_id=tid, variant_id=v.id, avg_cost=Decimal(str(cost))))
    await db.flush()
    return prod, v


async def _price(db, v) -> Decimal:
    await db.refresh(v)
    return Decimal(v.price)


async def _prev(db, tid, season="SS26", percent="20", **kw):
    return await SeasonMarkdownService.preview(db, tid, season=season, percent=percent, **kw)


async def _apply(db, tid, prev, *, season="SS26", percent="20", **kw):
    return await SeasonMarkdownService.apply(
        db, tid, None, season=season, percent=percent, token=prev["token"], **kw
    )


# ── the percent and the maths ─────────────────────────────────────────────────────────────────


def test_percent_accepts_exact_text_within_bounds() -> None:
    assert parse_percent("15") == Decimal("15")
    assert parse_percent(" 12.5 ") == Decimal("12.5")
    assert parse_percent("0.01") == Decimal("0.01")
    assert parse_percent("90") == Decimal("90")
    assert parse_percent(15) == Decimal("15")  # an int is exact


@pytest.mark.parametrize(
    "bad", ["0", "0.00", "-5", "90.01", "91", "abc", "", "NaN", "Infinity", "1.005"]
)
def test_percent_refuses_out_of_range_or_odd_text(bad) -> None:
    with pytest.raises(ValidationError):
        parse_percent(bad)


@pytest.mark.parametrize("bad", [15.0, 12.5, None, True])
def test_percent_refuses_a_float_or_nothing(bad) -> None:
    with pytest.raises(ValidationError):
        parse_percent(bad)


def test_the_maths_is_exact_where_a_float_is_not() -> None:
    assert marked_down(Decimal("19.99"), Decimal("15")) == Decimal("16.99")  # 16.9915
    assert marked_down(Decimal("10.05"), Decimal("50")) == Decimal("5.03")  # 5.025 half up
    assert marked_down(Decimal("1.00"), Decimal("12.5")) == Decimal("0.88")  # 0.875 half up
    assert marked_down(Decimal("100"), Decimal("33.33")) == Decimal("66.67")
    assert marked_down(Decimal("0.01"), Decimal("90")) == Decimal("0.00")


# ── preview ───────────────────────────────────────────────────────────────────────────────────


async def test_preview_shows_old_and_new_price_and_changes_nothing(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    _, v = await _item(db, tid, price="100.00", cost="60")
    prev = await _prev(db, tid, percent="20")
    row = prev["rows"][0]
    assert (row["old_price"], row["new_price"]) == ("100.00", "80.00")
    assert (row["model"], row["size"], row["colour"]) == ("قميص", "M", "أسود")
    assert row["unit_cost"] == "60.00" and row["cost_known"] is True and row["below_cost"] is False
    assert prev["percent"] == "20" and prev["season"] == "SS26"
    assert await _price(db, v) == Decimal("100.00")  # nothing written


async def test_preview_counts_variants_and_products(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    prod, _ = await _item(db, tid, size="S")
    await CatalogService.add_variant(
        db, tid, prod.id, price="50", option_values={SIZE_AXIS: "L", COLOR_AXIS: "أسود"}
    )
    await _item(db, tid, title="جاكت", size="M")
    t = (await _prev(db, tid))["totals"]
    assert (t["variants"], t["products"]) == (3, 2)


async def test_below_cost_is_flagged_and_unknown_cost_is_never_below_cost(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _item(db, tid, size="S", price="100", cost="85")  # 80 < 85
    await _item(db, tid, size="M", price="100", cost="80")  # 80 == 80: not below
    await _item(db, tid, size="L", price="100")  # no cost known
    prev = await _prev(db, tid, percent="20")
    by = {r["size"]: r for r in prev["rows"]}
    assert by["S"]["below_cost"] is True
    assert by["M"]["below_cost"] is False
    assert by["L"]["below_cost"] is False and by["L"]["cost_known"] is False
    assert prev["totals"]["below_cost"] == 1 and prev["totals"]["without_cost"] == 1


async def test_a_price_never_falls_to_zero(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    _, v = await _item(db, tid, price="0.02")
    prev = await _prev(db, tid, percent="90")
    row = prev["rows"][0]
    assert row["new_price"] == "0.01" and row["at_floor"] is True
    assert prev["totals"]["at_floor"] == 1
    await _apply(db, tid, prev, percent="90")
    assert await _price(db, v) == Decimal("0.01")


async def test_season_matching_ignores_case_and_outer_spaces(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _item(db, tid, season="SS26", size="S")
    await _item(db, tid, season=" ss26 ", size="M")
    assert len((await _prev(db, tid, season="  Ss26"))["rows"]) == 2


async def test_a_brand_narrows_the_set(db, tenant_ctx) -> None:
    from app.modules.catalog.models import Brand

    tid = tenant_ctx.tenant_id
    nile = Brand(tenant_id=tid, name="نيل")
    db.add(nile)
    await db.flush()
    p1, _ = await _item(db, tid, title="قميص نيل", size="S")
    await _item(db, tid, title="قميص تاني", size="M")
    p1.brand_id = nile.id
    await db.flush()
    rows = (await _prev(db, tid, brand_id=nile.id))["rows"]
    assert [r["model"] for r in rows] == ["قميص نيل"]


async def test_an_inactive_size_is_not_included(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    _, v = await _item(db, tid, size="S")
    await _item(db, tid, size="M")
    v.is_active = False
    await db.flush()
    assert [r["size"] for r in (await _prev(db, tid))["rows"]] == ["M"]


async def test_a_season_needs_a_name(db, tenant_ctx) -> None:
    with pytest.raises(ValidationError):
        await _prev(db, tenant_ctx.tenant_id, season="   ")


# ── apply ─────────────────────────────────────────────────────────────────────────────────────


async def test_apply_writes_exactly_what_the_preview_showed(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    _, a = await _item(db, tid, size="S", price="19.99")
    _, b = await _item(db, tid, size="M", price="10.05")
    prev = await _prev(db, tid, percent="15")
    shown = {r["variant_id"]: Decimal(r["new_price"]) for r in prev["rows"]}
    out = await _apply(db, tid, prev, percent="15")
    assert out["applied"] == 2 and out["percent"] == "15"
    assert await _price(db, a) == shown[str(a.id)] == Decimal("16.99")
    assert await _price(db, b) == shown[str(b.id)] == Decimal("8.54")  # 8.5425


async def test_other_seasons_and_other_shops_are_untouched(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    _, mine = await _item(db, tid, season="SS26", size="S")
    _, other_season = await _item(db, tid, season="AW26", size="M")
    _, no_season = await _item(db, tid, season=None, size="L")
    prev = await _prev(db, tid)
    await _apply(db, tid, prev)
    assert await _price(db, mine) == Decimal("80.00")
    assert await _price(db, other_season) == Decimal("100.00")
    assert await _price(db, no_season) == Decimal("100.00")
    # another shop asking for the same season sees nothing
    assert (await _prev(db, uuid.uuid4()))["rows"] == []


async def test_a_token_from_another_shop_or_percent_or_season_is_refused(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    _, v = await _item(db, tid)
    prev = await _prev(db, tid, percent="20")
    with pytest.raises(ConflictError):
        await _apply(db, tid, prev, percent="25")  # a different percent
    with pytest.raises(ConflictError):
        await SeasonMarkdownService.apply(
            db, tid, None, season="SS26", percent="20", token="0" * 64
        )
    with pytest.raises(ConflictError):
        await SeasonMarkdownService.apply(db, tid, None, season="SS26", percent="20", token="")
    assert await _price(db, v) == Decimal("100.00")


async def test_a_changed_price_between_preview_and_apply_is_a_409_and_writes_nothing(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    _, a = await _item(db, tid, size="S")
    _, b = await _item(db, tid, size="M")
    prev = await _prev(db, tid)
    b.price = Decimal("120.00")  # someone repriced a size in between
    await db.flush()
    with pytest.raises(ConflictError):
        await _apply(db, tid, prev)
    assert await _price(db, a) == Decimal("100.00")
    assert await _price(db, b) == Decimal("120.00")


async def test_a_size_added_between_preview_and_apply_is_a_409(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _item(db, tid, size="S")
    prev = await _prev(db, tid)
    await _item(db, tid, size="L")
    with pytest.raises(ConflictError):
        await _apply(db, tid, prev)


async def test_applying_twice_the_second_time_is_a_409_not_a_double_markdown(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    _, v = await _item(db, tid)
    prev = await _prev(db, tid)
    await _apply(db, tid, prev)
    with pytest.raises(ConflictError):
        await _apply(db, tid, prev)
    assert await _price(db, v) == Decimal("80.00")  # 100 -> 80 once, never 64


async def test_nothing_matching_is_a_409_not_a_silent_zero(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    prev = await _prev(db, tid, season="NOPE")
    assert prev["rows"] == [] and prev["totals"]["variants"] == 0
    with pytest.raises(ConflictError):
        await _apply(db, tid, prev, season="NOPE")


async def test_the_markdown_is_all_or_nothing(db, tenant_ctx, monkeypatch) -> None:
    """A failure part way leaves every price as it was (the caller's transaction rolls back)."""
    tid = tenant_ctx.tenant_id
    _, a = await _item(db, tid, size="S")
    _, b = await _item(db, tid, size="M")
    prev = await _prev(db, tid)

    async def boom(*_a, **_k):
        raise RuntimeError("audit down")

    monkeypatch.setattr("app.core.season_markdown.write_audit_row", boom)
    sp = await db.begin_nested()
    with pytest.raises(RuntimeError):
        await _apply(db, tid, prev)
    await sp.rollback()
    assert await _price(db, a) == Decimal("100.00")
    assert await _price(db, b) == Decimal("100.00")


async def test_one_audit_row_says_who_what_and_how_many(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _item(db, tid, size="S")
    await _item(db, tid, size="M")
    prev = await _prev(db, tid, percent="12.5")
    me = uuid.UUID(str(tenant_ctx.user.id))
    await SeasonMarkdownService.apply(
        db, tid, me, season="SS26", percent="12.5", token=prev["token"]
    )
    rows = (
        await db.execute(
            text(
                "select actor_user_id, resource_type, resource_id, before, after from audit_logs"
                " where tenant_id = :t and action = 'catalog.season_markdown'"
            ),
            {"t": tid},
        )
    ).all()
    assert len(rows) == 1
    actor, kind, rid, before, after = rows[0]
    assert (actor, kind, rid) == (me, "season", "SS26")
    assert after["percent"] == "12.5" and after["variants"] == 2 and after["season"] == "SS26"
    assert len(before["prices"]) == 2 and set(before["prices"].values()) == {"100.00"}


async def test_no_audit_row_when_nothing_was_applied(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _item(db, tid)
    prev = await _prev(db, tid)
    with pytest.raises(ConflictError):
        await _apply(db, tid, prev, percent="21")
    n = (
        await db.execute(
            text(
                "select count(*) from audit_logs where tenant_id = :t"
                " and action = 'catalog.season_markdown'"
            ),
            {"t": tid},
        )
    ).scalar()
    assert n == 0


# ── what the token binds ──────────────────────────────────────────────────────────────────────


def test_the_token_changes_with_every_part_it_is_meant_to_bind() -> None:
    """Shop, season, percent and every (variant, old, new) price: change one and it differs."""
    from app.core.season_markdown import _sign

    t1, t2 = uuid.uuid4(), uuid.uuid4()
    lines = [("v1", "100.00", "80.00"), ("v2", "50.00", "40.00")]
    base = _sign(t1, "ss26", Decimal("20"), lines)
    assert base == _sign(t1, "ss26", Decimal("20"), list(lines))  # stable
    assert base != _sign(t2, "ss26", Decimal("20"), lines)  # another shop
    assert base != _sign(t1, "aw26", Decimal("20"), lines)  # another season
    assert base != _sign(t1, "ss26", Decimal("25"), lines)  # another percent
    assert base != _sign(t1, "ss26", Decimal("20"), [("v1", "101.00", "80.00"), lines[1]])  # old
    assert base != _sign(t1, "ss26", Decimal("20"), [("v1", "100.00", "79.00"), lines[1]])  # new
    assert base != _sign(t1, "ss26", Decimal("20"), [lines[0]])  # a size missing


async def test_the_token_does_not_depend_on_how_the_season_was_typed(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _item(db, tid)
    a = await _prev(db, tid, season="SS26")
    b = await _prev(db, tid, season="  ss26 ")
    assert a["token"] == b["token"]
    await SeasonMarkdownService.apply(
        db, tid, None, season="ss26", percent="20", token=a["token"]
    )  # a token from "SS26" opens an apply typed "ss26"


async def test_a_token_for_one_price_set_cannot_be_used_after_the_old_price_moved_back(
    db, tenant_ctx
) -> None:
    """Same new price, different old price: still a different set, so a 409."""
    tid = tenant_ctx.tenant_id
    _, v = await _item(db, tid, price="100.00")
    prev = await _prev(db, tid, percent="20")  # 100 -> 80
    v.price = Decimal("200.00")
    await db.flush()
    other = await _prev(db, tid, percent="60")  # 200 -> 80: the same new price, other old price
    assert other["rows"][0]["new_price"] == prev["rows"][0]["new_price"] == "80.00"
    assert other["token"] != prev["token"]


async def test_the_token_built_from_a_real_plan_follows_old_and_new_prices(db, tenant_ctx) -> None:
    """``_token`` itself (not just the signer): a changed old price or a changed new price shows."""
    tid = tenant_ctx.tenant_id
    await _item(db, tid, price="100.00")
    rows, _ = await SeasonMarkdownService._plan(
        db, tid, season="SS26", percent=Decimal("20"), brand_id=None, lock=False
    )
    tok = SeasonMarkdownService._token
    base = tok(tid, "SS26", Decimal("20"), rows)
    assert base == tok(tid, " ss26 ", Decimal("20"), rows)
    assert base != tok(tid, "SS26", Decimal("20"), [{**rows[0], "old_price": "101.00"}])
    assert base != tok(tid, "SS26", Decimal("20"), [{**rows[0], "new_price": "79.00"}])
    assert base != tok(tid, "SS26", Decimal("20"), [{**rows[0], "variant_id": str(uuid.uuid4())}])


# ── the floor, the cost flag and the brand ────────────────────────────────────────────────────


async def test_a_price_that_lands_exactly_on_a_cent_is_not_at_the_floor(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _item(db, tid, price="0.02")
    row = (await _prev(db, tid, percent="50"))["rows"][0]  # 0.02 * 0.5 = 0.01 exactly
    assert row["new_price"] == "0.01" and row["at_floor"] is False


async def test_unknown_cost_with_a_big_markdown_is_not_below_cost(db, tenant_ctx) -> None:
    """Without a known cost nothing can be below it, however deep the markdown."""
    tid = tenant_ctx.tenant_id
    await _item(db, tid, price="100", cost=None)
    row = (await _prev(db, tid, percent="90"))["rows"][0]
    assert row["cost_known"] is False and row["below_cost"] is False


async def test_a_zero_cost_is_a_known_cost_and_nothing_is_below_it(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _item(db, tid, price="100", cost="0")
    row = (await _prev(db, tid, percent="90"))["rows"][0]
    assert row["cost_known"] is True and row["below_cost"] is False


async def test_a_brand_filter_reaches_the_service_through_both_routes(db, tenant_ctx) -> None:
    from app.modules.catalog.models import Brand
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    tid = tenant_ctx.tenant_id
    nile = Brand(tenant_id=tid, name="نيل")
    db.add(nile)
    await db.flush()
    p1, v1 = await _item(db, tid, title="نيل", size="S")
    _, v2 = await _item(db, tid, title="تاني", size="M")
    p1.brand_id = nile.id
    await db.flush()
    base = "/api/v1/catalog/season-markdown"
    body = {"season": "SS26", "percent": "20", "brand_id": str(nile.id)}
    prev = (await _call(db, tenant_ctx, "POST", f"{base}/preview", perms=MANAGER, body=body)).json()
    assert [r["model"] for r in prev["rows"]] == ["نيل"]
    done = await _call(
        db,
        tenant_ctx,
        "POST",
        f"{base}/apply",
        perms=MANAGER,
        body={**body, "token": prev["token"]},
    )
    assert done.status_code == 200, done.text
    assert await _price(db, v1) == Decimal("80.00")
    assert await _price(db, v2) == Decimal("100.00")  # the other brand is untouched


async def test_the_audit_row_names_the_person_who_applied_it_through_the_route(
    db, tenant_ctx
) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    tid = tenant_ctx.tenant_id
    await _item(db, tid)
    base = "/api/v1/catalog/season-markdown"
    body = {"season": "SS26", "percent": "20"}
    prev = (await _call(db, tenant_ctx, "POST", f"{base}/preview", perms=MANAGER, body=body)).json()
    await _call(
        db,
        tenant_ctx,
        "POST",
        f"{base}/apply",
        perms=MANAGER,
        body={**body, "token": prev["token"]},
    )
    actor = (
        await db.execute(
            text(
                "select actor_user_id from audit_logs where tenant_id = :t"
                " and action = 'catalog.season_markdown'"
            ),
            {"t": tid},
        )
    ).scalar()
    assert actor is not None


def test_a_true_or_false_is_not_a_percent() -> None:
    with pytest.raises(ValidationError):
        parse_percent(True)
    with pytest.raises(ValidationError):
        parse_percent(False)


# ── the route ─────────────────────────────────────────────────────────────────────────────────


async def test_the_routes_are_manager_only(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import CASHIER, MANAGER, _call

    await _item(db, tenant_ctx.tenant_id)
    body = {"season": "SS26", "percent": "20"}
    base = "/api/v1/catalog/season-markdown"
    for path, b in (("preview", body), ("apply", {**body, "token": "x"})):
        denied = await _call(db, tenant_ctx, "POST", f"{base}/{path}", perms=CASHIER, body=b)
        assert denied.status_code == 403, path
    ok = await _call(db, tenant_ctx, "POST", f"{base}/preview", perms=MANAGER, body=body)
    assert ok.status_code == 200, ok.text


async def test_the_routes_preview_then_apply_end_to_end_and_409_on_a_stale_token(
    db, tenant_ctx
) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    tid = tenant_ctx.tenant_id
    _, v = await _item(db, tid, price="100.00")
    base = "/api/v1/catalog/season-markdown"
    body = {"season": "SS26", "percent": "20"}
    prev = (await _call(db, tenant_ctx, "POST", f"{base}/preview", perms=MANAGER, body=body)).json()
    assert prev["rows"][0]["new_price"] == "80.00"
    bad = await _call(
        db, tenant_ctx, "POST", f"{base}/apply", perms=MANAGER, body={**body, "token": "0" * 64}
    )
    assert bad.status_code == 409
    done = await _call(
        db,
        tenant_ctx,
        "POST",
        f"{base}/apply",
        perms=MANAGER,
        body={**body, "token": prev["token"]},
    )
    assert done.status_code == 200, done.text
    assert done.json()["applied"] == 1
    assert await _price(db, v) == Decimal("80.00")
    again = await _call(
        db,
        tenant_ctx,
        "POST",
        f"{base}/apply",
        perms=MANAGER,
        body={**body, "token": prev["token"]},
    )
    assert again.status_code == 409


async def test_the_routes_refuse_a_bad_percent_and_a_numeric_percent(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    base = "/api/v1/catalog/season-markdown/preview"
    for pct in ("0", "91", "abc"):
        r = await _call(
            db, tenant_ctx, "POST", base, perms=MANAGER, body={"season": "SS26", "percent": pct}
        )
        assert r.status_code == 400, pct  # the app's own ValidationError
    as_number = await _call(
        db, tenant_ctx, "POST", base, perms=MANAGER, body={"season": "SS26", "percent": 15.5}
    )
    assert as_number.status_code == 422


# ── two applies at the same moment ────────────────────────────────────────────────────────────


@pytest.fixture
async def one_shop(db_url, admin_url):
    from tests._pos_helpers import make_tenant, purge_test_tenant

    engine, factory, tid, uid = await make_tenant(db_url, "sm")
    try:
        yield factory, tid
    finally:
        await engine.dispose()
        await purge_test_tenant(admin_url, tid, uid)


async def test_two_applies_at_once_mark_the_season_down_once_not_twice(one_shop) -> None:
    """Two owners press Confirm together with the same preview: one wins, the other gets a 409.

    Without the row lock both read 100.00, both match the token, and the shop is marked down twice
    (100 -> 80 -> 64). With it the second waits, re-reads 80.00 and its token no longer matches.
    """
    import asyncio

    from tests._pos_helpers import in_tx

    factory, tid = one_shop

    async def make(s):
        _, v = await _item(s, tid, price="100.00")
        return v.id

    vid = await in_tx(factory, tid, make)
    assert not isinstance(vid, Exception), vid
    prev = await in_tx(factory, tid, lambda s: _prev(s, tid, percent="20"))
    assert not isinstance(prev, Exception), prev

    # Make the overlap certain instead of hoping for it: each apply waits, after it has read the
    # prices and before it writes, until BOTH have read (or a short timeout, which is what happens
    # when the row lock makes the second one wait). Without the lock both reads are 100.00.
    arrived = 0
    both_read = asyncio.Event()

    real_plan = SeasonMarkdownService._plan

    async def plan_then_meet(*a, **k):
        nonlocal arrived
        out = await real_plan(*a, **k)
        if k.get("lock"):
            arrived += 1
            if arrived >= 2:
                both_read.set()
            try:
                await asyncio.wait_for(both_read.wait(), timeout=1.5)
            except TimeoutError:
                pass  # the other apply is blocked on the row lock: exactly what the lock is for
        return out

    SeasonMarkdownService._plan = staticmethod(plan_then_meet)

    async def go(s):
        return await SeasonMarkdownService.apply(
            s, tid, None, season="SS26", percent="20", token=prev["token"]
        )

    try:
        results = await asyncio.gather(*[in_tx(factory, tid, go) for _ in range(2)])
    finally:
        SeasonMarkdownService._plan = staticmethod(real_plan)
    won = [r for r in results if isinstance(r, dict)]
    lost = [r for r in results if isinstance(r, ConflictError)]
    assert len(won) == 1 and len(lost) == 1, results

    async def read(s):
        return (
            await s.execute(text("select price from product_variants where id = :v"), {"v": vid})
        ).scalar()

    assert Decimal(await in_tx(factory, tid, read)) == Decimal("80.00")  # not 64

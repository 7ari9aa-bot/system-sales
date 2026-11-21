"""A shop's own size sets and colours, kept as data.

A shop that defined nothing sees exactly the lists the till has always offered, so nothing changes
for it. A shop that defined its own sees only its own, so it can drop a colour it never sells.
Names are cleaned the same way the size x colour matrix cleans them, and duplicates that differ only
by case or spaces are one entry.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ValidationError
from app.modules.catalog.apparel.options import (
    DEFAULT_COLOURS,
    DEFAULT_SIZE_SETS,
    ShopOptionsService,
)

pytestmark = pytest.mark.asyncio


async def test_a_shop_that_defined_nothing_sees_the_defaults(db, tenant_ctx) -> None:
    out = await ShopOptionsService.get(db, tenant_ctx.tenant_id)
    assert out["customised"] is False
    assert out["size_sets"] == DEFAULT_SIZE_SETS
    assert out["colours"] == DEFAULT_COLOURS


def test_the_defaults_are_the_lists_the_till_offered_before() -> None:
    assert DEFAULT_SIZE_SETS["clothing"] == ["S", "M", "L", "XL", "XXL"]
    assert DEFAULT_SIZE_SETS["shoes"] == ["39", "40", "41", "42", "43"]
    assert [c["name"] for c in DEFAULT_COLOURS][:3] == ["أسود", "أبيض", "كحلي"]
    assert len(DEFAULT_COLOURS) == 10
    assert all(c["hex"].startswith("#") for c in DEFAULT_COLOURS)


async def test_a_shop_can_save_its_own_size_sets_and_gets_only_those(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_size_sets(
        db, tid, {"رجالي": ["M", "L", "XL"], "مواليد": ["0-3", "3-6"]}
    )
    out = await ShopOptionsService.get(db, tid)
    assert out["size_sets"] == {"رجالي": ["M", "L", "XL"], "مواليد": ["0-3", "3-6"]}
    assert out["customised"] is True
    # colours were not touched, so they are still the defaults
    assert out["colours"] == DEFAULT_COLOURS


async def test_a_shop_can_save_its_own_colours_and_drops_the_ones_it_does_not_sell(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_colours(
        db, tid, [{"name": "أسود", "hex": "#000000"}, {"name": "عنابي", "hex": "#800020"}]
    )
    out = await ShopOptionsService.get(db, tid)
    assert [c["name"] for c in out["colours"]] == ["أسود", "عنابي"]
    assert out["size_sets"] == DEFAULT_SIZE_SETS


async def test_saving_again_replaces_the_previous_list_not_adds_to_it(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_colours(db, tid, [{"name": "أسود"}, {"name": "أبيض"}])
    await ShopOptionsService.save_colours(db, tid, [{"name": "أحمر"}])
    assert [c["name"] for c in (await ShopOptionsService.get(db, tid))["colours"]] == ["أحمر"]


async def test_the_order_the_owner_gave_is_kept(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_colours(db, tid, [{"name": "ج"}, {"name": "أ"}, {"name": "ب"}])
    assert [c["name"] for c in (await ShopOptionsService.get(db, tid))["colours"]] == [
        "ج",
        "أ",
        "ب",
    ]
    await ShopOptionsService.save_size_sets(db, tid, {"z": ["L", "S", "M"]})
    assert (await ShopOptionsService.get(db, tid))["size_sets"]["z"] == ["L", "S", "M"]


async def test_names_are_cleaned_like_the_matrix_cleans_them(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_size_sets(db, tid, {"  أطفال  ": ["٢ سنة", "  4   سنوات "]})
    out = await ShopOptionsService.get(db, tid)
    assert out["size_sets"] == {"أطفال": ["2 سنة", "4 سنوات"]}


async def test_duplicates_that_differ_only_by_case_or_spaces_are_one_entry(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_colours(
        db, tid, [{"name": "Red"}, {"name": " red "}, {"name": "RED"}, {"name": "Blue"}]
    )
    assert [c["name"] for c in (await ShopOptionsService.get(db, tid))["colours"]] == [
        "Red",
        "Blue",
    ]
    await ShopOptionsService.save_size_sets(db, tid, {"a": ["m", "M", "L"]})
    # a letter size is upper-cased exactly as the matrix does, so "m" and "M" are one size
    assert (await ShopOptionsService.get(db, tid))["size_sets"]["a"] == ["M", "L"]


async def test_two_sets_with_the_same_name_are_refused(db, tenant_ctx) -> None:
    with pytest.raises(ValidationError, match="size set"):
        await ShopOptionsService.save_size_sets(
            db, tenant_ctx.tenant_id, {"رجالي": ["M"], " رجالي ": ["L"]}
        )


@pytest.mark.parametrize(
    "bad",
    [{}, {"a": []}, {"": ["M"]}, {"a": [""]}, {"a": ["  "]}, {"a": ["x" * 64]}],
)
async def test_an_empty_or_oversized_size_set_is_refused_and_changes_nothing(
    db, tenant_ctx, bad
) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_size_sets(db, tid, {"keep": ["M"]})
    with pytest.raises(ValidationError):
        await ShopOptionsService.save_size_sets(db, tid, bad)
    assert (await ShopOptionsService.get(db, tid))["size_sets"] == {"keep": ["M"]}


@pytest.mark.parametrize("bad", ["red", "#12345", "#GGGGGG", "#1234567", "rgb(1,2,3)", "<x>"])
async def test_a_colour_hex_must_be_a_six_digit_hash_code(db, tenant_ctx, bad) -> None:
    with pytest.raises(ValidationError, match="hex"):
        await ShopOptionsService.save_colours(db, tenant_ctx.tenant_id, [{"name": "x", "hex": bad}])


async def test_a_colour_hex_is_optional_and_stored_upper_case(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_colours(db, tid, [{"name": "a"}, {"name": "b", "hex": "#aabbcc"}])
    cols = (await ShopOptionsService.get(db, tid))["colours"]
    assert cols[0]["hex"] is None
    assert cols[1]["hex"] == "#AABBCC"


async def test_an_empty_colour_list_or_a_colour_with_no_name_is_refused(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    for bad in ([], [{"name": ""}], [{"name": "   "}], [{}]):
        with pytest.raises(ValidationError):
            await ShopOptionsService.save_colours(db, tid, bad)


async def test_the_sizes_in_a_set_are_limited(db, tenant_ctx) -> None:
    with pytest.raises(ValidationError, match="at most"):
        await ShopOptionsService.save_size_sets(
            db, tenant_ctx.tenant_id, {"a": [str(i) for i in range(61)]}
        )
    with pytest.raises(ValidationError, match="at most"):
        await ShopOptionsService.save_size_sets(
            db, tenant_ctx.tenant_id, {f"s{i}": ["M"] for i in range(41)}
        )
    with pytest.raises(ValidationError, match="at most"):
        await ShopOptionsService.save_colours(
            db, tenant_ctx.tenant_id, [{"name": f"c{i}"} for i in range(201)]
        )


async def test_resetting_brings_the_defaults_back(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_colours(db, tid, [{"name": "عنابي"}])
    await ShopOptionsService.save_size_sets(db, tid, {"x": ["M"]})
    await ShopOptionsService.reset(db, tid)
    out = await ShopOptionsService.get(db, tid)
    assert out["customised"] is False
    assert out["colours"] == DEFAULT_COLOURS
    assert out["size_sets"] == DEFAULT_SIZE_SETS


async def test_one_shops_lists_never_show_in_another(db, tenant_ctx) -> None:
    await ShopOptionsService.save_colours(db, tenant_ctx.tenant_id, [{"name": "عنابي"}])
    other = await ShopOptionsService.get(db, uuid.uuid4())
    assert other["customised"] is False
    assert other["colours"] == DEFAULT_COLOURS


async def test_the_defaults_returned_cannot_be_changed_by_a_caller(db, tenant_ctx) -> None:
    out = await ShopOptionsService.get(db, tenant_ctx.tenant_id)
    out["colours"].append({"name": "x", "hex": None})
    out["size_sets"]["clothing"].append("ZZ")
    again = await ShopOptionsService.get(db, tenant_ctx.tenant_id)
    assert len(again["colours"]) == 10
    assert again["size_sets"]["clothing"] == ["S", "M", "L", "XL", "XXL"]


# ── the order a rack is read must use the shop's own letter sizes ─────────────────────────────


def test_the_rack_order_is_unchanged_for_the_built_in_letter_sizes() -> None:
    from app.modules.catalog.apparel.matrix import size_sort_key

    ordered = sorted(["XL", "S", "L", "M"], key=size_sort_key)
    assert ordered == ["S", "M", "L", "XL"]


# ── through the real routes ────────────────────────────────────────────────────────────────────


async def _call(db, tenant_ctx, method, path, *, perms, body=None):
    from httpx import ASGITransport, AsyncClient

    from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
    from tests.security.test_role_authz_matrix import _authz_app

    ctx = TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code="x",
            is_platform_admin=False,
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="x",
        permission_codes=perms,
    )
    app = _authz_app()

    async def _db():
        yield db

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=20
    ) as client:
        return await client.request(method, path, json=body)


READ = {"products:read"}
WRITE = {"products:read", "products:write"}
URL = "/api/v1/apparel/options"


async def test_the_route_returns_the_defaults_to_a_reader(db, tenant_ctx) -> None:
    r = await _call(db, tenant_ctx, "GET", URL, perms=READ)
    assert r.status_code == 200, r.text
    assert r.json()["customised"] is False
    assert len(r.json()["colours"]) == 10


async def test_the_route_saves_colours_and_size_sets_for_a_writer(db, tenant_ctx) -> None:
    c = await _call(
        db,
        tenant_ctx,
        "PUT",
        URL + "/colours",
        perms=WRITE,
        body={"colours": [{"name": "عنابي", "hex": "#800020"}]},
    )
    assert c.status_code == 200, c.text
    s = await _call(
        db,
        tenant_ctx,
        "PUT",
        URL + "/size-sets",
        perms=WRITE,
        body={"size_sets": {"رجالي": ["M", "L"]}},
    )
    assert s.status_code == 200, s.text
    got = (await _call(db, tenant_ctx, "GET", URL, perms=READ)).json()
    assert got["customised"] is True
    assert got["colours"] == [{"name": "عنابي", "hex": "#800020"}]
    assert got["size_sets"] == {"رجالي": ["M", "L"]}


async def test_a_reader_cannot_save_or_reset(db, tenant_ctx) -> None:
    body = {"colours": [{"name": "x"}]}
    assert (
        await _call(db, tenant_ctx, "PUT", URL + "/colours", perms=READ, body=body)
    ).status_code == 403
    assert (
        await _call(
            db, tenant_ctx, "PUT", URL + "/size-sets", perms=READ, body={"size_sets": {"a": ["M"]}}
        )
    ).status_code == 403
    assert (await _call(db, tenant_ctx, "DELETE", URL, perms=READ)).status_code == 403


async def test_the_route_refuses_a_bad_colour_with_a_clear_error(db, tenant_ctx) -> None:
    r = await _call(
        db,
        tenant_ctx,
        "PUT",
        URL + "/colours",
        perms=WRITE,
        body={"colours": [{"name": "x", "hex": "red"}]},
    )
    assert r.status_code in (400, 422), r.text
    assert (await _call(db, tenant_ctx, "GET", URL, perms=READ)).json()["customised"] is False


async def test_the_route_resets_to_the_defaults(db, tenant_ctx) -> None:
    await _call(
        db, tenant_ctx, "PUT", URL + "/colours", perms=WRITE, body={"colours": [{"name": "x"}]}
    )
    r = await _call(db, tenant_ctx, "DELETE", URL, perms=WRITE)
    assert r.status_code == 200, r.text
    assert r.json()["customised"] is False
    assert len(r.json()["colours"]) == 10


# ── gaps found by mutation ─────────────────────────────────────────────────────────────────────


async def test_size_sets_come_back_in_the_order_the_owner_gave_not_by_name(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_size_sets(
        db, tid, {"ز": ["M"], "أ": ["M"], "م": ["M"], "ب": ["M"]}
    )
    assert list((await ShopOptionsService.get(db, tid))["size_sets"]) == ["ز", "أ", "م", "ب"]


async def test_every_query_names_the_shop_it_is_for(db, tenant_ctx, monkeypatch) -> None:
    """Row-level security is the backstop. Each statement must also name the shop itself, so a
    missing policy or a privileged connection can never read or wipe another shop's lists."""
    tid = tenant_ctx.tenant_id
    seen: list[str] = []
    real = db.execute

    async def spy(stmt, *a, **k):
        seen.append(str(stmt.compile()))
        return await real(stmt, *a, **k)

    monkeypatch.setattr(db, "execute", spy)
    await ShopOptionsService.save_size_sets(db, tid, {"a": ["M"]})
    await ShopOptionsService.save_colours(db, tid, [{"name": "x"}])
    await ShopOptionsService.get(db, tid)
    await ShopOptionsService.reset(db, tid)
    own = [q for q in seen if "shop_size_sets" in q or "shop_colours" in q]
    assert own, "no statement touched the shop's lists"
    for q in own:
        if q.lstrip().upper().startswith(("SELECT", "DELETE")):
            assert "tenant_id =" in q, f"statement does not name the shop: {q[:90]}"


async def test_a_failed_save_leaves_the_previous_size_sets_untouched(
    db, tenant_ctx, monkeypatch
) -> None:
    """Replace is delete-then-insert: if the insert fails the old lists must still be there, with
    no savepoint wrapped around the call from outside."""
    from app.modules.catalog.models import ShopSizeSet

    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_size_sets(db, tid, {"keep": ["M"]})
    real_add = db.add
    calls = {"n": 0}

    def flaky(obj):
        if isinstance(obj, ShopSizeSet):
            calls["n"] += 1
            raise RuntimeError("boom")
        return real_add(obj)

    monkeypatch.setattr(db, "add", flaky)
    with pytest.raises(RuntimeError):
        await ShopOptionsService.save_size_sets(db, tid, {"new": ["L"]})
    monkeypatch.setattr(db, "add", real_add)
    assert (await ShopOptionsService.get(db, tid))["size_sets"] == {"keep": ["M"]}


async def test_a_failed_save_leaves_the_previous_colours_untouched(
    db, tenant_ctx, monkeypatch
) -> None:
    from app.modules.catalog.models import ShopColour

    tid = tenant_ctx.tenant_id
    await ShopOptionsService.save_colours(db, tid, [{"name": "keep"}])
    real_add = db.add

    def flaky(obj):
        if isinstance(obj, ShopColour):
            raise RuntimeError("boom")
        return real_add(obj)

    monkeypatch.setattr(db, "add", flaky)
    with pytest.raises(RuntimeError):
        await ShopOptionsService.save_colours(db, tid, [{"name": "new"}])
    monkeypatch.setattr(db, "add", real_add)
    assert [c["name"] for c in (await ShopOptionsService.get(db, tid))["colours"]] == ["keep"]

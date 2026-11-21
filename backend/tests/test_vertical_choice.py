"""The owner chooses what kind of shop this is, and a clothing shop starts with its branches.

The choice sets ``business.vertical``. Choosing apparel plants a starting tree of categories (men,
women, kids, babies) so the owner does not open an empty system, but only into a shop that has no
categories yet: it never touches what the owner already built. Choosing again later changes the
vertical and nothing else. Only verticals that actually behave differently are offered.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.core.shop_type import (
    APPAREL_STARTER_TREE,
    CHOOSABLE_VERTICALS,
    choose_vertical,
)
from app.modules.catalog.models import Category
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio


async def _cats(db, tid):
    return list((await db.execute(select(Category).where(Category.tenant_id == tid))).scalars())


async def _vertical(db, tid):
    return (await SettingsService(db, tid).resolve("business.vertical")).value


def test_only_verticals_that_behave_differently_can_be_chosen() -> None:
    assert set(CHOOSABLE_VERTICALS) == {"general", "apparel"}


async def test_choosing_apparel_sets_the_vertical(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await choose_vertical(db, tid, "apparel", user_id=tenant_ctx.user.id)
    assert await _vertical(db, tid) == "apparel"


async def test_choosing_apparel_plants_the_starting_branches_once(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    out = await choose_vertical(db, tid, "apparel", user_id=tenant_ctx.user.id)
    cats = await _cats(db, tid)
    roots = {c.name for c in cats if c.parent_id is None}
    assert roots == set(APPAREL_STARTER_TREE)
    assert out["categories_created"] == len(cats) > 0
    # Each branch has its own sub-branches, as data.
    men = next(c for c in cats if c.name == "رجالي" and c.parent_id is None)
    assert {c.name for c in cats if c.parent_id == men.id} == set(APPAREL_STARTER_TREE["رجالي"])


async def test_choosing_apparel_again_does_not_plant_a_second_tree(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await choose_vertical(db, tid, "apparel", user_id=tenant_ctx.user.id)
    n = len(await _cats(db, tid))
    again = await choose_vertical(db, tid, "apparel", user_id=tenant_ctx.user.id)
    assert len(await _cats(db, tid)) == n
    assert again["categories_created"] == 0


async def test_a_shop_that_already_has_categories_keeps_them_untouched(db, tenant_ctx) -> None:
    from app.modules.catalog.service import CatalogService

    tid = tenant_ctx.tenant_id
    mine = await CatalogService.create_category(db, tid, name="My own section")
    out = await choose_vertical(db, tid, "apparel", user_id=tenant_ctx.user.id)
    cats = await _cats(db, tid)
    assert [c.name for c in cats] == ["My own section"]
    assert cats[0].id == mine.id
    assert out["categories_created"] == 0
    assert await _vertical(db, tid) == "apparel"


async def test_choosing_general_plants_nothing(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    out = await choose_vertical(db, tid, "general", user_id=tenant_ctx.user.id)
    assert await _cats(db, tid) == []
    assert out["categories_created"] == 0
    assert await _vertical(db, tid) == "general"


async def test_switching_away_from_apparel_keeps_the_categories(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await choose_vertical(db, tid, "apparel", user_id=tenant_ctx.user.id)
    n = len(await _cats(db, tid))
    await choose_vertical(db, tid, "general", user_id=tenant_ctx.user.id)
    assert len(await _cats(db, tid)) == n
    assert await _vertical(db, tid) == "general"


@pytest.mark.parametrize("name", ["pharmacy", "restaurant", "nonsense", ""])
async def test_a_vertical_that_is_not_offered_is_refused_and_changes_nothing(
    db, tenant_ctx, name
) -> None:
    tid = tenant_ctx.tenant_id
    before = await _vertical(db, tid)
    with pytest.raises(ValidationError):
        await choose_vertical(db, tid, name, user_id=tenant_ctx.user.id)
    assert await _vertical(db, tid) == before
    assert await _cats(db, tid) == []


async def test_the_tree_is_planted_in_the_chosen_shop_only(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await choose_vertical(db, tid, "apparel", user_id=tenant_ctx.user.id)
    assert await _cats(db, uuid.uuid4()) == []


async def test_a_failure_while_planting_leaves_the_vertical_unchanged(
    db, tenant_ctx, monkeypatch
) -> None:
    """Both happen or neither: no shop is left 'apparel' with half a tree.

    The failure is NOT wrapped in a savepoint here: choose_vertical must be atomic on its own,
    or a caller that catches the error would keep a half-planted shop.
    """
    from app.modules.catalog.service import CatalogService

    tid = tenant_ctx.tenant_id
    before = await _vertical(db, tid)
    real = CatalogService.create_category
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("boom")
        return await real(*a, **k)

    monkeypatch.setattr(CatalogService, "create_category", staticmethod(flaky))
    with pytest.raises(RuntimeError):
        await choose_vertical(db, tid, "apparel", user_id=tenant_ctx.user.id)
    assert await _vertical(db, tid) == before
    assert await _cats(db, tid) == []


async def test_the_has_categories_check_names_the_shop_in_its_own_statement(
    db, tenant_ctx, monkeypatch
) -> None:
    """Row-level security is the backstop; the query must also name the shop itself."""
    tid = tenant_ctx.tenant_id
    seen: list[str] = []
    real = db.execute

    async def spy(stmt, *a, **k):
        seen.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        return await real(stmt, *a, **k)

    monkeypatch.setattr(db, "execute", spy)
    await choose_vertical(db, tid, "general", user_id=tenant_ctx.user.id)
    # general plants nothing, so ask the check directly
    from app.core.shop_type import _has_categories

    seen.clear()
    await _has_categories(db, tid)
    counts = [q for q in seen if "categories" in q]
    assert counts and all("categories.tenant_id =" in q for q in counts)


# ── through the real routes ────────────────────────────────────────────────────────────────────


async def _call(db, tenant_ctx, method: str, path: str, *, perms: set[str]):
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
        return await client.request(method, path)


async def test_the_route_lists_the_choices_and_the_current_one(db, tenant_ctx) -> None:
    r = await _call(db, tenant_ctx, "GET", "/api/v1/shop-type", perms={"products:read"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["choices"]) == {"general", "apparel"}
    assert body["current"] == "general"


async def test_the_route_chooses_apparel_and_plants_the_tree(db, tenant_ctx) -> None:
    r = await _call(db, tenant_ctx, "POST", "/api/v1/shop-type/apparel", perms={"settings:write"})
    assert r.status_code == 200, r.text
    assert r.json()["vertical"] == "apparel"
    assert r.json()["categories_created"] > 0
    assert await _vertical(db, tenant_ctx.tenant_id) == "apparel"


async def test_the_route_refuses_without_the_settings_permission(db, tenant_ctx) -> None:
    r = await _call(db, tenant_ctx, "POST", "/api/v1/shop-type/apparel", perms={"products:write"})
    assert r.status_code == 403
    assert await _vertical(db, tenant_ctx.tenant_id) == "general"
    assert await _cats(db, tenant_ctx.tenant_id) == []


async def test_the_route_refuses_a_vertical_that_is_not_offered(db, tenant_ctx) -> None:
    r = await _call(db, tenant_ctx, "POST", "/api/v1/shop-type/pharmacy", perms={"settings:write"})
    assert r.status_code in (400, 422), r.text
    assert await _vertical(db, tenant_ctx.tenant_id) == "general"

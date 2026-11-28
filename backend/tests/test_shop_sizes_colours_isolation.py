"""Two real shops on real connections: neither sees, changes or wipes the other's lists.

The per-test `db` fixture is one connection that row-level security is not really exercised on, so
this commits two throw-away shops and talks to them through the app role, then deletes everything
it made. A shop's lists must also survive another shop saving, resetting or being deleted.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.core.db import bind_tenant
from app.applications.apparel.modules.catalog.apparel.options import DEFAULT_COLOURS, ShopOptionsService
from tests._pos_helpers import in_tx, make_tenant

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def two_shops(db_url):
    a = await make_tenant(db_url, "optA")
    b = await make_tenant(db_url, "optB")
    try:
        yield a, b
    finally:
        for engine, factory, tenant_id, user_id in (a, b):
            async with factory() as s:
                await s.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                )
                for table in ("shop_colours", "shop_size_sets"):
                    await s.execute(
                        sa.text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                    )
                await s.commit()
            async with factory() as s:
                await s.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                )
                await s.execute(
                    sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)}
                )
                await s.execute(
                    sa.text("DELETE FROM tenant_users WHERE tenant_id = :t"), {"t": tenant_id}
                )
                await s.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
                gone = await s.execute(
                    sa.text("DELETE FROM tenants WHERE id = :t RETURNING id"), {"t": tenant_id}
                )
                assert gone.first() is not None, "cleanup failed: a throw-away shop is left behind"
                await s.commit()
            await engine.dispose()


async def _get(shop):
    _, factory, tid, _ = shop
    return await in_tx(factory, tid, lambda s: ShopOptionsService.get(s, tid))


async def test_one_shops_saved_lists_are_not_seen_by_the_other(two_shops) -> None:
    a, b = two_shops
    await in_tx(a[1], a[2], lambda s: ShopOptionsService.save_colours(s, a[2], [{"name": "عنابي"}]))
    assert [c["name"] for c in (await _get(a))["colours"]] == ["عنابي"]
    other = await _get(b)
    assert other["customised"] is False
    assert other["colours"] == DEFAULT_COLOURS


async def test_one_shop_resetting_does_not_wipe_the_other(two_shops) -> None:
    a, b = two_shops
    for shop, name in ((a, "A-colour"), (b, "B-colour")):
        await in_tx(
            shop[1],
            shop[2],
            lambda s, shop=shop, name=name: ShopOptionsService.save_colours(
                s, shop[2], [{"name": name}]
            ),
        )
    await in_tx(a[1], a[2], lambda s: ShopOptionsService.reset(s, a[2]))
    assert (await _get(a))["customised"] is False
    assert [c["name"] for c in (await _get(b))["colours"]] == ["B-colour"]


async def test_one_shop_saving_does_not_replace_the_other(two_shops) -> None:
    a, b = two_shops
    await in_tx(b[1], b[2], lambda s: ShopOptionsService.save_size_sets(s, b[2], {"x": ["M"]}))
    await in_tx(a[1], a[2], lambda s: ShopOptionsService.save_size_sets(s, a[2], {"y": ["L"]}))
    assert (await _get(b))["size_sets"] == {"x": ["M"]}
    assert (await _get(a))["size_sets"] == {"y": ["L"]}


async def test_the_same_colour_name_can_exist_in_both_shops(two_shops) -> None:
    """The unique key is per shop, so two shops may both sell 'أسود'."""
    a, b = two_shops
    for shop in (a, b):
        await in_tx(
            shop[1],
            shop[2],
            lambda s, shop=shop: ShopOptionsService.save_colours(s, shop[2], [{"name": "أسود"}]),
        )
    assert [c["name"] for c in (await _get(a))["colours"]] == ["أسود"]
    assert [c["name"] for c in (await _get(b))["colours"]] == ["أسود"]


async def test_a_shop_cannot_write_a_row_for_another_shop(two_shops) -> None:
    """Row-level security refuses an insert that names someone else's shop."""
    a, b = two_shops

    async def _forge(s):
        await s.execute(
            sa.text(
                "INSERT INTO shop_colours (id, tenant_id, name, position) "
                "VALUES (gen_random_uuid(), :t, 'forged', 0)"
            ),
            {"t": b[2]},
        )
        await s.flush()

    result = await in_tx(a[1], a[2], _forge)
    assert isinstance(result, Exception)
    assert (await _get(b))["customised"] is False


async def test_a_shop_sees_none_of_the_others_rows_without_the_service(two_shops) -> None:
    a, b = two_shops
    await in_tx(b[1], b[2], lambda s: ShopOptionsService.save_colours(s, b[2], [{"name": "سري"}]))

    async def _count(s):
        await bind_tenant(s, a[2])
        return (await s.execute(sa.text("SELECT count(*) FROM shop_colours"))).scalar_one()

    assert await in_tx(a[1], a[2], _count) == 0

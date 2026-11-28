"""The owner's three screen switches: transfers between warehouses, online allocation, units.

They only HIDE a screen. Every shop starts with all three shown, so nothing changes for a shop that
never touches them; the owner (or the apparel preset) turns one off and it can be turned back on.
Any member of the shop may read the answer, because the till needs it to draw its menu.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.modules.inventory.services.screens import SCREEN_SWITCHES, decide, visible_screens
from app.platform.settings.registry import get_definition
from app.platform.settings.service import SettingsService

ALL = set(SCREEN_SWITCHES)


@pytest.mark.parametrize("key", sorted(SCREEN_SWITCHES.values()))
def test_each_switch_is_a_tenant_bool_that_starts_shown_and_is_enforced(key: str) -> None:
    d = get_definition(key)
    assert d.default is True
    assert d.enforced
    assert d.label_ar and d.label_en and d.description_ar and d.description_en


def test_a_real_false_hides_and_nothing_else_does() -> None:
    k = SCREEN_SWITCHES["warehouse_transfers"]
    assert decide({k: False})["warehouse_transfers"] is False
    for stray in (True, None, 0, "", "false", "no", []):
        assert decide({k: stray})["warehouse_transfers"] is True, stray


def test_the_three_screens_decide_independently() -> None:
    off = {SCREEN_SWITCHES["channel_allocation"]: False}
    assert decide(off) == {
        "warehouse_transfers": True,
        "channel_allocation": False,
        "units_of_measure": True,
    }


@pytest.mark.asyncio
async def test_a_shop_that_never_touched_them_shows_everything(db, tenant_ctx) -> None:
    got = await visible_screens(db, tenant_ctx.tenant_id)
    assert set(got) == ALL
    assert all(v is True for v in got.values())


@pytest.mark.asyncio
async def test_turning_one_off_hides_only_that_one_and_back_on_restores_it(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(SCREEN_SWITCHES["warehouse_transfers"], False)
    got = await visible_screens(db, tenant_ctx.tenant_id)
    assert got == {
        "warehouse_transfers": False,
        "channel_allocation": True,
        "units_of_measure": True,
    }
    await svc.set(SCREEN_SWITCHES["warehouse_transfers"], True)
    assert all((await visible_screens(db, tenant_ctx.tenant_id)).values())


@pytest.mark.asyncio
async def test_one_shop_hiding_a_screen_does_not_hide_it_for_another(db, tenant_ctx) -> None:
    import uuid

    other = uuid.uuid4()
    await SettingsService(db, tenant_ctx.tenant_id).set(SCREEN_SWITCHES["units_of_measure"], False)
    assert (await visible_screens(db, tenant_ctx.tenant_id))["units_of_measure"] is False
    assert (await visible_screens(db, other))["units_of_measure"] is True


def test_the_route_is_read_only_and_open_to_any_member_so_the_till_can_use_it() -> None:
    from app.applications.apparel.modules.inventory.router import router

    route = next(r for r in router.routes if getattr(r, "path", "") == "/inventory/screens")
    assert route.methods == {"GET"}
    deps = [d.call.__name__ for d in route.dependant.dependencies]
    assert "require_permission" not in " ".join(deps)

"""The single ground-floor cash clothes shop, as a preset an owner applies on purpose.

A preset is data: values for switches that already exist. These tests prove the values land, that
nobody is switched into it by choosing apparel alone, and that every other preset and every other
shop is left exactly as it was.
"""

from __future__ import annotations

import pytest

from app.modules.settings.presets import PRESETS
from app.modules.settings.registry import REGISTRY
from app.modules.settings.service import SettingsService

NAME = "apparel_ground_shop"
OWNER = {"settings:write", "settings:read"}

# What each preset held before this one was added. If an older preset ever changes, this fails.
_OLD = {
    "physical_retail": {
        "business.type": "retail",
        "pos.require_customer": False,
        "pos.allow_hold_cart": True,
        "pos.return_max_days": 30,
        "inventory.auto_reserve": False,
        "inventory.fifo_enabled": False,
        "inventory.track_locations": False,
        "inventory.quality_check_on_receipt": False,
        "purchasing.approval_required": False,
        "purchasing.allow_partial_receipt": True,
        "print.paper_width": "80mm",
        "print.copies": 1,
        "notifications.low_stock_alert": True,
    },
}


def test_every_key_in_the_preset_is_a_real_setting_with_a_valid_value() -> None:
    for key, value in PRESETS[NAME].items():
        defn = REGISTRY.get(key)
        assert defn is not None, key
        assert value is not None, key


def test_the_preset_makes_the_till_take_cash_to_a_walk_in_and_never_on_account() -> None:
    p = PRESETS[NAME]
    assert p["pos.take_payments"] is True
    assert p["pos.require_customer"] is False
    assert p["pos.allow_sale_on_account"] is False


def test_the_preset_switches_off_batches_serials_locations_and_quality_hold() -> None:
    p = PRESETS[NAME]
    for key in (
        "capability.serial_tracking",
        "capability.lot_expiry",
        "capability.fefo_picking",
        "inventory.track_locations",
        "inventory.quality_check_on_receipt",
        "inventory.auto_reserve",
        "purchasing.centralized",
    ):
        assert p[key] is False, key


def test_the_preset_keeps_the_low_stock_alert_and_the_size_colour_matrix_on() -> None:
    p = PRESETS[NAME]
    assert p["notifications.low_stock_alert"] is True
    assert p["capability.variant_matrix"] is True
    assert p["inventory.stocktake_approval_required"] is True


def test_the_preset_hides_transfers_online_allocation_and_units_of_measure() -> None:
    """A one-store, walk-in-only shop does not use these three screens, and each has a switch."""
    for key in (
        "inventory.show_warehouse_transfers",
        "inventory.show_channel_allocation",
        "inventory.show_units_of_measure",
    ):
        assert PRESETS[NAME][key] is False, key


def test_the_older_presets_are_unchanged() -> None:
    for name, expected in _OLD.items():
        assert PRESETS[name] == expected, name
    assert set(_OLD) <= set(PRESETS)
    assert {"ecommerce", "omnichannel", "enterprise"} <= set(PRESETS)


def test_no_other_preset_turns_on_payments_so_a_shop_that_does_not_pick_this_is_unchanged() -> None:
    for name, preset in PRESETS.items():
        if name != NAME:
            assert "pos.take_payments" not in preset, name


@pytest.mark.asyncio
async def test_applying_it_writes_every_value_and_an_owner_may_do_it(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    result = await svc.apply_preset(NAME, user_id=tenant_ctx.user.id, permissions=OWNER)
    assert len(result["applied"]) == len(PRESETS[NAME])
    assert result["pending_approval"] == []
    for key, value in PRESETS[NAME].items():
        assert (await svc.resolve(key)).value == value, key


@pytest.mark.asyncio
async def test_applying_it_turns_the_till_on_and_the_shop_into_apparel(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    assert (await svc.resolve("pos.take_payments")).value is False
    await svc.apply_preset(NAME, user_id=tenant_ctx.user.id, permissions=OWNER)
    assert (await svc.resolve("pos.take_payments")).value is True
    assert (await svc.resolve("business.vertical")).value == "apparel"


@pytest.mark.asyncio
async def test_a_shop_that_never_applied_it_keeps_every_default(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    for key in PRESETS[NAME]:
        resolved = await svc.resolve(key)
        assert resolved.is_default, key
        assert resolved.value == REGISTRY[key].default, key


@pytest.mark.asyncio
async def test_applying_it_to_one_shop_leaves_another_shop_untouched(db, tenant_ctx) -> None:
    import uuid

    other = uuid.uuid4()
    await SettingsService(db, tenant_ctx.tenant_id).apply_preset(
        NAME, user_id=tenant_ctx.user.id, permissions=OWNER
    )
    resolved = await SettingsService(db, other).resolve("pos.take_payments")
    assert resolved.value is False
    assert resolved.is_default


@pytest.mark.asyncio
async def test_a_person_without_settings_write_cannot_apply_it(db, tenant_ctx) -> None:
    from app.core.errors import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await SettingsService(db, tenant_ctx.tenant_id).apply_preset(
            NAME, user_id=tenant_ctx.user.id, permissions={"orders:read"}
        )


@pytest.mark.asyncio
async def test_the_owner_can_still_change_any_value_afterwards(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.apply_preset(NAME, user_id=tenant_ctx.user.id, permissions=OWNER)
    await svc.set("pos.take_payments", False, user_id=tenant_ctx.user.id)
    assert (await svc.resolve("pos.take_payments")).value is False


@pytest.mark.asyncio
async def test_applying_it_twice_changes_nothing_the_second_time(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.apply_preset(NAME, user_id=tenant_ctx.user.id, permissions=OWNER)
    await svc.apply_preset(NAME, user_id=tenant_ctx.user.id, permissions=OWNER)
    for key, value in PRESETS[NAME].items():
        assert (await svc.resolve(key)).value == value, key


@pytest.mark.asyncio
async def test_choosing_apparel_alone_does_not_apply_the_preset(db, tenant_ctx) -> None:
    from app.core.shop_type import choose_vertical

    await choose_vertical(db, tenant_ctx.tenant_id, "apparel", user_id=tenant_ctx.user.id)
    svc = SettingsService(db, tenant_ctx.tenant_id)
    assert (await svc.resolve("business.vertical")).value == "apparel"
    for key in ("pos.take_payments", "inventory.auto_reserve", "purchasing.centralized"):
        assert (await svc.resolve(key)).is_default, key


@pytest.mark.asyncio
async def test_the_preset_is_listed_so_an_owner_can_find_it(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import _call

    r = await _call(db, tenant_ctx, "GET", "/api/v1/settings/presets", perms={"settings:read"})
    assert r.status_code == 200, r.text
    assert NAME in r.json()


@pytest.mark.asyncio
async def test_the_apply_route_applies_it_and_refuses_a_cashier(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import _call

    path = f"/api/v1/settings/presets/{NAME}"
    denied = await _call(db, tenant_ctx, "POST", path, perms={"orders:read"})
    assert denied.status_code == 403
    ok = await _call(db, tenant_ctx, "POST", path, perms={"settings:write", "settings:read"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["applied_count"] == len(PRESETS[NAME])


_EXPECTED = {
    "business.type": "retail",
    "business.vertical": "apparel",
    "pos.take_payments": True,
    "pos.require_customer": False,
    "pos.allow_sale_on_account": False,
    "pos.allow_hold_cart": True,
    "pos.variance_reason_required": True,
    "pos.settle_payment_methods": True,
    "pos.return_restock_default": True,
    "pos.return_max_days": 30,
    "inventory.auto_reserve": False,
    "inventory.track_locations": False,
    "inventory.quality_check_on_receipt": False,
    "inventory.fifo_enabled": True,
    "inventory.stocktake_approval_required": True,
    "inventory.show_warehouse_transfers": False,
    "inventory.show_channel_allocation": False,
    "inventory.show_units_of_measure": False,
    "capability.serial_tracking": False,
    "capability.lot_expiry": False,
    "capability.fefo_picking": False,
    "capability.weight_scale": False,
    "capability.variant_matrix": True,
    "purchasing.approval_required": False,
    "purchasing.centralized": False,
    "purchasing.allow_partial_receipt": True,
    "print.paper_width": "80mm",
    "print.copies": 1,
    "notifications.low_stock_alert": True,
    "notifications.order_received": False,
}


def test_the_preset_holds_exactly_these_values_and_no_others() -> None:
    """One table is the contract. A value changed, a key added or one dropped fails here, so the
    preset can never drift from what the owner was told it does."""
    assert PRESETS[NAME] == _EXPECTED
    for key, value in PRESETS[NAME].items():
        assert type(value) is type(_EXPECTED[key]), key

"""A shop's vertical decides what it can do, and its owner decides the rest.

A vertical (apparel, pharmacy, restaurant, general) only chooses the *starting* answer for each
capability. Every capability is its own switch the owner can flip, so a pharmacy that wants size
and colour variants, or a clothes shop that tracks expiry, just turns it on. Code asks
``capability_enabled`` and never branches on the vertical's name.
"""

from __future__ import annotations

import pytest

from app.platform.settings import capabilities as caps
from app.platform.settings.registry import get_definition


def test_the_four_verticals_are_known() -> None:
    assert set(caps.VERTICALS) == {"general", "apparel", "pharmacy", "restaurant"}


def test_apparel_starts_with_the_size_and_colour_matrix_and_nothing_pharmacy() -> None:
    on = caps.defaults_for("apparel")
    assert on["variant_matrix"] is True
    assert on["lot_expiry"] is False
    assert on["prescription_required"] is False


def test_pharmacy_starts_with_batches_expiry_and_prescriptions() -> None:
    on = caps.defaults_for("pharmacy")
    assert on["lot_expiry"] is True
    assert on["fefo_picking"] is True
    assert on["prescription_required"] is True
    assert on["variant_matrix"] is False


def test_restaurant_starts_with_modifiers_and_recipes() -> None:
    on = caps.defaults_for("restaurant")
    assert on["modifiers"] is True
    assert on["recipe_bom"] is True
    assert on["lot_expiry"] is False


def test_general_is_the_plain_shop_with_no_special_capability() -> None:
    assert not any(caps.defaults_for("general").values())


def test_an_unknown_vertical_is_the_plain_shop_not_an_error() -> None:
    assert caps.defaults_for("moon-base") == caps.defaults_for("general")
    assert caps.defaults_for(None) == caps.defaults_for("general")


def test_every_vertical_answers_every_capability() -> None:
    names = set(caps.CAPABILITIES)
    for v in caps.VERTICALS:
        assert set(caps.defaults_for(v)) == names, v


def test_an_owner_choice_beats_the_verticals_default_both_ways() -> None:
    # pharmacy default is ON; the owner turned it off
    assert (
        caps.capability_enabled("lot_expiry", vertical="pharmacy", overrides={"lot_expiry": False})
        is False
    )
    # apparel default is OFF; the owner turned it on
    assert (
        caps.capability_enabled("lot_expiry", vertical="apparel", overrides={"lot_expiry": True})
        is True
    )


def test_no_owner_choice_falls_back_to_the_verticals_default() -> None:
    assert caps.capability_enabled("lot_expiry", vertical="pharmacy", overrides={}) is True
    assert caps.capability_enabled("lot_expiry", vertical="apparel", overrides={}) is False
    assert caps.capability_enabled("lot_expiry", vertical="apparel", overrides=None) is False


def test_an_unknown_capability_is_off_not_a_crash() -> None:
    assert caps.capability_enabled("teleport", vertical="pharmacy", overrides={}) is False


def test_a_non_boolean_override_is_ignored_so_a_bad_value_cannot_switch_things_on() -> None:
    for bad in ("true", "yes", 1, 0, [], {}):
        assert (
            caps.capability_enabled("lot_expiry", vertical="apparel", overrides={"lot_expiry": bad})
            is False
        ), bad


def test_the_vertical_is_a_setting_the_owner_controls() -> None:
    d = get_definition("business.vertical")
    assert d.default == "general"
    assert set(d.allowed_values) == set(caps.VERTICALS)
    assert d.permission == "settings:write"


@pytest.mark.parametrize("name", sorted(caps.CAPABILITIES))
def test_every_capability_is_an_owner_setting_with_labels(name: str) -> None:
    d = get_definition(f"capability.{name}")
    assert d.type.value == "bool"
    assert d.permission == "settings:write"
    assert d.label_ar and d.label_en and d.description_ar


def test_the_capabilities_route_is_declared_before_the_catch_all_key_route() -> None:
    """``/{key:path}`` swallows any path declared after it; the rule is cheap to keep."""
    from app.platform.settings.router import router

    paths = [(r.path, tuple(sorted(r.methods))) for r in router.routes]
    cap = next(i for i, (p, m) in enumerate(paths) if p.endswith("/capabilities") and "GET" in m)
    catch_all = next(i for i, (p, _m) in enumerate(paths) if p.endswith("{key:path}"))
    assert cap < catch_all


def test_the_capabilities_route_is_read_only_and_needs_the_settings_read_permission() -> None:
    from app.platform.settings import router as r

    route = next(x for x in r.router.routes if x.path.endswith("/capabilities"))
    assert route.methods == {"GET"}
    assert "SettingsReadCtx" in str(route.endpoint.__annotations__)

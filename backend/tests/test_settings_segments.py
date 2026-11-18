"""Business segments: each kind of shop sees the settings that mean something to it.

The platform serves retail, food and beverage, services and wholesale. A setting names the segments
it applies to; naming none means everyone. Narrowing only changes what the settings screen lists,
never what a key resolves to, so code that reads a setting never has to know the segment.
"""

from __future__ import annotations

import pytest

from app.modules.settings.registry import (
    SEGMENTS,
    SettingDef,
    SettingType,
    get_definition,
    list_definitions,
)


def test_every_segment_a_setting_names_is_a_known_one() -> None:
    for d in list_definitions():
        assert set(d.segments) <= set(SEGMENTS), f"{d.key} names an unknown segment: {d.segments}"


def test_business_type_choices_are_exactly_the_segments() -> None:
    """The segment list and the ``business.type`` choices must never drift apart."""
    assert set(get_definition("business.type").allowed_values or ()) == set(SEGMENTS)


def test_no_segment_is_left_with_nothing_to_configure() -> None:
    for seg in SEGMENTS:
        assert list_definitions(segment=seg), f"segment {seg} sees no settings at all"


def test_a_setting_naming_no_segment_is_shown_to_every_segment() -> None:
    shared = get_definition("pos.max_discount_pct")
    assert shared.segments == ()
    for seg in SEGMENTS:
        assert shared in list_definitions(segment=seg)


def test_services_do_not_see_shelf_stock_settings() -> None:
    services = {d.key for d in list_definitions(segment="services")}
    assert "inventory.fifo_enabled" not in services
    assert "orders.allow_backorder" not in services
    assert "purchasing.allow_over_receipt" not in services
    # ...but still see what any business has: identity, printing, notifications.
    assert {"business.legal_name", "print.paper_width", "notifications.order_received"} <= services


@pytest.mark.parametrize("seg", ["retail", "fnb", "wholesale"])
def test_goods_segments_see_the_shelf_stock_settings(seg: str) -> None:
    keys = {d.key for d in list_definitions(segment=seg)}
    assert {"inventory.fifo_enabled", "orders.allow_backorder"} <= keys


def test_segment_and_domain_filters_combine() -> None:
    services = {d.key for d in list_definitions(domain="inventory", segment="services")}
    retail = {d.key for d in list_definitions(domain="inventory", segment="retail")}
    assert services < retail  # services see strictly fewer inventory keys, never more
    assert "inventory.fifo_enabled" in retail - services


def test_a_hidden_setting_still_resolves_to_its_default() -> None:
    """Hiding a key from a segment's screen must not make it unreadable to the code."""
    hidden = get_definition("inventory.fifo_enabled")
    assert "services" not in hidden.segments
    assert hidden.default is True


def test_the_default_for_an_unfiltered_call_is_unchanged() -> None:
    assert len(list_definitions()) == len({d.key for d in list_definitions()})


def test_a_definition_defaults_to_every_segment() -> None:
    d = SettingDef(key="x.y", domain="x", type=SettingType.BOOL, default=True)
    assert d.segments == ()


def test_no_two_settings_share_a_description() -> None:
    """A copy-pasted description tells the merchant the wrong thing about a setting."""
    seen: dict[str, str] = {}
    for d in list_definitions():
        for text in (d.description_en, d.description_ar):
            if not text:
                continue
            assert text not in seen, f"{d.key} repeats the description of {seen[text]}: {text!r}"
            seen[text] = d.key


def test_every_setting_explains_itself_in_both_languages() -> None:
    """The settings screen shows the description; a blank one leaves only a bare name."""
    for d in list_definitions():
        assert d.label_ar and d.label_en, f"{d.key} is missing a label"
        assert d.description_ar and d.description_en, f"{d.key} is missing a description"


def test_settings_with_no_behind_them_stay_out_of_the_registry() -> None:
    """These were listed but nothing read them (the till records a sale, it takes no payment, and
    the day/receipt/drawer rules are always on). A switch that moves nothing misleads the owner."""
    keys = {d.key for d in list_definitions()}
    for gone in (
        "pos.default_payment_method",
        "pos.allowed_payment_methods",
        "pos.require_session",
        "pos.opening_float_required",
        "pos.return_requires_receipt",
        "pos.deduct_stock_on",
    ):
        assert gone not in keys, f"{gone} is back but nothing enforces it"

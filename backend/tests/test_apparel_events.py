"""Apparel events must be publishable, not just named.

An event type that the outbox cannot resolve is an event no consumer can read,
and the failure shows up at the worst moment: the first real sale. These tests
check the wire names, the registration, and that registering twice is safe
because startup may retry.
"""

from __future__ import annotations

from app.applications.apparel.events import (
    PREFIX,
    event_names,
    is_registered,
    register,
    wire_name,
)
from app.applications.apparel.manifest import MODULES
from app.core.events.schemas import EVENT_TYPES


def test_wire_names_are_prefixed_and_snake_cased() -> None:
    assert wire_name("catalog", "ProductCreated") == "apparel.catalog.product_created"
    assert wire_name("pos", "ShiftClosed") == "apparel.pos.shift_closed"


def test_every_manifest_event_has_a_wire_name() -> None:
    declared = sum(len(module.events) for module in MODULES)
    names = event_names()
    assert len(names) == declared
    assert len(set(names)) == len(names), f"duplicate wire names: {names}"
    for name in names:
        assert name.startswith(PREFIX), name


def test_registration_makes_every_event_resolvable() -> None:
    register()
    missing = [name for name in event_names() if not is_registered(name)]
    assert missing == [], f"events the outbox could not deserialize: {missing}"


def test_registering_twice_is_safe() -> None:
    register()
    before = {name: EVENT_TYPES[name] for name in event_names()}
    register()
    assert {name: EVENT_TYPES[name] for name in event_names()} == before


def test_the_platform_does_not_hard_code_apparel_events() -> None:
    """The closed set stays the platform's; sector names arrive by registration."""
    from app.core.events.schemas import DOMAIN_EVENT_TYPES

    hardcoded = [name for name in DOMAIN_EVENT_TYPES if name.startswith(PREFIX)]
    assert hardcoded == [], (
        "apparel events must be registered by the application, never listed in "
        f"platform code: {hardcoded}"
    )

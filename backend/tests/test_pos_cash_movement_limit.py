"""A drawer movement cap the shop actually set is enforced, and one it never set is not.

A pay-out is the one way cash leaves the drawer without a sale, so the owner can cap a single
movement. The rule has to be exact in both directions: a limit of zero must never block a
movement (every shop that never touched the setting), and a positive limit must refuse anything
above it while still allowing the amount at the limit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.applications.apparel.modules.pos.service import PosService
from app.modules.settings.registry import ENFORCED_KEYS, get_definition

check = PosService._assert_within_cash_movement_limit


def test_a_shop_that_never_set_a_limit_accepts_any_movement() -> None:
    for no_limit in (None, "", 0, 0.0, "0"):
        check(Decimal("50000"), no_limit)


def test_the_limit_itself_is_allowed_and_one_pound_more_is_not() -> None:
    check(Decimal("1000"), 1000)
    check(Decimal("999.99"), 1000)
    with pytest.raises(ValidationError) as refused:
        check(Decimal("1000.01"), 1000)
    # The message has to name the number the employee hit, not just say "not allowed".
    assert "1000" in str(refused.value)


def test_the_limit_is_a_setting_the_owner_can_change() -> None:
    definition = get_definition("pos.cash_movement_limit")
    assert definition.type.value == "number"
    assert definition.default == 0
    assert definition.min_value == 0
    # Zero is the documented "no cap", so it must validate rather than be rejected as falsy.
    assert definition.validate(0) == 0
    assert definition.validate(750) == 750
    with pytest.raises(ValueError):
        definition.validate(-1)


def test_the_registry_calls_the_cap_enforced() -> None:
    assert "pos.cash_movement_limit" in ENFORCED_KEYS

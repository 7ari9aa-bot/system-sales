"""The assistant's dialect: a closed list, defaulted from the shop's currency, never free text.

The owner decided the dialect is a setting the shop owner controls, with a default derived from the
currency. ``identity.dialects`` owns the list and the resolution; the assistant only supplies fixed
wording per key. What this file pins: the choices are a closed list (so nothing a shop types can
reach the system prompt), an unset shop gets its currency's dialect, an explicit choice always wins
over the currency, and an unknown value fails closed to the neutral register rather than to a guess.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence import dialect
from app.modules.identity import dialects


def test_the_assistants_mirror_equals_the_settings_owner() -> None:
    """``ai`` keeps a copy so it need not import ``identity``; this keeps the copy honest."""
    assert dialect.CHOICES == dialects.CHOICES
    assert dialect.NEUTRAL == dialects.NEUTRAL
    assert dialect.CURRENCY_DEFAULT == dialects.CURRENCY_DEFAULT


@pytest.mark.parametrize("stored", [None, "", "egyptian", "gulf", "klingon", "EGYPTIAN"])
@pytest.mark.parametrize("currency", [None, "", "EGP", "SAR", "MAD", "JOD", "USD", "egp"])
def test_the_mirror_resolves_exactly_like_the_owner(stored, currency) -> None:
    assert dialect.resolve(stored, currency) == dialects.resolve(stored, currency)[0]


def test_every_listed_dialect_has_exactly_one_directive_and_nothing_else_does() -> None:
    assert set(dialect.DIRECTIVES) == set(dialects.CHOICES)
    assert set(dialects.CHOICES) == {"egyptian", "gulf", "levantine", "maghrebi", "msa"}
    for key in dialects.CHOICES:
        text = dialect.directive_for(key)
        assert text and text.strip() == text
        assert len(text) < 400  # a style hint, not a second system prompt


def test_each_directive_is_fixed_text_that_asks_only_for_style() -> None:
    for key in dialects.CHOICES:
        text = dialect.directive_for(key)
        # style only: it must not loosen a rule the main prompt sets
        for forbidden in ("تجاهل", "ignore", "بدل", "override", "مش لازم أداة"):
            assert forbidden not in text
        # and it keeps the numbers exact
        assert "الأرقام" in text


@pytest.mark.parametrize(
    ("currency", "expected"),
    [
        ("EGP", "egyptian"),
        ("SAR", "gulf"),
        ("AED", "gulf"),
        ("QAR", "gulf"),
        ("KWD", "gulf"),
        ("JOD", "levantine"),
        ("MAD", "maghrebi"),
        ("egp", "egyptian"),  # a currency code is case-insensitive, a dialect key is not
    ],
)
def test_an_unset_shop_gets_the_dialect_of_its_currency(currency: str, expected: str) -> None:
    assert dialects.resolve(None, currency) == (expected, dialects.SOURCE_CURRENCY)
    assert dialects.resolve("", currency) == (expected, dialects.SOURCE_CURRENCY)


@pytest.mark.parametrize("currency", ["USD", "zzz", "", None])
def test_a_currency_with_no_dialect_gets_the_neutral_register(currency: str | None) -> None:
    assert dialects.resolve(None, currency) == ("msa", dialects.SOURCE_DEFAULT)


def test_an_explicit_choice_beats_the_currency_and_says_so() -> None:
    assert dialects.resolve("gulf", "EGP") == ("gulf", dialects.SOURCE_OWNER)
    assert dialects.resolve("msa", "SAR") == ("msa", dialects.SOURCE_OWNER)


@pytest.mark.parametrize("stored", ["klingon", "EGYPTIAN", "egyptian ", "<script>"])
def test_an_unknown_stored_value_fails_closed_to_neutral_not_to_the_currency(stored: str) -> None:
    # a value that is not on the list is not a choice the owner made; guessing from the currency
    # would be inventing one
    assert dialects.resolve(stored, "EGP") == ("msa", dialects.SOURCE_DEFAULT)


def test_directive_for_an_unknown_key_is_the_neutral_one() -> None:
    assert dialect.directive_for("nope") == dialect.directive_for("msa")
    assert dialect.directive_for(None) == dialect.directive_for("msa")


def test_the_currency_map_only_points_at_listed_dialects() -> None:
    for currency, key in dialects.CURRENCY_DEFAULT.items():
        assert key in dialects.CHOICES, currency
    assert dialects.NEUTRAL in dialects.CHOICES


def test_is_valid_accepts_only_the_list_and_the_empty_clear() -> None:
    assert dialects.is_valid("egyptian")
    assert dialects.is_valid("")  # empty clears back to the currency default
    assert dialects.is_valid(None)
    assert not dialects.is_valid("Egyptian")
    assert not dialects.is_valid("egyptian ")
    assert not dialects.is_valid("x" * 64)
    assert not dialects.is_valid("<script>")


def test_a_shop_gets_the_directive_of_its_resolved_dialect() -> None:
    assert dialect.directive_for_shop(None, "EGP") == dialect.directive_for("egyptian")
    assert dialect.directive_for_shop("gulf", "EGP") == dialect.directive_for("gulf")
    assert dialect.directive_for_shop("klingon", "EGP") == dialect.directive_for("msa")
    assert dialect.directive_for_shop(None, None) == dialect.directive_for("msa")


def test_the_refusal_names_the_choices_and_never_echoes_a_long_value() -> None:
    message = dialects.dialect_refusal("x" * 500)
    assert message is not None and len(message) < 200
    for key in dialects.CHOICES:
        assert key in message
    assert dialects.dialect_refusal("gulf") is None
    assert dialects.dialect_refusal("") is None

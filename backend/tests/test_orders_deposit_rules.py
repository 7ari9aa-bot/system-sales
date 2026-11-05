"""Deposit rules are arithmetic, so they are tested without a database.

Every case below is a way a deposit amount can become money the merchant cannot
collect or the customer was never told about. The spec (Customer Commerce §6.3,
§12.11) demands a deterministic engine and forbids the LLM from computing these
numbers, which only holds if the engine is one pure function with no session.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.orders.deposit import (
    BASE_GRAND_TOTAL,
    BASE_ITEMS_AFTER_DISCOUNTS,
    TYPE_FIXED,
    TYPE_NONE,
    TYPE_PERCENTAGE,
    DepositRule,
    deposit_for,
    deposit_refusal,
    remaining_balance,
)


def rule(
    deposit_type: str = TYPE_PERCENTAGE,
    value: str = "20",
    base: str = BASE_GRAND_TOTAL,
    minimum: str | None = None,
    maximum: str | None = None,
) -> DepositRule:
    return DepositRule(
        deposit_type=deposit_type,
        deposit_value=Decimal(value),
        calculation_base=base,
        minimum_deposit=None if minimum is None else Decimal(minimum),
        maximum_deposit=None if maximum is None else Decimal(maximum),
    )


def totals(subtotal: str = "2000", discount: str = "0", shipping: str = "100") -> dict:
    """The spec's worked example: 2,000 goods + 100 shipping = 2,100 grand total."""
    return {
        "subtotal": Decimal(subtotal),
        "discount_total": Decimal(discount),
        "shipping_total": Decimal(shipping),
        "grand_total": Decimal(subtotal) - Decimal(discount) + Decimal(shipping),
    }


class TestDepositFor:
    def test_percentage_of_grand_total_matches_the_spec_example(self) -> None:
        assert deposit_for(rule(value="20"), currency="EGP", **totals()) == Decimal("420.00")

    def test_percentage_of_subtotal_after_discounts_ignores_shipping(self) -> None:
        policy = rule(value="20", base=BASE_ITEMS_AFTER_DISCOUNTS)
        assert deposit_for(policy, currency="EGP", **totals()) == Decimal("400.00")

    def test_discount_reduces_the_base_when_goods_are_the_base(self) -> None:
        policy = rule(value="20", base=BASE_ITEMS_AFTER_DISCOUNTS)
        assert deposit_for(policy, currency="EGP", **totals(discount="500")) == Decimal("300.00")

    @pytest.mark.parametrize("minimum,expected", [(None, "0.00"), ("10", "10.00")])
    def test_discount_beyond_items_floors_the_base_before_bands(self, minimum, expected):
        policy = rule(value="20", base=BASE_ITEMS_AFTER_DISCOUNTS, minimum=minimum)
        assert deposit_for(
            policy, currency="EGP", **totals(subtotal="100", discount="150", shipping="100")
        ) == Decimal(expected)

    def test_fixed_ignores_both_the_base_and_the_discount(self) -> None:
        policy = rule(TYPE_FIXED, value="150", base=BASE_ITEMS_AFTER_DISCOUNTS)
        money = totals(subtotal="2000", discount="500")
        assert deposit_for(policy, currency="EGP", **money) == Decimal("150.00")

    def test_none_asks_for_nothing(self) -> None:
        assert deposit_for(rule(TYPE_NONE), currency="EGP", **totals()) == Decimal("0.00")

    def test_minimum_clamps_a_small_percentage_up(self) -> None:
        assert deposit_for(rule(value="1", minimum="100"), currency="EGP", **totals()) == (
            Decimal("100.00")
        )

    def test_maximum_clamps_a_big_percentage_down(self) -> None:
        assert deposit_for(rule(value="50", maximum="300"), currency="EGP", **totals()) == (
            Decimal("300.00")
        )

    def test_deposit_never_exceeds_the_grand_total(self) -> None:
        # A fixed deposit larger than a small order must not bill more than the
        # order is worth: the customer would be holding a credit no one issued.
        # The minimum is applied first, so the cap is what has the last word.
        policy = rule(TYPE_FIXED, value="5000", minimum="6000")
        assert deposit_for(policy, currency="EGP", **totals(subtotal="100", shipping="0")) == (
            Decimal("100.00")
        )

    def test_zero_total_never_produces_a_deposit(self) -> None:
        policy = rule(TYPE_FIXED, value="150")
        assert deposit_for(policy, currency="EGP", **totals(subtotal="0", shipping="0")) == (
            Decimal("0.00")
        )

    def test_rounding_is_half_up_at_the_currency_scale(self) -> None:
        # 20% of 33.33 is 6.666: the provider is asked for 6.67, not 6.66 and
        # not 6.7.
        policy = rule(value="20")
        assert deposit_for(policy, currency="EGP", **totals(subtotal="33.33", shipping="0")) == (
            Decimal("6.67")
        )

    def test_minimum_applies_before_rounding_and_is_capped_at_order_total(self) -> None:
        policy = rule(value="1", minimum="0.50")
        assert deposit_for(policy, currency="EGP", **totals(subtotal="0.01", shipping="0")) == (
            Decimal("0.01")
        )

    def test_negative_fraction_is_not_rounded_into_a_valid_input(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            deposit_for(rule(), currency="EGP", **totals(discount="-0.001"))

    def test_100_percent_prepays_the_whole_order(self) -> None:
        assert deposit_for(rule(value="100"), currency="EGP", **totals()) == Decimal("2100.00")

    def test_a_three_decimal_currency_survives_the_provider_round_trip(self) -> None:
        # §47: the amount the provider is charged is the amount that was decided.
        # IQD is quoted in thirds of a fil, so a two-place quantum would lose a
        # whole minor unit between the engine and the checkout session.
        money = totals(subtotal="100", shipping="0.005")
        assert deposit_for(rule(value="20"), currency="IQD", **money) == Decimal("20.001")

    def test_a_two_decimal_currency_closes_its_inputs_before_it_multiplies(self) -> None:
        # The mirror of the case above. EGP cannot hold a third of a qurush, so
        # 100.005 is priced as the 100.01 the row will actually store: the
        # deposit is computed from the money that exists, never from a number the
        # database is about to rewrite under the caller.
        money = totals(subtotal="100", shipping="0.005")
        assert deposit_for(rule(value="20"), currency="EGP", **money) == Decimal("20.00")

    def test_an_unsupported_currency_is_refused_not_guessed(self) -> None:
        # core/currency keeps a closed table on purpose: assuming 2 decimals for an
        # unlisted code is how an amount is silently rewritten by a fifth of itself.
        with pytest.raises(ValueError, match="currency"):
            deposit_for(rule(), currency="XXX", **totals())

    def test_a_negative_component_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            deposit_for(rule(), currency="EGP", **totals(discount="-500"))


class TestDepositRefusal:
    def test_a_valid_policy_has_no_refusal(self) -> None:
        assert deposit_refusal(rule(), currency="EGP") is None

    def test_percentage_above_one_hundred_is_refused(self) -> None:
        assert deposit_refusal(rule(value="100.01"), currency="EGP") is not None

    def test_zero_percentage_is_refused_because_none_exists_for_that(self) -> None:
        assert deposit_refusal(rule(value="0"), currency="EGP") is not None

    def test_a_negative_fixed_deposit_is_refused(self) -> None:
        assert deposit_refusal(rule(TYPE_FIXED, value="-5"), currency="EGP") is not None

    def test_fixed_without_an_amount_is_refused(self) -> None:
        assert deposit_refusal(rule(TYPE_FIXED, value="0"), currency="EGP") is not None

    def test_an_unknown_type_is_refused_rather_than_treated_as_none(self) -> None:
        # Fail closed: a typo in a stored policy must not silently turn into
        # "collect no deposit" on every order in that shop.
        assert deposit_refusal(DepositRule(deposit_type="percent"), currency="EGP") is not None

    def test_an_unknown_base_is_refused(self) -> None:
        assert deposit_refusal(rule(base="subtotal_before_discounts"), currency="EGP") is not None

    def test_minimum_above_maximum_is_refused(self) -> None:
        assert deposit_refusal(rule(minimum="500", maximum="100"), currency="EGP") is not None

    def test_none_type_needs_no_value(self) -> None:
        assert deposit_refusal(rule(TYPE_NONE), currency="EGP") is None

    def test_a_currency_that_cannot_be_stored_is_refused(self) -> None:
        assert deposit_refusal(rule(), currency="XXX") is not None


class TestRemainingBalance:
    def test_remaining_is_the_total_less_what_arrived(self) -> None:
        assert remaining_balance(Decimal("2100"), Decimal("420")) == Decimal("1680.00")

    def test_an_over_collected_order_owes_nothing(self) -> None:
        assert remaining_balance(Decimal("100"), Decimal("120")) == Decimal("0.00")

    def test_nothing_paid_leaves_the_whole_total(self) -> None:
        assert remaining_balance(Decimal("2100.00"), Decimal("0")) == Decimal("2100.00")

    def test_the_balance_follows_the_currency_scale_when_one_is_given(self) -> None:
        # A zero-exponent currency is quoted in whole units, so a balance must
        # not come back carrying two decimals the deposit itself never had.
        assert remaining_balance(Decimal("2100.4"), Decimal("420.4"), currency="JPY") == Decimal(
            "1680"
        )

    def test_the_balance_keeps_thirds_of_a_fil(self) -> None:
        assert remaining_balance(Decimal("100.005"), Decimal("20.001"), currency="IQD") == Decimal(
            "80.004"
        )


class TestNonFiniteRulesAreRefused:
    def test_a_nan_percentage_is_a_reason_not_an_exception(self) -> None:
        # Decimal("NaN") > 0 raises InvalidOperation rather than answering, so
        # the refusal has to look at finiteness BEFORE it compares. A stored row
        # that somehow holds NaN must never take down a read path.
        policy = DepositRule(deposit_type=TYPE_PERCENTAGE, deposit_value=Decimal("NaN"))
        assert deposit_refusal(policy, currency="EGP") is not None

    def test_an_infinite_fixed_amount_is_a_reason_not_an_exception(self) -> None:
        policy = DepositRule(deposit_type=TYPE_FIXED, deposit_value=Decimal("Infinity"))
        assert deposit_refusal(policy, currency="EGP") is not None

    def test_an_infinite_band_is_a_reason_not_an_exception(self) -> None:
        policy = DepositRule(
            deposit_type=TYPE_PERCENTAGE,
            deposit_value=Decimal("20"),
            minimum_deposit=Decimal("Infinity"),
        )
        assert deposit_refusal(policy, currency="EGP") is not None

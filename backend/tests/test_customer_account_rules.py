"""Customer account rules: exact money, one sign convention, a limit that actually limits."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.customer_accounts.rules import (
    AccountRuleError,
    apply_deposit,
    balance,
    check_credit_sale,
    money,
    signed_amount,
)

D = Decimal


def test_each_kind_moves_the_balance_the_right_way() -> None:
    assert signed_amount("charge", "100") == D("100.00")  # owes more
    assert signed_amount("payment", "40") == D("-40.00")  # owes less
    assert signed_amount("deposit", "50") == D("-50.00")  # holds credit
    assert signed_amount("deposit_applied", "50") == D("50.00")  # credit used up


def test_adjustments_and_reversals_carry_their_own_sign() -> None:
    assert signed_amount("adjustment", "-5.50") == D("-5.50")
    assert signed_amount("reversal", "100") == D("100.00")
    with pytest.raises(AccountRuleError):
        signed_amount("adjustment", "0")


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "", "NaN", "Infinity", "1.005", "1e12"])
def test_a_plain_entry_refuses_bad_amounts(bad) -> None:
    with pytest.raises(AccountRuleError):
        signed_amount("charge", bad)


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(AccountRuleError):
        signed_amount("gift", "10")


def test_money_is_exact_not_float() -> None:
    assert money("0.10") + money("0.20") == D("0.30")
    assert balance([signed_amount("charge", "0.10"), signed_amount("charge", "0.20")]) == D("0.30")


def test_a_full_story_balances_to_zero() -> None:
    entries = [
        signed_amount("deposit", "200"),  # paid 200 in advance
        signed_amount("deposit_applied", "200"),  # used against the sale
        signed_amount("charge", "300"),  # the rest on account
        signed_amount("payment", "100"),
        signed_amount("payment", "200"),
    ]
    assert balance(entries) == D("0.00")


def test_a_reversal_cancels_a_mistake_exactly() -> None:
    wrong = signed_amount("charge", "123.45")
    undo = signed_amount("reversal", str(-wrong))
    assert balance([wrong, undo]) == D("0.00")


# ---- the credit limit ----


def test_a_sale_within_the_limit_goes_on_account() -> None:
    r = check_credit_sale(
        current_balance=D("100"), sale_total=D("300"), paid_now=D("0"), credit_limit=D("500")
    )
    assert r.allowed and r.owed_after == D("400.00") and r.available_after == D("100.00")


def test_a_sale_over_the_limit_is_refused_and_says_by_how_much() -> None:
    r = check_credit_sale(
        current_balance=D("400"), sale_total=D("300"), paid_now=D("0"), credit_limit=D("500")
    )
    assert not r.allowed and "200" in r.reason


def test_only_the_unpaid_part_counts_against_the_limit() -> None:
    r = check_credit_sale(
        current_balance=D("400"), sale_total=D("300"), paid_now=D("250"), credit_limit=D("500")
    )
    assert r.allowed and r.owed_after == D("450.00")


def test_exactly_at_the_limit_is_allowed() -> None:
    r = check_credit_sale(
        current_balance=D("0"), sale_total=D("500"), paid_now=D("0"), credit_limit=D("500")
    )
    assert r.allowed and r.available_after == D("0.00")


def test_a_zero_limit_means_no_credit_but_a_paid_sale_still_works() -> None:
    assert not check_credit_sale(
        current_balance=D("0"), sale_total=D("10"), paid_now=D("0"), credit_limit=D("0")
    ).allowed
    assert check_credit_sale(
        current_balance=D("0"), sale_total=D("10"), paid_now=D("10"), credit_limit=D("0")
    ).allowed


def test_no_limit_set_means_unlimited() -> None:
    assert check_credit_sale(
        current_balance=D("9999"), sale_total=D("9999"), paid_now=D("0"), credit_limit=None
    ).allowed


def test_a_blocked_customer_gets_no_credit_but_can_still_pay_cash() -> None:
    assert not check_credit_sale(
        current_balance=D("0"),
        sale_total=D("10"),
        paid_now=D("0"),
        credit_limit=None,
        blocked=True,
    ).allowed
    assert check_credit_sale(
        current_balance=D("0"),
        sale_total=D("10"),
        paid_now=D("10"),
        credit_limit=None,
        blocked=True,
    ).allowed


def test_an_unused_deposit_counts_in_the_customers_favour() -> None:
    # holds 200 credit (balance -200), buys 300 on account, limit 100: owes 100 after, allowed
    r = check_credit_sale(
        current_balance=D("-200"), sale_total=D("300"), paid_now=D("0"), credit_limit=D("100")
    )
    assert r.allowed and r.owed_after == D("100.00")


@pytest.mark.parametrize("total,paid", [("0", "0"), ("-5", "0"), ("10", "-1"), ("10", "11")])
def test_impossible_sales_are_refused(total, paid) -> None:
    with pytest.raises(AccountRuleError):
        check_credit_sale(
            current_balance=D("0"), sale_total=D(total), paid_now=D(paid), credit_limit=None
        )


# ---- using a deposit ----


def test_a_deposit_covers_the_sale_up_to_what_is_held() -> None:
    assert apply_deposit(balance_now=D("-200"), sale_total=D("150")) == D("150")
    assert apply_deposit(balance_now=D("-200"), sale_total=D("500")) == D("200")


def test_a_customer_who_owes_has_no_deposit_to_use() -> None:
    assert apply_deposit(balance_now=D("80"), sale_total=D("100")) == D("0.00")
    assert apply_deposit(balance_now=D("0"), sale_total=D("100")) == D("0.00")

"""Tax arithmetic: exact, and the document is always the sum of its printed lines."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.applications.apparel.modules.taxation.calc import split_document, split_line

D = Decimal


def test_a_shelf_price_keeps_its_total_and_the_tax_is_extracted() -> None:
    # 114.00 on the hanger with 14% VAT inside: net 100.00, tax 14.00, the customer pays 114.00
    line = split_line(D("114.00"), D("0.14"))
    assert (line.net, line.tax, line.gross) == (D("100.00"), D("14.00"), D("114.00"))


def test_the_customer_never_pays_more_because_vat_was_turned_on() -> None:
    for price in ("1.00", "9.99", "199.50", "349.00", "1234.56"):
        line = split_line(D(price), D("0.14"))
        assert line.gross == D(price)
        assert line.net + line.tax == line.gross


def test_a_price_before_tax_gets_the_tax_added_on_top() -> None:
    line = split_line(D("100.00"), D("0.14"), prices_include_tax=False)
    assert (line.net, line.tax, line.gross) == (D("100.00"), D("14.00"), D("114.00"))


def test_zero_rated_and_exempt_lines_carry_no_tax() -> None:
    line = split_line(D("250.00"), D("0"))
    assert (line.net, line.tax, line.gross) == (D("250.00"), D("0.00"), D("250.00"))


def test_half_a_piaster_rounds_up_not_to_even() -> None:
    # 0.01 inclusive at 14%: net 0.00877 -> 0.01, tax 0.00. A bankers-rounding bug flips these.
    assert split_line(D("0.01"), D("0.14")).tax == D("0.00")
    # 1.15 / 1.14 = 1.00877 -> 1.01 ; tax 0.14
    assert split_line(D("1.15"), D("0.14")).net == D("1.01")


def test_the_document_tax_is_the_sum_of_the_rounded_lines() -> None:
    # Three 0.99 lines: each tax rounds on its own; rounding the 2.97 total once would disagree.
    doc = split_document([(D("0.99"), D("0.14"))] * 3)
    assert doc.tax == sum(line.tax for line in doc.lines)
    assert doc.net + doc.tax == doc.gross == D("2.97")


def test_mixed_rates_in_one_basket() -> None:
    doc = split_document([(D("114.00"), D("0.14")), (D("50.00"), D("0")), (D("228.00"), D("0.14"))])
    assert doc.tax == D("42.00")
    assert doc.gross == D("392.00")
    assert doc.net == D("350.00")


@pytest.mark.parametrize("bad", ["-1", "-0.01"])
def test_a_negative_amount_is_refused(bad) -> None:
    with pytest.raises(ValueError):
        split_line(D(bad), D("0.14"))


@pytest.mark.parametrize("bad_rate", ["-0.1", "1.01", "14"])
def test_a_rate_that_is_not_a_fraction_is_refused(bad_rate) -> None:
    with pytest.raises(ValueError):
        split_line(D("10.00"), D(bad_rate))


def test_the_invariant_holds_over_a_wide_sweep() -> None:
    # net + tax == gross, always, for every piaster from 0.00 to 50.00 at three rates
    for cents in range(0, 5001):
        amount = D(cents) / D(100)
        for rate in (D("0.14"), D("0.05"), D("0")):
            line = split_line(amount, rate)
            assert line.net + line.tax == line.gross, (amount, rate)
            assert line.tax >= 0


# ---- spreading an order-level discount ----

from app.applications.apparel.modules.taxation.calc import allocate_discount  # noqa: E402


def test_the_shares_add_up_to_the_discount_exactly() -> None:
    nets = [D("33.33"), D("33.33"), D("33.34")]
    shares = allocate_discount(nets, D("10.00"))
    assert sum(shares) == D("10.00")


def test_a_discount_is_spread_in_proportion() -> None:
    assert allocate_discount([D("100.00"), D("300.00")], D("40.00")) == [D("10.00"), D("30.00")]


def test_no_line_goes_below_zero() -> None:
    shares = allocate_discount([D("1.00"), D("99.00")], D("100.00"))
    assert sum(shares) == D("100.00")
    assert all(s >= 0 for s in shares)
    assert [n - s for n, s in zip([D("1.00"), D("99.00")], shares, strict=True)] == [D("0.00")] * 2


def test_no_discount_no_shares() -> None:
    assert allocate_discount([D("10.00"), D("20.00")], D("0")) == [D("0.00"), D("0.00")]


def test_a_discount_larger_than_the_basket_is_refused() -> None:
    with pytest.raises(ValueError):
        allocate_discount([D("10.00")], D("10.01"))


def test_the_sweep_never_creates_or_loses_a_piaster() -> None:
    nets = [D("19.99"), D("0.01"), D("250.50"), D("7.77")]
    total = sum(nets)
    for cents in range(0, int(total * 100) + 1, 37):
        discount = D(cents) / D(100)
        shares = allocate_discount(nets, discount)
        assert sum(shares) == discount, discount
        assert all(0 <= s <= n for s, n in zip(shares, nets, strict=True)), discount

"""Tender rules are pure arithmetic: tested without a database."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.errors import ValidationError
from app.applications.apparel.modules.pos.tender import (
    TenderLine,
    expected_drawer_cash,
    parse_lines,
    settle,
    variance,
)

D = Decimal
ALL = ("cash", "card", "wallet", "bank_transfer")


def test_cash_only_sale_with_change() -> None:
    result = settle(
        [TenderLine("cash", D("170"), tendered=D("200"))], total=D("170"), allowed_methods=ALL
    )
    assert result.paid == D("170.00")
    assert result.cash_kept == D("170.00")
    assert result.tendered_cash == D("200.00")
    assert result.change == D("30.00")


def test_exact_cash_has_no_change() -> None:
    result = settle([TenderLine("cash", D("50"))], total=D("50"), allowed_methods=ALL)
    assert result.change == D("0.00")
    assert result.tendered_cash == D("50.00")


def test_split_cash_and_card() -> None:
    result = settle(
        [
            TenderLine("cash", D("100"), tendered=D("100")),
            TenderLine("card", D("70"), reference="A1"),
        ],
        total=D("170"),
        allowed_methods=ALL,
        reference_required=("card",),
    )
    assert result.by_method == {"cash": D("100.00"), "card": D("70.00")}
    assert result.cash_kept == D("100.00")
    assert result.change == D("0.00")


def test_method_not_enabled_is_refused() -> None:
    with pytest.raises(ValidationError, match="not enabled"):
        settle([TenderLine("card", D("10"))], total=D("10"), allowed_methods=("cash",))


def test_reference_required_for_card() -> None:
    with pytest.raises(ValidationError, match="reference"):
        settle(
            [TenderLine("card", D("10"))],
            total=D("10"),
            allowed_methods=ALL,
            reference_required=("card",),
        )


def test_cash_tendered_below_amount_is_refused() -> None:
    with pytest.raises(ValidationError, match="less than"):
        settle(
            [TenderLine("cash", D("100"), tendered=D("90"))], total=D("100"), allowed_methods=ALL
        )


def test_non_cash_cannot_be_over_tendered() -> None:
    with pytest.raises(ValidationError, match="only cash"):
        settle(
            [TenderLine("card", D("100"), tendered=D("120"))], total=D("100"), allowed_methods=ALL
        )


def test_short_payment_is_refused() -> None:
    with pytest.raises(ValidationError, match="do not cover"):
        settle([TenderLine("cash", D("40"))], total=D("50"), allowed_methods=ALL)


def test_over_collection_is_refused() -> None:
    with pytest.raises(ValidationError, match="exceed"):
        settle(
            [TenderLine("cash", D("40")), TenderLine("card", D("40"))],
            total=D("50"),
            allowed_methods=ALL,
        )


def test_no_lines_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        settle([], total=D("10"), allowed_methods=ALL)


def test_parse_lines_validates_shape() -> None:
    lines = parse_lines([{"method": "cash", "amount": "12.5", "tendered": "20"}])
    assert lines == [TenderLine("cash", D("12.50"), D("20.00"), None)]
    assert parse_lines(None) == []
    with pytest.raises(ValidationError):
        parse_lines("cash")
    with pytest.raises(ValidationError, match="greater than zero"):
        parse_lines([{"method": "cash", "amount": "0"}])
    with pytest.raises(ValidationError, match="valid number"):
        parse_lines([{"method": "cash", "amount": "abc"}])
    with pytest.raises(ValidationError, match="required"):
        parse_lines([{"amount": "5"}])


def test_expected_drawer_cash_from_ledger() -> None:
    rows = [
        ("in", "cash_sale", D("100")),
        ("in", "cash_sale", D("50")),
        ("out", "cash_refund", D("30")),
        ("out", "cash_drop", D("80")),
        ("in", "pay_in", D("10")),
    ]
    assert expected_drawer_cash(opening_float=D("200"), movements=rows) == D("250.00")


def test_expected_drawer_cash_rejects_bad_direction() -> None:
    with pytest.raises(ValidationError):
        expected_drawer_cash(opening_float=D("0"), movements=[("sideways", "x", D("1"))])


def test_variance_sign() -> None:
    assert variance(counted=D("245"), expected=D("250")) == D("-5.00")
    assert variance(counted=D("255"), expected=D("250")) == D("5.00")

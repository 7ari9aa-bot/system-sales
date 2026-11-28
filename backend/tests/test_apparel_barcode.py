"""Internal EAN-13 barcodes: numbering, validity and the bars a scanner reads. No database.

The reference bar patterns below were produced by an independent, widely used barcode library
(python-barcode), not by this code: a table typed from memory can look right and still draw a
barcode no scanner will read, so the drawing is pinned to numbers known to scan.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.modules.catalog.apparel.barcode import (
    MAX_SEQUENCE,
    bars,
    check_digit,
    internal_ean13,
    is_internal,
    is_valid_ean13,
)
from app.modules.errors import ValidationError

# number -> its 95 modules, from the reference library
_REFERENCE = {
    "4006381333931": (
        "101000110101001110101111011110100010010110011010"
        "10100001010000101000010111010010000101100110101"
    ),
    "5901234123457": (
        "101000101101001110110011001001101111010011101010"
        "10110011011011001000010101110010011101000100101"
    ),
    "2000000000015": (
        "101000110100011010100111010011100011010100111010"
        "10111001011100101110010111001011001101001110101"
    ),
}


@pytest.mark.parametrize(("number", "pattern"), _REFERENCE.items())
def test_the_bars_match_the_reference_library(number: str, pattern: str) -> None:
    assert bars(number) == pattern
    assert len(pattern) == 95


def test_the_check_digit_matches_known_real_products() -> None:
    assert check_digit("400638133393") == 1
    assert check_digit("590123412345") == 7
    assert check_digit("890103086527") == 5


def test_sequence_numbers_are_valid_eans_in_the_in_store_range() -> None:
    for sequence in (1, 2, 7, 123456, MAX_SEQUENCE):
        code = internal_ean13(sequence)
        assert len(code) == 13 and is_valid_ean13(code) and is_internal(code)
        assert code.startswith("2")  # GS1 reserves 20-29 for in-store use


def test_known_internal_numbers() -> None:
    assert internal_ean13(1) == "2000000000015"
    assert internal_ean13(7) == "2000000000077"
    assert internal_ean13(123456) == "2000001234563"


def test_consecutive_sequences_never_repeat() -> None:
    codes = [internal_ean13(n) for n in range(1, 5001)]
    assert len(set(codes)) == 5000


def test_a_manufacturers_barcode_is_valid_but_not_internal() -> None:
    assert is_valid_ean13("4006381333931") and not is_internal("4006381333931")


def test_a_mistyped_barcode_is_caught_by_its_check_digit() -> None:
    assert not is_valid_ean13("4006381333932")  # last digit wrong
    assert not is_valid_ean13("4006381333391")  # two digits swapped
    assert not is_valid_ean13("400638133393")  # too short
    assert not is_valid_ean13("40063813339311")  # too long
    assert not is_valid_ean13("40063813339A1")  # not digits
    assert not is_valid_ean13("")


def test_a_single_wrong_digit_is_always_caught() -> None:
    good = internal_ean13(4242)
    for position in range(13):
        for replacement in "0123456789":
            if replacement == good[position]:
                continue
            assert not is_valid_ean13(good[:position] + replacement + good[position + 1 :])


@pytest.mark.parametrize("bad", [0, -1, MAX_SEQUENCE + 1, 1.5, "7", None, True])
def test_a_bad_sequence_is_refused(bad) -> None:
    with pytest.raises(ValidationError):
        internal_ean13(bad)


def test_the_bars_of_an_invalid_number_are_refused_not_drawn() -> None:
    with pytest.raises(ValidationError):
        bars("4006381333932")


def test_bars_always_start_and_end_with_the_guard_and_have_the_centre_guard() -> None:
    pattern = bars(internal_ean13(99))
    assert pattern[:3] == "101" and pattern[-3:] == "101" and pattern[45:50] == "01010"

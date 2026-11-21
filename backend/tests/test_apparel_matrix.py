"""The size x colour matrix: pure rules, no database."""

from __future__ import annotations

import pytest

from app.modules.catalog.apparel.matrix import (
    COLOR_AXIS,
    MAX_COMBINATIONS,
    SIZE_AXIS,
    build_matrix,
    normalise_size,
    size_sort_key,
)
from app.modules.errors import ValidationError


def _skus(cells):
    return [c.sku for c in cells]


def test_sizes_come_in_rack_order_not_alphabetical() -> None:
    cells = build_matrix(sizes=["XL", "S", "L", "M", "XXL"], colors=["أسود"], sku_prefix="SH")
    assert [c.size for c in cells] == ["S", "M", "L", "XL", "XXL"]


def test_numeric_sizes_sort_by_value_not_as_text() -> None:
    cells = build_matrix(sizes=["42", "38", "40", "100", "9"], colors=["x"], sku_prefix="P")
    assert [c.size for c in cells] == ["9", "38", "40", "42", "100"]


def test_letters_come_before_numbers_and_unknown_last() -> None:
    assert size_sort_key("M") < size_sort_key("38") < size_sort_key("فري سايز")


def test_aliases_fold_to_one_size_so_a_typo_does_not_make_two_variants() -> None:
    assert normalise_size("large") == "L"
    assert normalise_size(" 2xl ") == "XXL"
    assert normalise_size("كبير") == "L"
    cells = build_matrix(sizes=["L", "large", "l", "Large "], colors=["x"], sku_prefix="P")
    assert [c.size for c in cells] == ["L"]


def test_arabic_indic_digits_are_read_as_numbers() -> None:
    assert normalise_size("٤٢") == "42"
    cells = build_matrix(sizes=["٤٢", "٣٨"], colors=["x"], sku_prefix="P")
    assert [c.size for c in cells] == ["38", "42"]


def test_every_combination_is_made_once_with_the_two_axes_set() -> None:
    cells = build_matrix(sizes=["S", "M"], colors=["أسود", "أبيض", "أحمر"], sku_prefix="SH24")
    assert len(cells) == 6
    assert {(c.size, c.color) for c in cells} == {
        (s, c) for s in ("S", "M") for c in ("أسود", "أبيض", "أحمر")
    }
    assert all(set(c.option_values) == {SIZE_AXIS, COLOR_AXIS} for c in cells)


def test_a_colour_written_two_ways_is_one_colour() -> None:
    cells = build_matrix(sizes=["M"], colors=["Red", "red", "RED "], sku_prefix="P")
    assert len(cells) == 1


def test_skus_are_readable_and_unique() -> None:
    cells = build_matrix(
        sizes=["S", "M"],
        colors=["Black", "White"],
        sku_prefix="sh 24",
        color_codes={"Black": "blk", "White": "wht"},
    )
    assert _skus(cells) == ["SH24-BLK-S", "SH24-BLK-M", "SH24-WHT-S", "SH24-WHT-M"]
    assert len(set(_skus(cells))) == len(cells)


def test_two_colours_that_would_share_a_code_are_refused() -> None:
    # "Navy Blue" and "Navy Grey" both start NAV: two variants must not share a SKU
    with pytest.raises(ValidationError, match="share the code"):
        build_matrix(sizes=["M"], colors=["Navy Blue", "Navy Grey"], sku_prefix="P")


def test_colours_with_different_starts_need_no_help() -> None:
    cells = build_matrix(sizes=["M"], colors=["Blue", "Black"], sku_prefix="P")
    assert _skus(cells) == ["P-BLU-M", "P-BLA-M"]


def test_a_clash_can_be_resolved_by_naming_a_code() -> None:
    cells = build_matrix(
        sizes=["M"],
        colors=["Navy Blue", "Navy Grey"],
        sku_prefix="P",
        color_codes={"Navy Blue": "NVB", "Navy Grey": "NVG"},
    )
    assert _skus(cells) == ["P-NVB-M", "P-NVG-M"]


def test_empty_inputs_are_refused_not_turned_into_a_garment_with_no_variants() -> None:
    with pytest.raises(ValidationError):
        build_matrix(sizes=[], colors=["x"], sku_prefix="P")
    with pytest.raises(ValidationError):
        build_matrix(sizes=["M"], colors=[], sku_prefix="P")
    with pytest.raises(ValidationError):
        build_matrix(sizes=["  "], colors=["x"], sku_prefix="P")
    with pytest.raises(ValidationError):
        build_matrix(sizes=["M"], colors=["x"], sku_prefix="---")


def test_an_absurd_matrix_is_a_typo_not_a_range() -> None:
    sizes = [str(n) for n in range(1, 30)]
    colors = [f"c{n}" for n in range(1, 12)]
    assert len(sizes) * len(colors) > MAX_COMBINATIONS
    with pytest.raises(ValidationError, match="more than"):
        build_matrix(sizes=sizes, colors=colors, sku_prefix="P")


def test_arabic_colour_names_make_a_usable_code() -> None:
    cells = build_matrix(sizes=["M"], colors=["أسود"], sku_prefix="SH")
    assert cells[0].sku == "SH-أسو-M"

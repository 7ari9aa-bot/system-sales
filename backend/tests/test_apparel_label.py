"""The printable label: structure, safety and, where a reader is installed, a real scan.

A barcode that looks right can still fail at the till, so the scan test renders the label and
reads it back with an independent decoder (ZXing). It needs two optional tools and skips without
them; the structural tests below always run.
"""

from __future__ import annotations

import re

import pytest

from app.applications.apparel.modules.catalog.apparel.barcode import bars, internal_ean13
from app.applications.apparel.modules.catalog.apparel.label import (
    MODULE_MM,
    QUIET_MODULES,
    SIZES,
    label_svg,
)
from app.modules.errors import ValidationError

CODE = internal_ean13(1234)


def _rects(svg: str) -> list[tuple[float, float]]:
    return [
        (float(x), float(w))
        for x, w in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', svg)
        if float(w) < 20  # the white background rect is the whole label
    ]


@pytest.mark.parametrize("size", sorted(SIZES))
def test_the_label_is_exactly_its_physical_size(size: str) -> None:
    width, height = SIZES[size]
    svg = label_svg(code=CODE, title="قميص", size=size)
    assert f'width="{width}mm" height="{height}mm"' in svg


@pytest.mark.parametrize("size", sorted(SIZES))
def test_the_bars_are_the_barcode_and_leave_the_quiet_zone_blank(size: str) -> None:
    width, _ = SIZES[size]
    rects = _rects(label_svg(code=CODE, title="x", size=size))
    first = min(x for x, _ in rects)
    last = max(x + w for x, w in rects)
    margin = QUIET_MODULES * MODULE_MM
    assert first >= margin - 1e-6, "no blank margin on the left: the scanner would not start"
    assert width - last >= margin - 1e-6, "no blank margin on the right"
    # every bar is a whole number of modules wide, and together they cover the pattern's 1s
    assert all(abs(w / MODULE_MM - round(w / MODULE_MM)) < 1e-2 for _, w in rects)
    assert round(sum(w for _, w in rects) / MODULE_MM) == bars(CODE).count("1")


def test_a_product_name_cannot_inject_markup() -> None:
    svg = label_svg(code=CODE, title='<script>alert(1)</script>"&', variant_text="<b>x</b>")
    assert "<script" not in svg and "<b>" not in svg
    assert "&lt;script&gt;" in svg and "&amp;" in svg


def test_the_standard_dimensions_are_pinned_not_read_back_from_the_code() -> None:
    # GS1 EAN-13: 0.33 mm module (100% size) and 11 blank modules each side. Hard-coded on purpose:
    # comparing the code with its own constants would pass whatever somebody changed them to.
    assert MODULE_MM == 0.33
    assert QUIET_MODULES == 11


def test_the_price_is_rounded_to_piastres_half_up() -> None:
    assert "249.50 ج.م" in label_svg(code=CODE, title="x", price="249.499")
    assert "249.51 ج.م" in label_svg(code=CODE, title="x", price="249.505")
    assert "0 ج.م" in label_svg(code=CODE, title="x", price="0.004")
    assert "1000 ج.م" in label_svg(code=CODE, title="x", price="999.999")


def test_the_digits_and_price_are_printed() -> None:
    svg = label_svg(code=CODE, title="قميص", price="249.5")
    assert CODE in svg
    assert "249.50 ج.م" in svg
    assert "250 ج.م" in label_svg(code=CODE, title="x", price="250.00")


def test_no_price_means_no_price_line() -> None:
    assert "ج.م" not in label_svg(code=CODE, title="x")


def test_a_long_name_is_shortened_not_overflowing() -> None:
    svg = label_svg(code=CODE, title="ا" * 200)
    assert "ا" * 41 not in svg and "…" in svg


@pytest.mark.parametrize("bad", ["-5", "abc", "nan", "inf"])
def test_a_bad_price_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        label_svg(code=CODE, title="x", price=bad)


def test_an_invalid_barcode_is_never_drawn() -> None:
    with pytest.raises(ValidationError):
        label_svg(code="2000000012347", title="x")  # wrong check digit


def test_an_unknown_label_size_is_refused() -> None:
    with pytest.raises(ValidationError):
        label_svg(code=CODE, title="x", size="huge")


def test_every_offered_size_is_wide_enough_to_scan() -> None:
    needed = (95 + 2 * QUIET_MODULES) * MODULE_MM
    for name, (width, _) in SIZES.items():
        assert width >= needed, f"{name} is {width} mm but a scannable EAN-13 needs {needed:.1f}"


@pytest.mark.parametrize("size", sorted(SIZES))
def test_the_label_really_scans_at_thermal_printer_resolution(size: str, tmp_path) -> None:
    zxingcpp = pytest.importorskip("zxingcpp", reason="optional: independent barcode decoder")
    cairosvg = pytest.importorskip("cairosvg", reason="optional: SVG renderer")
    pil_image = pytest.importorskip("PIL.Image")
    for dpi in (203, 300, 406):  # 203 is the common thermal head; the others are finer ones
        png = tmp_path / f"{size}-{dpi}.png"
        cairosvg.svg2png(
            bytestring=label_svg(
                code=CODE, title="قميص", variant_text="أسود / L", size=size
            ).encode("utf-8"),
            write_to=str(png),
            dpi=dpi,
            background_color="white",
        )
        read = zxingcpp.read_barcodes(pil_image.open(png).convert("L"))
        assert [(r.format.name, r.text) for r in read] == [("EAN13", CODE)], (size, dpi)

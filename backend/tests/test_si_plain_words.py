"""The owner reads plain shop language, never the system's own identifiers.

The model sees metric and dimension names (``refund_amount``, ``shipped_orders``) because the tools
need them, and it copies them into answers: "مرتجعات (refund_amount)". The prompt asks it not to;
this layer is the guarantee. It turns every internal name into the shop word, and anything that
still looks like an identifier is cut down to a plain word rather than shown raw."""

from __future__ import annotations

import pytest

from app.applications.apparel.modules.ai.agents.sales_intelligence.plain_words import KNOWN, plain_words


def test_a_known_name_in_brackets_after_its_word_is_dropped_not_doubled():
    assert plain_words("مرتجعات (refund_amount) فيها حاجة") == "مرتجعات فيها حاجة"
    assert plain_words("القنوات (channels) أي واحدة") == "القنوات أي واحدة"
    assert plain_words("الشحن (shipped_orders) أو التوصيل (fulfillment)") == "الشحن أو التوصيل"


def test_a_known_name_on_its_own_becomes_the_shop_word():
    assert plain_words("الـ refund_amount ارتفع") == "المرتجعات ارتفع"
    assert "المبيعات المسلَّمة" in plain_words("delivered_revenue زاد")
    assert "الفلوس المتحصّلة" in plain_words("collected_revenue زاد")
    assert "عدد الأوردرات" in plain_words("orders_placed زاد")


@pytest.mark.parametrize("name", sorted(KNOWN))
def test_no_known_name_survives_in_any_position(name):
    for text in (
        f"{name}",
        f"قيمة {name} النهاردة",
        f"({name})",
        f"**{name}**",
        f"`{name}`",
        f"- {name}: 5",
    ):
        out = plain_words(text)
        assert name not in out, (text, out)


def test_an_unknown_identifier_never_shows_raw():
    out = plain_words("بصّ على some_new_metric_x النهاردة")
    assert "some_new_metric_x" not in out and "_" not in out


def test_numbers_dates_and_arabic_text_are_untouched():
    text = "الإيراد 12,500.50 جنيه في 2026-11-14 بزيادة 12% عن الشهر اللي فات."
    assert plain_words(text) == text


def test_ordinary_english_words_are_left_alone():
    assert plain_words("الطلب جه من Instagram و Facebook") == "الطلب جه من Instagram و Facebook"
    assert plain_words("COD و EGP و SKU") == "COD و EGP و SKU"


def test_urls_and_emails_are_not_mangled():
    text = "https://example.com/a_b_c و x_y@shop.com"
    assert plain_words(text) == text


def test_markdown_structure_survives():
    src = "- المبيعات (delivered_revenue) زادت\n- المرتجعات (refund_amount) قلّت\n\n**ملخص**"
    out = plain_words(src)
    assert out.count("\n- ") == 1 and out.startswith("- ")
    assert "**ملخص**" in out
    assert "_" not in out


def test_empty_and_none_are_safe():
    assert plain_words("") == ""
    assert plain_words(None) == ""


def test_it_is_idempotent():
    once = plain_words("مرتجعات (refund_amount) و delivered_revenue و foo_bar_baz")
    assert plain_words(once) == once


def test_every_registered_metric_has_a_shop_word():
    from app.applications.apparel.modules.analytics.semantic import all_metrics

    missing = [m for m in all_metrics() if m not in KNOWN]
    assert not missing, f"metrics the owner could see raw: {missing}"


def test_every_dimension_a_tool_accepts_has_a_shop_word():
    from app.applications.apparel.modules.analytics.semantic import all_metrics

    dims = {d for m in all_metrics().values() for d in (m.dimensions_allowed or ())}
    missing = sorted(d for d in dims if "_" in d and d not in KNOWN)
    assert not missing, f"dimensions the owner could see raw: {missing}"


def test_a_link_that_contains_a_metric_name_is_not_rewritten():
    text = (
        "التقرير: https://shop.example.com/reports/refund_amount_daily"
        " و mail refund_amount@shop.com"
    )
    assert plain_words(text) == text


@pytest.mark.parametrize(
    ("src", "want"),
    [
        ("قيمة `refund_amount` النهاردة", "قيمة المرتجعات النهاردة"),
        ("قيمة **refund_amount** النهاردة", "قيمة المرتجعات النهاردة"),
        ("**refund_amount**", "المرتجعات"),
    ],
)
def test_formatting_marks_around_a_name_go_with_it(src, want):
    out = plain_words(src)
    assert out == want
    assert "`" not in out


def test_no_double_spaces_or_space_before_punctuation_are_left_behind():
    out = plain_words("المرتجعات (refund_amount) ، والشحن (shipped_orders) .")
    assert "  " not in out
    assert " ،" not in out and " ." not in out


def test_line_breaks_and_blank_lines_are_kept_exactly():
    src = "سطر أول\n\n- نقطة (refund_amount)\n- نقطة تانية\n\n\nآخر"
    out = plain_words(src)
    assert out.count("\n") == src.count("\n")
    assert "\n\n\n" in out


def test_none_and_empty_and_non_text_are_safe():
    assert plain_words(None) == ""
    assert plain_words("") == ""
    assert plain_words(0) == "0"


def test_a_name_inside_a_longer_english_word_is_not_touched():
    assert plain_words("my_channelsmith") != "my_channelsmith" or "_" not in plain_words(
        "my_channelsmith"
    )
    assert plain_words("subchannels") == "subchannels"

"""The richer template shapes Meta documents, built exactly as its reference pages show them.

Sources (read, not remembered):
* templates/components — media and location headers, copy-code and voice-call buttons
* templates/marketing-templates/media-card-carousel-templates — 2 to 10 cards
* templates/marketing-templates/limited-time-offer-templates — MARKETING only, no footer
* templates/authentication-templates/authentication-templates — OTP body, footer, button
* catalogs/catalog-template-messages — the catalog button
"""

import pytest

from app.core.errors import ValidationError
from app.modules.conversations.gateway import whatsapp_templates as wa


def _by_type(components, kind):
    return next(c for c in components if c["type"] == kind)


# --- headers -------------------------------------------------------------------------


def test_a_media_header_carries_the_uploaded_handle_not_a_url():
    components = wa.build_components(
        body="عرض الأسبوع", header_media={"format": "image", "handle": "4::aW1hZ2U="}
    )
    header = components[0]
    assert header == {
        "type": "HEADER",
        "format": "IMAGE",
        "example": {"header_handle": ["4::aW1hZ2U="]},
    }


def test_a_media_header_refuses_a_format_meta_does_not_accept():
    with pytest.raises(ValidationError, match="IMAGE, VIDEO, GIF or DOCUMENT"):
        wa.build_components(body="x", header_media={"format": "PDF", "handle": "4::a"})


def test_a_media_header_without_an_upload_is_refused_before_the_request():
    with pytest.raises(ValidationError, match="uploaded asset handle"):
        wa.build_components(body="x", header_media={"format": "IMAGE", "handle": "  "})


def test_a_location_header_takes_no_parameters_and_is_only_for_utility_or_marketing():
    components = wa.build_components(
        body="طلبك في الطريق", header_location=True, category="UTILITY"
    )
    assert components[0] == {"type": "HEADER", "format": "LOCATION"}
    with pytest.raises(ValidationError, match="UTILITY or MARKETING"):
        wa.build_components(body="x", header_location=True, category="AUTHENTICATION")


def test_a_template_has_one_header_only():
    with pytest.raises(ValidationError, match="one header"):
        wa.build_components(
            body="x", header_text="عنوان", header_media={"format": "IMAGE", "handle": "4::a"}
        )


# --- carousel ------------------------------------------------------------------------


def _card(handle, body=None, buttons=None):
    card = {"header_media": {"format": "IMAGE", "handle": handle}}
    if body is not None:
        card["body"] = body
    if buttons is not None:
        card["buttons"] = buttons
    return card


def test_a_carousel_builds_each_card_from_its_own_header_and_buttons():
    components = wa.build_components(
        body="اختار اللي يعجبك",
        category="MARKETING",
        carousel=[
            _card("4::a", "منتج أ", [{"type": "QUICK_REPLY", "text": "اسأل"}]),
            _card("4::b", "منتج ب", [{"type": "QUICK_REPLY", "text": "اسأل"}]),
        ],
    )
    carousel = _by_type(components, "CAROUSEL")
    assert len(carousel["cards"]) == 2
    first = carousel["cards"][0]["components"]
    assert first[0]["example"]["header_handle"] == ["4::a"]
    assert _by_type(first, "BODY")["text"] == "منتج أ"
    assert _by_type(first, "BUTTONS")["buttons"] == [{"type": "QUICK_REPLY", "text": "اسأل"}]


def test_a_carousel_needs_between_two_and_ten_cards():
    with pytest.raises(ValidationError, match="2 to 10 cards"):
        wa.build_components(body="x", category="MARKETING", carousel=[_card("4::a")])
    with pytest.raises(ValidationError, match="2 to 10 cards"):
        wa.build_components(
            body="x", category="MARKETING", carousel=[_card(f"4::{i}") for i in range(11)]
        )


def test_a_carousel_body_must_be_on_every_card_or_on_none():
    with pytest.raises(ValidationError, match="every card must have one"):
        wa.build_components(
            body="x",
            category="MARKETING",
            carousel=[_card("4::a", "منتج أ"), _card("4::b")],
        )


def test_a_carousel_card_carries_at_most_two_buttons():
    with pytest.raises(ValidationError, match="at most 2 buttons"):
        wa.build_components(
            body="x",
            category="MARKETING",
            carousel=[
                _card(
                    "4::a",
                    buttons=[
                        {"type": "QUICK_REPLY", "text": "أ"},
                        {"type": "QUICK_REPLY", "text": "ب"},
                        {"type": "QUICK_REPLY", "text": "ج"},
                    ],
                ),
                _card("4::b"),
            ],
        )


def test_a_carousel_is_marketing_only():
    with pytest.raises(ValidationError, match="only available in a MARKETING template"):
        wa.build_components(body="x", category="UTILITY", carousel=[_card("4::a"), _card("4::b")])


# --- limited-time offer --------------------------------------------------------------


def test_a_limited_time_offer_carries_its_text_and_expiration_flag():
    components = wa.build_components(
        body="خصم 20%",
        category="MARKETING",
        header_media={"format": "IMAGE", "handle": "4::a"},
        limited_time_offer={"text": "العرض ينتهي قريبًا", "has_expiration": True},
        buttons=[{"type": "COPY_CODE", "example": "SAVE20"}],
    )
    offer = _by_type(components, "LIMITED_TIME_OFFER")
    assert offer["limited_time_offer"] == {"text": "العرض ينتهي قريبًا", "has_expiration": True}
    assert _by_type(components, "BUTTONS")["buttons"] == [{"type": "COPY_CODE", "example": "SAVE20"}]


def test_a_limited_time_offer_is_marketing_only_and_has_no_footer():
    with pytest.raises(ValidationError, match="only available in a MARKETING template"):
        wa.build_components(
            body="x", category="UTILITY", limited_time_offer={"text": "t", "has_expiration": True}
        )
    with pytest.raises(ValidationError, match="cannot carry a footer"):
        wa.build_components(
            body="x",
            category="MARKETING",
            footer="شكرًا",
            limited_time_offer={"text": "t", "has_expiration": False},
        )


def test_a_limited_time_offer_must_say_whether_it_expires():
    with pytest.raises(ValidationError, match="has_expiration"):
        wa.build_components(
            body="x", category="MARKETING", limited_time_offer={"text": "t"}
        )


# --- authentication / OTP ------------------------------------------------------------


def test_an_otp_template_is_meta_body_footer_and_button_and_no_body_of_ours():
    components = wa.build_components(
        category="AUTHENTICATION",
        authentication={
            "add_security_recommendation": True,
            "code_expiration_minutes": 10,
            "otp_type": "copy_code",
        },
    )
    assert components == [
        {"type": "BODY", "add_security_recommendation": True},
        {"type": "FOOTER", "code_expiration_minutes": 10},
        {"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE"}]},
    ]


def test_an_otp_template_defaults_to_a_copy_code_button_and_no_expiry_line():
    components = wa.build_components(category="AUTHENTICATION", authentication={})
    assert components[0] == {"type": "BODY", "add_security_recommendation": True}
    assert _by_type(components, "BUTTONS")["buttons"] == [{"type": "OTP", "otp_type": "COPY_CODE"}]
    assert all(c["type"] != "FOOTER" for c in components)


def test_an_otp_template_cannot_be_handed_our_own_body_footer_or_buttons():
    with pytest.raises(ValidationError, match="written by Meta"):
        wa.build_components(body="كودك هو {{1}}", category="AUTHENTICATION", authentication={})
    with pytest.raises(ValidationError, match="Meta's expiry line"):
        wa.build_components(category="AUTHENTICATION", authentication={}, footer="شكرًا")
    with pytest.raises(ValidationError, match="Meta's own OTP button"):
        wa.build_components(
            category="AUTHENTICATION",
            authentication={},
            buttons=[{"type": "QUICK_REPLY", "text": "إعادة"}],
        )


def test_an_otp_template_must_be_categorized_authentication():
    with pytest.raises(ValidationError, match="categorized AUTHENTICATION"):
        wa.build_components(category="UTILITY", authentication={})


def test_an_otp_expiry_must_be_a_sane_whole_number_of_minutes():
    with pytest.raises(ValidationError, match="code_expiration_minutes"):
        wa.build_components(
            category="AUTHENTICATION", authentication={"code_expiration_minutes": 0}
        )


# --- the remaining buttons -----------------------------------------------------------


def test_a_catalog_button_is_marketing_only():
    components = wa.build_components(
        body="اتفرج على الكتالوج",
        category="MARKETING",
        buttons=[{"type": "CATALOG", "text": "الكتالوج"}],
    )
    assert _by_type(components, "BUTTONS")["buttons"] == [{"type": "CATALOG", "text": "الكتالوج"}]
    with pytest.raises(ValidationError, match="only available in a MARKETING template"):
        wa.build_components(
            body="x", category="UTILITY", buttons=[{"type": "CATALOG", "text": "الكتالوج"}]
        )


def test_a_voice_call_button_needs_only_its_label():
    components = wa.build_components(
        body="اتصل بينا", buttons=[{"type": "VOICE_CALL", "text": "اتصل"}]
    )
    assert _by_type(components, "BUTTONS")["buttons"] == [{"type": "VOICE_CALL", "text": "اتصل"}]


def test_a_copy_code_button_copies_its_example_and_is_capped_at_twenty_characters():
    components = wa.build_components(
        body="كود الخصم", buttons=[{"type": "COPY_CODE", "example": "250FF"}]
    )
    assert _by_type(components, "BUTTONS")["buttons"] == [{"type": "COPY_CODE", "example": "250FF"}]
    with pytest.raises(ValidationError, match="at most 20 characters"):
        wa.build_components(body="x", buttons=[{"type": "COPY_CODE", "example": "X" * 21}])


def test_only_one_copy_code_voice_call_and_catalog_button_each():
    with pytest.raises(ValidationError, match="at most 1 copy-code button"):
        wa.build_components(
            body="x",
            buttons=[{"type": "COPY_CODE", "example": "A"}, {"type": "COPY_CODE", "example": "B"}],
        )
    with pytest.raises(ValidationError, match="at most 1 voice call button"):
        wa.build_components(
            body="x",
            buttons=[{"type": "VOICE_CALL", "text": "أ"}, {"type": "VOICE_CALL", "text": "ب"}],
        )
    with pytest.raises(ValidationError, match="at most 1 catalog button"):
        wa.build_components(
            body="x",
            category="MARKETING",
            buttons=[{"type": "CATALOG", "text": "أ"}, {"type": "CATALOG", "text": "ب"}],
        )


def test_the_whole_set_still_caps_at_ten_buttons():
    buttons = [{"type": "QUICK_REPLY", "text": f"خيار {i}"} for i in range(11)]
    with pytest.raises(ValidationError, match="at most 10 buttons"):
        wa.build_components(body="x", buttons=buttons)


# --- the plain template keeps working ------------------------------------------------


def test_a_plain_body_template_is_unchanged():
    # Meta refuses a body that opens or closes on a variable, so the name sits inside it.
    assert wa.build_components(body="أهلًا يا {{1}}، نورت", body_examples=["أحمد"]) == [
        {"type": "BODY", "text": "أهلًا يا {{1}}، نورت", "example": {"body_text": [["أحمد"]]}}
    ]


def test_a_template_with_nothing_to_show_is_refused():
    with pytest.raises(ValidationError, match="body is required"):
        wa.build_components(header_text="عنوان")

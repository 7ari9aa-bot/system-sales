"""WhatsApp interactive messages: every Meta limit, the exact payload, and the send path.

The limits asserted here are the ones in Meta's reference for reply buttons, list messages and
call-to-action URL messages. They differ between kinds (a list body takes 4096, buttons 1024; a
list header is text only), so each is pinned on its own: one shared constant would hide it.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ValidationError
from app.modules.conversations.gateway import whatsapp_interactive as wi
from app.modules.conversations.gateway.base import OutboundMessage
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter as adapter
from app.modules.conversations.gateway.whatsapp_interactive import build_interactive, preview_text


def _buttons(**over) -> dict:
    spec = {
        "kind": "buttons",
        "body": "Confirm your order?",
        "buttons": [{"id": "yes", "title": "Confirm"}, {"id": "no", "title": "Cancel"}],
    }
    spec.update(over)
    return spec


def _list(**over) -> dict:
    spec = {
        "kind": "list",
        "body": "Pick a shipping option",
        "button": "Options",
        "sections": [
            {
                "title": "Shipping",
                "rows": [
                    {"id": "fast", "title": "Express", "description": "1 day"},
                    {"id": "slow", "title": "Standard"},
                ],
            }
        ],
    }
    spec.update(over)
    return spec


def _cta(**over) -> dict:
    spec = {
        "kind": "cta_url",
        "body": "Track your order",
        "label": "Track",
        "url": "https://fihrist.world/o/123",
    }
    spec.update(over)
    return spec


def _refused(spec: dict, *words: str) -> None:
    with pytest.raises(ValidationError) as caught:
        build_interactive(spec)
    message = str(caught.value)
    for word in words:
        assert word in message, f"{word!r} not in {message!r}"


# ------------------------------------------------------------------ exact payloads


def test_reply_buttons_payload_is_exactly_what_meta_takes():
    assert build_interactive(
        _buttons(footer="Thanks", header={"type": "text", "text": "Order"})
    ) == {
        "type": "button",
        "header": {"type": "text", "text": "Order"},
        "body": {"text": "Confirm your order?"},
        "footer": {"text": "Thanks"},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "yes", "title": "Confirm"}},
                {"type": "reply", "reply": {"id": "no", "title": "Cancel"}},
            ]
        },
    }


def test_list_payload_is_exactly_what_meta_takes():
    assert build_interactive(_list()) == {
        "type": "list",
        "body": {"text": "Pick a shipping option"},
        "action": {
            "button": "Options",
            "sections": [
                {
                    "title": "Shipping",
                    "rows": [
                        {"id": "fast", "title": "Express", "description": "1 day"},
                        {"id": "slow", "title": "Standard"},
                    ],
                }
            ],
        },
    }


def test_link_button_payload_is_exactly_what_meta_takes():
    assert build_interactive(_cta(footer="Dates may change")) == {
        "type": "cta_url",
        "body": {"text": "Track your order"},
        "footer": {"text": "Dates may change"},
        "action": {
            "name": "cta_url",
            "parameters": {"display_text": "Track", "url": "https://fihrist.world/o/123"},
        },
    }


@pytest.mark.parametrize("kind", ["image", "video", "document"])
def test_buttons_and_link_buttons_take_a_media_header(kind):
    header = {"type": kind, "link": "https://cdn.example.com/a.bin"}
    expected = {"type": kind, kind: {"link": "https://cdn.example.com/a.bin"}}
    assert build_interactive(_buttons(header=header))["header"] == expected
    assert build_interactive(_cta(header=header))["header"] == expected


def test_arabic_text_is_counted_in_characters_not_bytes():
    twenty = "ا" * wi.BUTTON_TITLE_MAX  # 40 bytes in UTF-8, 20 characters
    built = build_interactive(_buttons(buttons=[{"id": "a", "title": twenty}]))
    assert built["action"]["buttons"][0]["reply"]["title"] == twenty


# ------------------------------------------------------------------ the kind


# "flow" used to be listed here: it is a real kind now, built in whatsapp_flows.
@pytest.mark.parametrize("kind", [None, "", "carousel", 3])
def test_an_unknown_kind_is_refused(kind):
    _refused({"kind": kind, "body": "x"}, "kind")


@pytest.mark.parametrize("spec", [None, [], "buttons", 5])
def test_a_spec_that_is_not_an_object_is_refused(spec):
    _refused(spec, "object")


# ------------------------------------------------------------------ reply buttons


def test_button_limits_are_the_documented_ones():
    assert (wi.BUTTONS_BODY_MAX, wi.BUTTONS_MAX, wi.BUTTON_TITLE_MAX, wi.BUTTON_ID_MAX) == (
        1024,
        3,
        20,
        256,
    )


def test_body_is_required_and_capped_at_1024():
    _refused(_buttons(body=""), "body", "required")
    _refused(_buttons(body="   "), "body", "required")
    _refused(_buttons(body="x" * 1025), "body", "1024")
    assert build_interactive(_buttons(body="x" * 1024))


def test_one_to_three_buttons():
    _refused(_buttons(buttons=[]), "buttons")
    _refused(_buttons(buttons="yes"), "buttons")
    four = [{"id": str(i), "title": f"B{i}"} for i in range(4)]
    _refused(_buttons(buttons=four), "buttons", "3")
    assert build_interactive(_buttons(buttons=four[:3]))


def test_button_title_is_required_and_capped_at_20():
    _refused(_buttons(buttons=[{"id": "a", "title": ""}]), "buttons[0].title", "required")
    _refused(_buttons(buttons=[{"id": "a", "title": "x" * 21}]), "buttons[0].title", "20")


def test_button_id_is_required_and_capped_at_256():
    _refused(_buttons(buttons=[{"title": "A"}]), "buttons[0].id", "required")
    _refused(_buttons(buttons=[{"id": "x" * 257, "title": "A"}]), "buttons[0].id", "256")
    assert build_interactive(_buttons(buttons=[{"id": "x" * 256, "title": "A"}]))


def test_button_titles_must_be_unique_ignoring_case():
    twin = [{"id": "a", "title": "Yes"}, {"id": "b", "title": "yes"}]
    _refused(_buttons(buttons=twin), "buttons[1].title", "repeats")


def test_button_ids_must_be_unique():
    twin = [{"id": "a", "title": "Yes"}, {"id": "a", "title": "No"}]
    _refused(_buttons(buttons=twin), "buttons[1].id", "repeats")


def test_a_button_that_is_not_an_object_is_refused():
    _refused(_buttons(buttons=["Yes"]), "buttons[0]")


# ------------------------------------------------------------------ list


def test_list_limits_are_the_documented_ones():
    assert (
        wi.LIST_BODY_MAX,
        wi.LIST_BUTTON_MAX,
        wi.LIST_SECTIONS_MAX,
        wi.LIST_ROWS_MAX,
        wi.LIST_SECTION_TITLE_MAX,
        wi.LIST_ROW_TITLE_MAX,
        wi.LIST_ROW_DESCRIPTION_MAX,
        wi.LIST_ROW_ID_MAX,
    ) == (4096, 20, 10, 10, 24, 24, 72, 200)


def test_a_list_body_takes_4096_where_buttons_take_1024():
    assert build_interactive(_list(body="x" * 4096))
    _refused(_list(body="x" * 4097), "body", "4096")
    _refused(_buttons(body="x" * 1025), "body", "1024")


def test_a_list_header_can_only_be_text():
    assert build_interactive(_list(header={"type": "text", "text": "Shipping"}))
    for kind in ("image", "video", "document"):
        _refused(_list(header={"type": kind, "link": "https://x.example/a"}), "header", "text")


def test_the_list_button_label_is_required_and_capped_at_20():
    _refused(_list(button=""), "button", "required")
    _refused(_list(button="x" * 21), "button", "20")


def test_a_list_needs_a_section_and_each_needs_a_title_and_a_row():
    _refused(_list(sections=[]), "sections")
    _refused(
        _list(sections=[{"rows": [{"id": "a", "title": "A"}]}]), "sections[0].title", "required"
    )
    _refused(_list(sections=[{"title": "S", "rows": []}]), "sections[0].rows")
    _refused(_list(sections=["S"]), "sections[0]")


def test_section_and_row_text_limits():
    row = {"id": "a", "title": "A"}
    _refused(_list(sections=[{"title": "x" * 25, "rows": [row]}]), "sections[0].title", "24")
    _refused(_list(sections=[{"title": "S", "rows": [{**row, "title": "x" * 25}]}]), "title", "24")
    _refused(
        _list(sections=[{"title": "S", "rows": [{**row, "description": "x" * 73}]}]),
        "description",
        "72",
    )
    _refused(_list(sections=[{"title": "S", "rows": [{**row, "id": "x" * 201}]}]), "id", "200")
    ok = {"id": "x" * 200, "title": "x" * 24, "description": "x" * 72}
    assert build_interactive(_list(sections=[{"title": "x" * 24, "rows": [ok]}]))


def test_ten_rows_in_total_across_sections_not_ten_per_section():
    def section(name, start, count):
        rows = [{"id": f"r{start + i}", "title": f"R{start + i}"} for i in range(count)]
        return {"title": name, "rows": rows}

    assert build_interactive(_list(sections=[section("A", 0, 5), section("B", 5, 5)]))
    _refused(_list(sections=[section("A", 0, 5), section("B", 5, 6)]), "rows", "10", "total")
    _refused(_list(sections=[section("A", 0, 11)]), "rows", "10")


def test_at_most_ten_sections():
    ten = [{"title": f"S{i}", "rows": [{"id": f"r{i}", "title": f"R{i}"}]} for i in range(10)]
    assert build_interactive(_list(sections=ten))
    eleven = [*ten, {"title": "S10", "rows": [{"id": "r10", "title": "R10"}]}]
    _refused(_list(sections=eleven), "sections", "10")


def test_row_ids_must_be_unique_across_the_whole_list():
    sections = [
        {"title": "A", "rows": [{"id": "same", "title": "One"}]},
        {"title": "B", "rows": [{"id": "same", "title": "Two"}]},
    ]
    _refused(_list(sections=sections), "sections[1].rows[0].id", "repeats")


# ------------------------------------------------------------------ link button


def test_link_button_limits_are_the_documented_ones():
    assert (wi.CTA_BODY_MAX, wi.CTA_LABEL_MAX) == (1024, 20)


def test_link_button_label_is_required_and_capped_at_20():
    _refused(_cta(label=""), "label", "required")
    _refused(_cta(label="x" * 21), "label", "20")


@pytest.mark.parametrize(
    "url",
    [
        "",
        None,
        "fihrist.world/o/1",
        "javascript:alert(1)",
        "ftp://x.example/a",
        "https://",
        "//x.y",
    ],
)
def test_link_button_needs_a_real_web_address(url):
    _refused(_cta(url=url), "url")


def test_http_and_https_links_are_accepted():
    assert build_interactive(_cta(url="http://x.example/a"))
    assert build_interactive(_cta(url="https://x.example/a?b=1&c=2"))


# ------------------------------------------------------------------ shared limits


@pytest.mark.parametrize("spec", [_buttons, _list, _cta])
def test_footer_and_text_header_are_capped_at_60(spec):
    _refused(spec(footer="x" * 61), "footer", "60")
    _refused(spec(header={"type": "text", "text": "x" * 61}), "header.text", "60")
    assert spec(footer="x" * 60)


def test_a_header_needs_a_known_type_and_a_link():
    _refused(_buttons(header={"type": "gif", "link": "https://x.example/a"}), "header.type")
    _refused(_buttons(header={"type": "image"}), "header.link", "required")
    _refused(_buttons(header={"type": "image", "link": "ftp://x"}), "header.link")
    _refused(_buttons(header={"type": "text"}), "header.text", "required")
    _refused(_buttons(header="Order"), "header")


def test_an_empty_optional_footer_or_header_is_left_out():
    built = build_interactive(_buttons(footer="  ", header={}))
    assert "footer" not in built and "header" not in built


def test_text_is_trimmed():
    built = build_interactive(_buttons(body="  hi  "))
    assert built["body"]["text"] == "hi"


# ------------------------------------------------------------------ the thread preview


def test_preview_lists_the_choices_so_the_thread_reads_sensibly():
    assert preview_text(_buttons()) == "Confirm your order?\n[ Confirm ]\n[ Cancel ]"
    assert preview_text(_list()) == "Pick a shipping option\n[ Options ]\n- Express\n- Standard"
    assert preview_text(_cta()) == "Track your order\n[ Track ] https://fihrist.world/o/123"


def test_preview_refuses_what_the_builder_refuses():
    with pytest.raises(ValidationError):
        preview_text(_buttons(body=""))


# ------------------------------------------------------------------ the send path


def _outbound(**meta) -> OutboundMessage:
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201000000001",
        body="preview text",
        meta=meta,
    )


def test_the_adapter_sends_an_interactive_message():
    payload = adapter._build_send_payload(_outbound(interactive=_buttons()))
    assert payload["type"] == "interactive"
    assert payload["to"] == "201000000001"
    assert payload["interactive"] == build_interactive(_buttons())
    assert "text" not in payload


def test_the_adapter_quotes_a_reply_on_an_interactive_message():
    payload = adapter._build_send_payload(
        _outbound(interactive=_cta(), reply_to_provider_id="wamid.X")
    )
    assert payload["context"] == {"message_id": "wamid.X"}


def test_a_stored_spec_is_checked_again_at_send_time():
    """What reaches Meta is rebuilt, so a spec stored before a rule tightened cannot slip out."""
    with pytest.raises(ValidationError):
        adapter._build_send_payload(_outbound(interactive=_buttons(body="")))


def test_a_template_wins_over_an_interactive_spec():
    message = _outbound(interactive=_buttons())
    message.template_name = "order_update"
    assert adapter._build_send_payload(message)["type"] == "template"


def test_a_plain_message_is_unchanged():
    assert adapter._build_send_payload(_outbound())["type"] == "text"


# ------------------------------------------------------------------ the customer's tap


def _tap(kind: str, reply: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "201000000001", "profile": {"name": "Ali"}}],
                            "messages": [
                                {
                                    "from": "201000000001",
                                    "id": "wamid.TAP",
                                    "type": "interactive",
                                    "context": {"id": "wamid.OURS"},
                                    "interactive": {"type": kind, kind: reply},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_a_button_tap_keeps_the_id_we_sent_and_threads_to_our_message():
    (tap,) = adapter.parse_inbound(_tap("button_reply", {"id": "yes", "title": "Confirm"}))
    assert (tap.body, tap.content_type) == ("Confirm", "buttons")
    assert tap.reply_to_message_id == "wamid.OURS"
    # The title is only what the customer read; the id is what WE chose and what an automation
    # must key on. It must survive in the stored raw message.
    assert tap.raw["interactive"]["button_reply"]["id"] == "yes"


def test_a_list_tap_keeps_the_row_id_we_sent():
    (tap,) = adapter.parse_inbound(
        _tap("list_reply", {"id": "fast", "title": "Express", "description": "1 day"})
    )
    assert (tap.body, tap.content_type) == ("Express", "list")
    assert tap.raw["interactive"]["list_reply"]["id"] == "fast"


def test_what_we_send_is_what_comes_back():
    """The id in a button we build is the id Meta returns on the tap: one round trip."""
    sent = build_interactive(_buttons())["action"]["buttons"][0]["reply"]
    (tap,) = adapter.parse_inbound(_tap("button_reply", sent))
    assert tap.raw["interactive"]["button_reply"] == sent


# ------------------------------------------------- commerce and location kinds
# Meta's interactive reference gives each of these its own object; a shop that only has buttons and
# lists cannot send a product card, and hand-written shapes are where the field names go wrong.


def test_a_single_product_carries_the_catalogs_own_id():
    built = build_interactive(
        {
            "kind": "product",
            "body": "المنتج ده متوفر",
            "header": {"type": "text", "text": "عرض"},
            "product_retailer_id": "SKU-9",
        }
    )

    assert built["type"] == "product"
    assert built["action"] == {
        "name": "open_product",
        "parameters": {"product_retailer_id": "SKU-9"},
    }
    assert built["body"]["text"] == "المنتج ده متوفر"


def test_a_product_without_a_catalog_id_is_refused_before_meta_sees_it():
    with pytest.raises(ValidationError):
        build_interactive({"kind": "product", "body": "x", "product_retailer_id": ""})


def test_a_product_list_groups_items_into_sections():
    built = build_interactive(
        {
            "kind": "product_list",
            "body": "اختار من اللي عندنا",
            "catalog_id": "CAT-1",
            "sections": [
                {"title": "أحذية", "product_items": [{"product_retailer_id": "A"}, {"product_retailer_id": "B"}]},
                {"product_items": [{"product_retailer_id": "C"}]},
            ],
        }
    )

    assert built["type"] == "product_list"
    assert built["action"]["catalog_id"] == "CAT-1"
    assert built["action"]["sections"][0]["product_items"] == [
        {"product_retailer_id": "A"},
        {"product_retailer_id": "B"},
    ]
    # A section without a title is still valid; the key is simply absent, never empty.
    assert "title" not in built["action"]["sections"][1]


def test_more_than_thirty_products_is_refused():
    with pytest.raises(ValidationError):
        build_interactive(
            {
                "kind": "product_list",
                "body": "x",
                "catalog_id": "CAT-1",
                "sections": [
                    {"product_items": [{"product_retailer_id": f"P{i}"} for i in range(31)]}
                ],
            }
        )


def test_a_catalog_message_may_omit_its_thumbnail():
    with_thumb = build_interactive(
        {"kind": "catalog_message", "body": "شوف الكتالوج", "thumbnail_product_retailer_id": "A"}
    )
    without = build_interactive({"kind": "catalog_message", "body": "شوف الكتالوج"})

    assert with_thumb["action"]["parameters"] == {"thumbnail_product_retailer_id": "A"}
    assert without["action"] == {"name": "catalog_message"}


def test_a_location_request_asks_meta_for_the_picker():
    built = build_interactive({"kind": "location", "body": "ابعتلنا مكانك"})

    assert built == {
        "type": "location_request_message",
        "body": {"text": "ابعتلنا مكانك"},
        "action": {"name": "send_location"},
    }


def test_every_new_kind_has_a_readable_thread_preview():
    previews = [
        preview_text({"kind": "product", "body": "ب", "product_retailer_id": "SKU-9"}),
        preview_text(
            {
                "kind": "product_list",
                "body": "ب",
                "catalog_id": "CAT-1",
                "sections": [{"product_items": [{"product_retailer_id": "A"}]}],
            }
        ),
        preview_text({"kind": "catalog_message", "body": "ب"}),
        preview_text({"kind": "location", "body": "ب"}),
    ]

    assert all("ب" in text and text.strip() for text in previews)
    assert "SKU-9" in previews[0]

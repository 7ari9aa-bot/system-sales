"""WhatsApp's structured payloads: a place, a contact card, the id of the tapped option.

The report's WhatsApp gap (e): the canonical message model flattened structured payloads into a
summary string. A shared location became "📍 Café 12 Nile St" with no coordinates, a shared contact
became one concatenated name-and-number line, and a tapped list option lost its `id` — the thing a
bot actually routes on.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.conversations.gateway.whatsapp_structured import (
    parse_contacts,
    parse_location,
    parse_selection,
    structured_payload,
)
from app.modules.conversations.routers.inbox import _present_structured


def test_a_location_keeps_its_coordinates():
    place = parse_location(
        {
            "location": {
                "latitude": 30.0444,
                "longitude": 31.2357,
                "name": "المخزن",
                "address": "١٢ شارع النيل",
            }
        }
    )
    assert place["latitude"] == 30.0444
    assert place["longitude"] == 31.2357
    assert place["name"] == "المخزن"


def test_a_location_without_coordinates_is_not_a_location():
    """Meta always sends both; a half-filled card cannot open a map."""
    assert parse_location({"location": {"name": "somewhere"}}) is None
    assert parse_location({"location": {"latitude": "30.0", "longitude": 31.2}}) is None
    assert parse_location({"location": {"latitude": 91, "longitude": 31.2}}) is None
    assert parse_location(None) is None


def test_a_contact_card_keeps_its_numbers():
    cards = parse_contacts(
        {
            "contacts": [
                {
                    "name": {"formatted_name": "منى", "first_name": "منى"},
                    "phones": [{"phone": "+201234567890"}, {"phone": "+201111111111"}],
                }
            ]
        }
    )
    assert cards[0]["name"] == "منى"
    assert cards[0]["phones"] == ["+201234567890", "+201111111111"]


def test_a_contact_with_nothing_readable_is_dropped():
    assert parse_contacts({"contacts": [{"name": {}, "phones": []}]}) is None
    assert parse_contacts({"contacts": []}) is None


def test_a_tapped_list_option_keeps_the_id_the_bot_routes_on():
    selection = parse_selection(
        {
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "sku_42", "title": "قميص", "description": "مقاس L"},
            }
        }
    )
    assert selection == {"kind": "list", "id": "sku_42", "title": "قميص", "description": "مقاس L"}


def test_a_tapped_button_keeps_its_id():
    selection = parse_selection({"interactive": {"button_reply": {"id": "yes", "title": "أيوة"}}})
    assert selection["kind"] == "button" and selection["id"] == "yes"


def test_a_template_quick_reply_keeps_its_payload():
    selection = parse_selection({"button": {"text": "تأكيد", "payload": "CONFIRM"}})
    assert selection["kind"] == "template_button" and selection["id"] == "CONFIRM"


def test_an_unknown_shape_yields_nothing_rather_than_passing_it_through():
    assert parse_selection({"interactive": {"type": "nfm_reply"}}) is None
    assert parse_selection({"evil": "payload"}) is None


@pytest.mark.parametrize(
    "content_type, raw, expected_type",
    [
        ("location", {"location": {"latitude": 1.0, "longitude": 2.0}}, "location"),
        ("contact", {"contacts": [{"name": {"formatted_name": "أحمد"}}]}, "contacts"),
        ("buttons", {"interactive": {"button_reply": {"id": "a", "title": "A"}}}, "selection"),
        ("list", {"interactive": {"list_reply": {"id": "b", "title": "B"}}}, "selection"),
        ("text", {"text": {"body": "hi"}}, None),
    ],
)
def test_the_reader_picks_the_right_shape(content_type, raw, expected_type):
    payload = structured_payload(content_type, raw)
    assert (payload or {}).get("type") == expected_type


def test_the_thread_shows_the_map_pin_and_not_the_text_line():
    row = SimpleNamespace(
        direction="inbound",
        content_type="location",
        payload={"raw": {"location": {"latitude": 30.0, "longitude": 31.0, "name": "الفرع"}}},
    )
    assert _present_structured(row)["latitude"] == 30.0


def test_an_outbound_row_has_no_customer_structured_payload():
    row = SimpleNamespace(
        direction="outbound",
        content_type="location",
        payload={"raw": {"location": {"latitude": 30.0, "longitude": 31.0}}},
    )
    assert _present_structured(row) is None

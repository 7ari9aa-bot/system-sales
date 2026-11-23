"""Instagram edited messages and thread control reach the same ownership rules as Messenger."""

from __future__ import annotations

from app.modules.conversations.gateway.instagram import InstagramAdapter

adapter = InstagramAdapter()


def _payload(**event) -> dict:
    return {
        "entry": [
            {
                "id": "IG-1",
                "messaging": [
                    {"sender": {"id": "cust"}, "recipient": {"id": "IG-1"}, "timestamp": 5, **event}
                ],
            }
        ]
    }


def test_an_edited_message_is_reported_with_its_new_text() -> None:
    out = adapter.parse_edits(_payload(message_edit={"mid": "m1", "num_edit": 1, "text": "new"}))
    assert out == [
        {
            "customer_ref": "cust",
            "recipient_ref": "IG-1",
            "mid": "m1",
            "text": "new",
            "num_edit": 1,
            "timestamp": 5,
        }
    ]


def test_an_edit_without_text_still_marks_the_message_edited() -> None:
    out = adapter.parse_edits(_payload(message_edit={"mid": "m1", "num_edit": 2}))
    assert out[0]["mid"] == "m1" and out[0]["text"] is None


def test_an_edit_with_no_mid_is_ignored() -> None:
    assert adapter.parse_edits(_payload(message_edit={"num_edit": 1})) == []


def test_an_edit_is_not_a_new_inbound_message() -> None:
    assert adapter.parse_inbound(_payload(message_edit={"mid": "m1", "text": "x"})) == []


def test_thread_control_events_are_parsed_in_messengers_shape() -> None:
    out = adapter.parse_handovers(
        _payload(take_thread_control={"previous_owner_app_id": "1", "metadata": "m"})
    )
    assert out[0]["event"] == "take_thread_control"
    assert out[0]["customer_ref"] == "cust"
    assert out[0]["previous_owner_app_id"] == "1"


def test_a_plain_message_has_no_edit_or_handover() -> None:
    plain = _payload(message={"mid": "m9", "text": "hi"})
    assert adapter.parse_edits(plain) == [] and adapter.parse_handovers(plain) == []

"""Instagram webhook parsing against the payloads Meta documents, not against our own shapes.

Each payload below is the documented example from Meta's "Instagram webhook notification
examples" and "Webhooks for Instagram Messaging" pages (messaging fields live in
``entry[].messaging[]``). A setup whose payload "varies by authorization" and delivers the same
event as ``entry[].changes[].value`` is covered too, so an event is not lost to its envelope.
"""

from __future__ import annotations

from app.applications.apparel.modules.conversations.gateway.instagram import InstagramAdapter

adapter = InstagramAdapter()


def _messaging(**event) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": "IGID",
                "time": 1569262486134,
                "messaging": [
                    {
                        "sender": {"id": "IGSID"},
                        "recipient": {"id": "IGID"},
                        "timestamp": 1569262485349,
                        **event,
                    }
                ],
            }
        ],
    }


def _in_changes(field: str, **event) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": "IGID",
                "time": 1569262486134,
                "changes": [
                    {
                        "field": field,
                        "value": {
                            "sender": {"id": "IGSID"},
                            "recipient": {"id": "IGID"},
                            "timestamp": 1569262485349,
                            **event,
                        },
                    }
                ],
            }
        ],
    }


# ---- message_edit -------------------------------------------------------------------------------


def test_a_documented_message_edit_is_read() -> None:
    out = adapter.parse_edits(
        _messaging(message_edit={"mid": "MID", "text": "edited", "num_edit": "1"})
    )
    assert [(e["mid"], e["text"], e["customer_ref"]) for e in out] == [("MID", "edited", "IGSID")]


def test_a_message_edit_delivered_in_changes_is_read_too() -> None:
    out = adapter.parse_edits(
        _in_changes("message_edit", message_edit={"mid": "MID", "text": "x", "num_edit": "2"})
    )
    assert [(e["mid"], e["text"]) for e in out] == [("MID", "x")]


# ---- messaging_seen -----------------------------------------------------------------------------


def test_a_documented_read_receipt_marks_the_message_read() -> None:
    out = adapter.parse_status_updates(_messaging(read={"mid": "MID"}))
    assert [(u.channel_message_id, u.status) for u in out] == [("MID", "read")]


def test_a_read_receipt_delivered_in_changes_is_read_too() -> None:
    out = adapter.parse_status_updates(_in_changes("messaging_seen", read={"mid": "MID"}))
    assert [(u.channel_message_id, u.status) for u in out] == [("MID", "read")]


# ---- message_reactions --------------------------------------------------------------------------


def test_a_documented_reaction_and_its_removal_are_read() -> None:
    react = adapter.parse_inbound(
        _messaging(
            reaction={"mid": "MID", "action": "react", "reaction": "love", "emoji": "\u2764\ufe0f"}
        )
    )
    assert [m.content_type for m in react] == ["reaction"]
    assert react[0].reply_to_message_id == "MID"
    unreact = adapter.parse_inbound(_messaging(reaction={"mid": "MID", "action": "unreact"}))
    assert [m.content_type for m in unreact] == ["reaction"]


# ---- a hand-off notice is not a customer message -----------------------------------------------


def test_a_handoff_notice_is_not_fed_to_the_ai_as_a_customer_message() -> None:
    """Meta: a hand-off notice "can omit mid and text because it has no underlying message"."""
    notice = _messaging(
        message={"admin_text": "BUSINESS_ADMIN_TEXT", "handoff_reason": "purchase_intent"}
    )
    assert adapter.parse_inbound(notice) == []


def test_a_real_text_message_is_still_read() -> None:
    out = adapter.parse_inbound(_messaging(message={"mid": "MID", "text": "hello"}))
    assert [(m.channel_message_id, m.body) for m in out] == [("MID", "hello")]


def test_a_message_with_admin_text_AND_a_customer_text_is_still_read() -> None:
    out = adapter.parse_inbound(
        _messaging(message={"mid": "MID", "text": "hi", "admin_text": "context"})
    )
    assert [m.body for m in out] == ["hi"]


def test_an_unsent_message_is_still_reported() -> None:
    out = adapter.parse_inbound(_messaging(message={"mid": "MID", "is_deleted": True}))
    assert [m.content_type for m in out] == ["deleted"]


# ---- negatives ----------------------------------------------------------------------------------


def test_an_unrelated_field_yields_nothing() -> None:
    other = _in_changes("story_insights", message_edit=None)
    assert adapter.parse_edits(other) == []
    assert adapter.parse_status_updates(other) == []
    assert adapter.parse_inbound(other) == []

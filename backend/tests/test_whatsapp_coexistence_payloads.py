"""The three coexistence payloads, read the way Meta actually sends them.

Contacts, history chunks and the merchant's own app replies are DATA TO IMPORT, never a customer
turn, so they are parsed outside ``parse_inbound``. These tests pin the parts that decide whether an
import is correct:

* a history chunk keeps its phase/chunk_order/progress, so out-of-order arrivals can be ordered;
* a message's direction comes from the thread (the customer), not from guessing;
* a chunk that carries only ``progress: 100`` is still returned — it is the completion signal;
* a media-only echo is not dropped, and its customer is the ``to`` side;
* a contact without a WhatsApp number is skipped instead of stored as a nameless row;
* 131060 is an explainable gap, not a broken channel.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.conversations.gateway import whatsapp_coexistence as wa


def _envelope(field: str, value: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": field, "value": value}]}],
    }


def _history_value(*, messages: list, phase: int = 0, chunk_order: int = 0, progress: int = 0):
    return {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "201000000000", "phone_number_id": "456"},
        "request_id": "req-1",
        "phase": phase,
        "chunk_order": chunk_order,
        "progress": progress,
        "history": [
            {
                "metadata": {"phase": phase, "chunk_order": chunk_order, "progress": progress},
                "threads": [{"id": "201111111111", "messages": messages}],
            }
        ],
    }


# ---------- history ----------


def test_a_history_chunk_keeps_its_place_in_the_transfer() -> None:
    batches = wa.parse_history_batches(
        _envelope("history", _history_value(messages=[], phase=2, chunk_order=7, progress=64))
    )
    assert len(batches) == 1
    batch = batches[0]
    assert (batch["phase"], batch["chunk_order"], batch["progress"]) == (2, 7, 64)
    assert batch["request_id"] == "req-1"
    assert batch["phone_number_id"] == "456"


def test_direction_comes_from_the_thread_not_from_the_payload_order() -> None:
    value = _history_value(
        messages=[
            {
                "id": "wamid.A",
                "from": "201111111111",
                "timestamp": "1700000000",
                "type": "text",
                "text": {"body": "عايز مقاس 42"},
            },
            {
                "id": "wamid.B",
                "from": "201000000000",
                "timestamp": "1700000060",
                "type": "text",
                "text": {"body": "متوفر"},
            },
        ]
    )
    messages = wa.parse_history_batches(_envelope("history", value))[0]["messages"]
    assert [m["direction"] for m in messages] == ["inbound", "outbound"]
    assert messages[0]["customer_ref"] == "201111111111"
    assert messages[1]["customer_ref"] == "201111111111"


def test_a_historical_voice_note_is_a_voice_note_not_a_file() -> None:
    value = _history_value(
        messages=[
            {
                "id": "wamid.C",
                "from": "201111111111",
                "timestamp": "1700000100",
                "type": "audio",
                "audio": {"id": "media-1", "mime_type": "audio/ogg"},
            },
        ]
    )
    message = wa.parse_history_batches(_envelope("history", value))[0]["messages"][0]
    assert message["content_type"] == "voice"
    assert message["media_type"] == "audio"
    assert message["media_url"] == "media-1"


def test_the_original_timestamp_is_kept() -> None:
    value = _history_value(
        messages=[
            {
                "id": "wamid.D",
                "from": "201111111111",
                "timestamp": "1700000000",
                "type": "text",
                "text": {"body": "قديمة"},
            },
        ]
    )
    message = wa.parse_history_batches(_envelope("history", value))[0]["messages"][0]
    assert message["occurred_at"] == datetime.fromtimestamp(1700000000, tz=UTC)


def test_a_chunk_that_only_reports_completion_is_still_a_batch() -> None:
    """progress 100 is the only signal that the whole transfer finished — never drop it."""
    batches = wa.parse_history_batches(
        _envelope("history", _history_value(messages=[], phase=2, chunk_order=99, progress=100))
    )
    assert len(batches) == 1 and batches[0]["progress"] == 100 and batches[0]["messages"] == []


def test_a_thread_sent_without_the_history_wrapper_still_parses() -> None:
    value = {
        "metadata": {"phone_number_id": "456"},
        "phase": 1,
        "chunk_order": 3,
        "progress": 40,
        "threads": [
            {
                "id": "201222222222",
                "messages": [
                    {
                        "id": "wamid.E",
                        "from": "201222222222",
                        "timestamp": "1700000200",
                        "type": "text",
                        "text": {"body": "hi"},
                    }
                ],
            }
        ],
    }
    batches = wa.parse_history_batches(_envelope("history", value))
    assert batches[0]["messages"][0]["customer_ref"] == "201222222222"
    assert batches[0]["chunk_order"] == 3


def test_a_reply_keeps_its_quoted_message_id() -> None:
    value = _history_value(
        messages=[
            {
                "id": "wamid.F",
                "from": "201111111111",
                "timestamp": "1700000300",
                "type": "text",
                "text": {"body": "ده رد"},
                "context": {"id": "wamid.ORIGINAL"},
            },
        ]
    )
    message = wa.parse_history_batches(_envelope("history", value))[0]["messages"][0]
    assert message["reply_to_message_id"] == "wamid.ORIGINAL"


# ---------- contacts ----------


def _state_value(*items: dict) -> dict:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "456"},
        "request_id": "req-2",
        "state_sync": list(items),
    }


def test_contact_add_update_and_remove_are_all_carried() -> None:
    batches = wa.parse_state_sync_batches(
        _envelope(
            "smb_app_state_sync",
            _state_value(
                {
                    "type": "contact",
                    "action": "add",
                    "contact": {"full_name": "أحمد", "phone_number": "201111111111"},
                },
                {
                    "type": "contact",
                    "action": "update",
                    "contact": {"full_name": "منى", "phone_number": "201222222222"},
                },
                {
                    "type": "contact",
                    "action": "remove",
                    "contact": {"phone_number": "201333333333"},
                },
            ),
        )
    )
    contacts = batches[0]["contacts"]
    assert [c["action"] for c in contacts] == ["add", "update", "remove"]
    assert contacts[0]["name"] == "أحمد"
    assert contacts[0]["phone"] == "201111111111"


def test_a_contact_without_a_whatsapp_number_is_skipped() -> None:
    """Meta only syncs contacts that have a WhatsApp number; a nameless row helps nobody."""
    batches = wa.parse_state_sync_batches(
        _envelope("smb_app_state_sync", _state_value({"contact": {"full_name": "بلا رقم"}}))
    )
    assert batches[0]["contacts"] == []


def test_an_unknown_action_falls_back_to_add() -> None:
    batches = wa.parse_state_sync_batches(
        _envelope(
            "smb_app_state_sync",
            _state_value({"action": "merge", "contact": {"phone_number": "201444444444"}}),
        )
    )
    assert batches[0]["contacts"][0]["action"] == "add"


# ---------- the merchant's own replies ----------


def _echo_value(*echoes: dict) -> dict:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "456"},
        "message_echoes": list(echoes),
    }


def test_an_echo_is_outbound_to_the_customer_who_received_it() -> None:
    echoes = wa.parse_message_echoes(
        _envelope(
            "smb_message_echoes",
            _echo_value(
                {
                    "id": "wamid.G",
                    "from": "201000000000",
                    "to": "201111111111",
                    "timestamp": "1700000400",
                    "type": "text",
                    "text": {"body": "تم الشحن"},
                },
            ),
        )
    )
    assert len(echoes) == 1
    assert echoes[0]["customer_ref"] == "201111111111"
    assert echoes[0]["body"] == "تم الشحن"
    assert echoes[0]["source"] == "whatsapp_business_app"


def test_a_media_only_echo_is_not_dropped() -> None:
    """The old echo path required text; a photo reply from the phone is still a reply."""
    echoes = wa.parse_message_echoes(
        _envelope(
            "smb_message_echoes",
            _echo_value(
                {
                    "id": "wamid.H",
                    "to": "201111111111",
                    "timestamp": "1700000500",
                    "type": "image",
                    "image": {"id": "media-2", "mime_type": "image/jpeg"},
                },
            ),
        )
    )
    assert echoes[0]["content_type"] == "image"
    assert echoes[0]["media_url"] == "media-2"
    assert echoes[0]["body"] is None


def test_an_echo_without_a_recipient_is_ignored() -> None:
    echoes = wa.parse_message_echoes(
        _envelope("smb_message_echoes", _echo_value({"id": "wamid.I", "type": "text"}))
    )
    assert echoes == []


# ---------- unsupported messages ----------


def test_an_unsupported_message_is_reported_not_crashed() -> None:
    payload = _envelope(
        "messages",
        {
            "metadata": {"phone_number_id": "456"},
            "statuses": [
                {
                    "id": "wamid.J",
                    "status": "failed",
                    "errors": [
                        {
                            "code": 131060,
                            "title": "Unsupported message",
                            "error_data": {
                                "details": "Message from an unsupported companion device"
                            },
                        }
                    ],
                }
            ],
        },
    )
    notices = wa.parse_unsupported_notices(payload)
    assert notices[0]["code"] == 131060
    assert "companion" in notices[0]["details"]


def test_other_delivery_errors_are_not_unsupported_message_notices() -> None:
    payload = _envelope(
        "messages",
        {"statuses": [{"id": "wamid.K", "status": "failed", "errors": [{"code": 131047}]}]},
    )
    assert wa.parse_unsupported_notices(payload) == []

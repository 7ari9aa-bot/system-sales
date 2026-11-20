"""A Messenger delivery naming two Pages must reach each Page's own store.

Meta batches `entry` items for several Pages into one signed POST. The webhook router resolves the
store once per envelope and asks the adapter for `split_by_account` to get one envelope per
account. Messenger only had `partition_payloads`, a name the router never asks for, so a batch for
two stores was filed entirely under the first one (the same leak WhatsApp had until ad6a3955).
"""

from __future__ import annotations

from app.modules.conversations.gateway.messenger import messenger_adapter


def _event(mid: str, sender: str, page: str) -> dict:
    return {
        "sender": {"id": sender},
        "recipient": {"id": page},
        "message": {"mid": mid, "text": "hi"},
    }


def _batch() -> dict:
    return {
        "object": "page",
        "entry": [
            {"id": "PAGE-A", "messaging": [_event("a1", "u1", "PAGE-A")]},
            {"id": "PAGE-B", "messaging": [_event("b1", "u2", "PAGE-B")]},
            {"id": "PAGE-A", "messaging": [_event("a2", "u3", "PAGE-A")]},
        ],
    }


def test_the_router_hook_exists_on_messenger() -> None:
    assert callable(getattr(messenger_adapter, "split_by_account", None))


def test_a_two_page_delivery_becomes_one_envelope_per_page() -> None:
    parts = messenger_adapter.split_by_account(_batch())
    assert [p["entry"][0]["id"] for p in parts] == ["PAGE-A", "PAGE-B"]
    # every envelope holds ONLY its own page's entries, so tenant resolution cannot mix them
    for part in parts:
        assert {str(e["id"]) for e in part["entry"]} == {part["entry"][0]["id"]}
        assert messenger_adapter.resolve_tenant_key(part) == part["entry"][0]["id"]
    assert [m.channel_message_id for m in messenger_adapter.parse_inbound(parts[0])] == ["a1", "a2"]
    assert [m.channel_message_id for m in messenger_adapter.parse_inbound(parts[1])] == ["b1"]


def test_a_single_page_delivery_is_returned_untouched() -> None:
    one = {
        "object": "page",
        "entry": [{"id": "PAGE-A", "messaging": [_event("a1", "u1", "PAGE-A")]}],
    }
    assert messenger_adapter.split_by_account(one) == [one]


def test_an_envelope_with_no_entries_is_not_dropped() -> None:
    empty = {"object": "page", "entry": []}
    assert messenger_adapter.split_by_account(empty) == [empty]

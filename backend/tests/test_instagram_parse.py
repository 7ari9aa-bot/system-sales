"""Instagram inbound parsing: one test per documented webhook shape."""

from __future__ import annotations

import uuid

import pytest

from app.modules.conversations.gateway.base import OutboundMessage
from app.modules.conversations.gateway.instagram import REACTION_REMOVED, InstagramAdapter
from app.modules.conversations.gateway.instagram_limits import InstagramLimitError

A = InstagramAdapter()


def _wrap(event: dict) -> dict:
    return {"object": "instagram", "entry": [{"id": "ig-biz-1", "time": 1, "messaging": [event]}]}


def _msg(message: dict, **extra) -> dict:
    return _wrap(
        {
            "sender": {"id": "cust-1"},
            "recipient": {"id": "ig-biz-1"},
            "timestamp": 1,
            "message": message,
            **extra,
        }
    )


def test_text_message():
    (m,) = A.parse_inbound(_msg({"mid": "m1", "text": "hello"}))
    assert (m.content_type, m.body, m.channel_message_id, m.customer_ref) == (
        "text",
        "hello",
        "m1",
        "cust-1",
    )


def test_image_video_audio_file():
    for att, canon in (
        ("image", "image"),
        ("video", "video"),
        ("audio", "voice"),
        ("file", "file"),
    ):
        (m,) = A.parse_inbound(
            _msg({"mid": "m", "attachments": [{"type": att, "payload": {"url": "https://x/y"}}]})
        )
        assert m.content_type == canon and m.media_url == "https://x/y"


def test_like_heart_is_a_sticker():
    (m,) = A.parse_inbound(
        _msg({"mid": "m", "attachments": [{"type": "like_heart", "payload": {}}]})
    )
    assert m.content_type == "sticker"


def test_shared_post_and_story_mention_and_story_reply():
    (s,) = A.parse_inbound(
        _msg(
            {
                "mid": "m",
                "attachments": [
                    {"type": "share", "payload": {"url": "https://ig/p/1", "title": "cap"}}
                ],
            }
        )
    )
    assert s.content_type == "share" and s.raw["_ig"]["share"]["url"] == "https://ig/p/1"
    (st,) = A.parse_inbound(
        _msg(
            {
                "mid": "m",
                "attachments": [{"type": "story_mention", "payload": {"url": "https://cdn/s"}}],
            }
        )
    )
    assert st.content_type == "story_mention"
    (sr,) = A.parse_inbound(
        _msg(
            {
                "mid": "m",
                "text": "love it",
                "reply_to": {"story": {"url": "https://cdn/s", "id": "9"}},
            }
        )
    )
    assert sr.body == "love it" and sr.raw["_ig"]["story_reply"]["id"] == "9"


def test_reply_to_a_message_is_linked():
    (m,) = A.parse_inbound(_msg({"mid": "m2", "text": "yes", "reply_to": {"mid": "m1"}}))
    assert m.reply_to_message_id == "m1" and m.raw["_ig"]["reply_to_provider_id"] == "m1"


def test_echo_is_not_a_customer_message():
    assert A.parse_inbound(_msg({"mid": "m", "text": "from the app", "is_echo": True})) == []


def test_unsend_is_marked_deleted():
    (m,) = A.parse_inbound(_msg({"mid": "m", "is_deleted": True}))
    assert m.content_type == "deleted" and m.body is None


def test_unknown_attachment_is_unsupported_not_dropped():
    (m,) = A.parse_inbound(_msg({"mid": "m", "attachments": [{"type": "location", "payload": {}}]}))
    assert m.content_type == "unsupported"


def test_reaction_and_unreaction():
    (r,) = A.parse_inbound(
        _wrap(
            {
                "sender": {"id": "c"},
                "recipient": {"id": "b"},
                "reaction": {
                    "mid": "m1",
                    "action": "react",
                    "reaction": "love",
                    "emoji": "\u2764\ufe0f",
                },
            }
        )
    )
    assert (r.content_type, r.body, r.reply_to_message_id) == ("reaction", "\u2764\ufe0f", "m1")
    (u,) = A.parse_inbound(
        _wrap(
            {
                "sender": {"id": "c"},
                "recipient": {"id": "b"},
                "reaction": {"mid": "m1", "action": "unreact"},
            }
        )
    )
    assert u.body == REACTION_REMOVED


def test_empty_and_malformed_payloads_yield_nothing():
    assert A.parse_inbound({}) == []
    assert A.parse_inbound({"entry": [{"messaging": []}]}) == []
    assert A.parse_inbound({"entry": [{"messaging": [{"sender": {"id": "c"}}]}]}) == []
    assert A.parse_inbound({"entry": None}) == []


def test_every_event_in_one_envelope_is_parsed():
    p = {
        "entry": [
            {
                "id": "b",
                "messaging": [
                    {
                        "sender": {"id": "c"},
                        "recipient": {"id": "b"},
                        "message": {"mid": "a", "text": "1"},
                    },
                    {
                        "sender": {"id": "c"},
                        "recipient": {"id": "b"},
                        "message": {"mid": "b", "text": "2"},
                    },
                ],
            }
        ]
    }
    assert [m.body for m in A.parse_inbound(p)] == ["1", "2"]


def test_read_receipt_becomes_a_read_status():
    p = _wrap(
        {"sender": {"id": "c"}, "recipient": {"id": "b"}, "timestamp": 5, "read": {"mid": "m9"}}
    )
    (s,) = A.parse_status_updates(p)
    assert (s.channel_message_id, s.status) == ("m9", "read")
    assert A.parse_status_updates({}) == []


# ---------- outbound payloads, shapes taken from Meta's Send API page ----------


def _out(**kw) -> OutboundMessage:
    meta = kw.pop("meta", {})
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="igsid-1",
        meta=meta,
        **kw,
    )


def test_send_text_and_reply_to_is_at_the_root():
    assert A.build_send_payload(_out(body="hi")) == {
        "recipient": {"id": "igsid-1"},
        "message": {"text": "hi"},
    }
    p = A.build_send_payload(_out(body="yes", meta={"reply_to_provider_id": "m1"}))
    assert p["reply_to"] == {"mid": "m1"} and "reply_to" not in p["message"]


def test_send_each_media_kind():
    for kind, want in (
        ("image", "image"),
        ("video", "video"),
        ("audio", "audio"),
        ("voice", "audio"),
        ("document", "file"),
    ):
        p = A.build_send_payload(_out(media_url="https://x/f", meta={"media_type": kind}))
        assert p["message"]["attachment"] == {"type": want, "payload": {"url": "https://x/f"}}


def test_send_heart_and_own_post_share():
    assert A.build_send_payload(_out(meta={"like_heart": True}))["message"] == {
        "attachment": {"type": "like_heart"}
    }
    s = A.build_send_payload(_out(meta={"share_media_id": "p1"}))
    assert s["message"]["attachment"] == {"type": "MEDIA_SHARE", "payload": {"id": "p1"}}


def test_send_reaction_and_unreaction():
    r = A.build_send_payload(_out(body="\u2764\ufe0f", meta={"reaction_to_provider_id": "m1"}))
    assert r == {
        "recipient": {"id": "igsid-1"},
        "sender_action": "react",
        "payload": {"message_id": "m1", "reaction": "love"},
    }
    u = A.build_send_payload(_out(body=REACTION_REMOVED, meta={"reaction_to_provider_id": "m1"}))
    assert u["sender_action"] == "unreact" and u["payload"] == {"message_id": "m1"}


def test_only_the_heart_can_be_sent_as_a_reaction():
    # Meta documents `love` as the only reaction a business may send; refuse the rest up front.
    with pytest.raises(InstagramLimitError) as refused:
        A.build_send_payload(_out(body="\U0001f602", meta={"reaction_to_provider_id": "m1"}))
    assert refused.value.code == "reaction_not_allowed"
    ok = A.build_send_payload(_out(body="\u2764", meta={"reaction_to_provider_id": "m1"}))
    assert ok["payload"]["reaction"] == "love"


def test_quick_replies_are_capped_at_13_and_20_chars():
    q = [{"title": "x" * 40, "payload": f"p{i}"} for i in range(20)]
    p = A.build_send_payload(_out(body="pick", meta={"quick_replies": q}))
    assert (
        len(p["message"]["quick_replies"]) == 13
        and len(p["message"]["quick_replies"][0]["title"]) == 20
    )


def test_sender_actions_only_allow_the_three_documented():
    assert A.build_sender_action("c", "mark_seen") == {
        "recipient": {"id": "c"},
        "sender_action": "mark_seen",
    }
    for ok in ("typing_on", "typing_off"):
        assert A.build_sender_action("c", ok)["sender_action"] == ok
    with pytest.raises(ValueError):
        A.build_sender_action("c", "react")


# ---- isolation + albums -----------------------------------------------------


def _event(account: str, mid: str, text: str) -> dict:
    return {
        "sender": {"id": f"cust-{account}"},
        "recipient": {"id": account},
        "message": {"mid": mid, "text": text},
    }


def test_an_entry_for_another_account_is_never_ingested_under_the_first_tenant():
    """The tenant is resolved from entry[0].id once for the whole delivery. If Meta batches
    a second account's entry into the same POST, its messages must NOT land in the first
    account's inbox: only entries belonging to the resolved account are parsed."""
    p = {
        "object": "instagram",
        "entry": [
            {"id": "acct-A", "messaging": [_event("acct-A", "a1", "for A")]},
            {"id": "acct-B", "messaging": [_event("acct-B", "b1", "for B")]},
        ],
    }
    assert A.resolve_tenant_key(p) == "acct-A"
    assert [m.body for m in A.parse_inbound(p)] == ["for A"]
    assert [m.body for m in A.parse_inbound(p, account_id="acct-B")] == ["for B"]


def test_several_entries_for_the_same_account_are_all_parsed():
    p = {
        "entry": [
            {"id": "acct-A", "messaging": [_event("acct-A", "a1", "one")]},
            {"id": "acct-A", "messaging": [_event("acct-A", "a2", "two")]},
        ]
    }
    assert [m.body for m in A.parse_inbound(p)] == ["one", "two"]


def test_the_accounts_in_a_delivery_are_listed_in_order_without_repeats():
    p = {
        "entry": [
            {"id": "acct-A", "messaging": []},
            {"id": "acct-B", "messaging": []},
            {"id": "acct-A", "messaging": []},
        ]
    }
    assert A.account_ids(p) == ["acct-A", "acct-B"]
    assert A.account_ids({}) == []
    assert A.account_ids({"entry": None}) == []


def test_every_attachment_of_an_album_becomes_its_own_message():
    """A customer can send several pictures in one message. Reading only attachments[0]
    silently dropped the rest."""
    p = _msg(
        {
            "mid": "album-1",
            "text": "look",
            "attachments": [
                {"type": "image", "payload": {"url": "https://cdn/1.jpg"}},
                {"type": "image", "payload": {"url": "https://cdn/2.jpg"}},
                {"type": "image", "payload": {"url": "https://cdn/3.jpg"}},
            ],
        }
    )
    got = A.parse_inbound(p)
    assert [m.media_url for m in got] == [
        "https://cdn/1.jpg",
        "https://cdn/2.jpg",
        "https://cdn/3.jpg",
    ]
    # Each needs its own idempotency key, and the caption belongs to the first one only.
    assert len({m.channel_message_id for m in got}) == 3
    assert got[0].channel_message_id == "album-1"
    assert [m.body for m in got] == ["look", None, None]


def test_a_single_attachment_keeps_the_plain_message_id():
    p = _msg(
        {"mid": "one", "attachments": [{"type": "image", "payload": {"url": "https://cdn/1.jpg"}}]}
    )
    (m,) = A.parse_inbound(p)
    assert m.channel_message_id == "one"


def test_a_delivery_for_two_accounts_is_split_into_one_envelope_each():
    p = {
        "object": "instagram",
        "entry": [
            {"id": "acct-A", "messaging": [_event("acct-A", "a1", "for A")]},
            {"id": "acct-B", "messaging": [_event("acct-B", "b1", "for B")]},
            {"id": "acct-A", "messaging": [_event("acct-A", "a2", "also A")]},
        ],
    }
    parts = A.split_by_account(p)
    assert [A.resolve_tenant_key(x) for x in parts] == ["acct-A", "acct-B"]
    assert [[m.body for m in A.parse_inbound(x)] for x in parts] == [["for A", "also A"], ["for B"]]
    assert all(x["object"] == "instagram" for x in parts)


def test_a_delivery_for_one_account_is_returned_untouched():
    p = _msg({"mid": "m", "text": "hi"})
    assert A.split_by_account(p) == [p]
    assert A.split_by_account({}) == [{}]


def test_heart_and_share_request_fields_default_off_and_cap_the_post_id():
    from pydantic import ValidationError

    from app.modules.conversations.routers._deps import SendMessageRequest

    plain = SendMessageRequest(body="hi")
    assert plain.instagram_heart is False and plain.instagram_share_post_id is None
    assert SendMessageRequest(instagram_heart=True).instagram_heart is True
    assert SendMessageRequest(instagram_share_post_id="17900000000000001").instagram_share_post_id
    with pytest.raises(ValidationError):
        SendMessageRequest(instagram_share_post_id="1" * 65)


def test_a_shared_post_without_an_id_is_not_sent_as_text():
    # An empty id must fall through to the plain-text branch, never become a card with no post.
    p = A.build_send_payload(_out(body="", meta={"share_media_id": ""}))
    assert "attachment" not in p["message"]

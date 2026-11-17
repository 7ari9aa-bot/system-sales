"""Instagram inbound parsing: one test per documented webhook shape."""

from __future__ import annotations

import uuid

import pytest

from app.modules.conversations.gateway.base import OutboundMessage
from app.modules.conversations.gateway.instagram import REACTION_REMOVED, InstagramAdapter

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
        "payload": {"message_id": "m1", "reaction": "\u2764\ufe0f"},
    }
    u = A.build_send_payload(_out(body=REACTION_REMOVED, meta={"reaction_to_provider_id": "m1"}))
    assert u["sender_action"] == "unreact" and u["payload"] == {"message_id": "m1"}


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

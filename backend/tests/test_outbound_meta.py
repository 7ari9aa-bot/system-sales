"""What the send worker hands the channel adapter beyond text and file.

The route stores a send-time feature (an Instagram heart, quick replies, WhatsApp buttons...) in
the message row; the worker copies it into ``OutboundMessage.meta`` and the adapter reads it from
there. If a key is not copied, nothing fails: the message still goes out, as plain text, and the
customer simply never gets the feature. Nothing else tests that hop, so it is pinned here.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.workers.message_worker import outbound_meta

SPEC = {"kind": "buttons", "body": "Ok?", "buttons": [{"id": "y", "title": "Yes"}]}


def _meta(provider_metadata=None, *, content_type="text", media=None, reply=None) -> dict:
    message = SimpleNamespace(provider_metadata=provider_metadata, content_type=content_type)
    return outbound_meta(message, media_meta=media or {}, reply_to_provider_id=reply)


def test_a_plain_message_carries_nothing():
    assert _meta() == {}
    assert _meta({}) == {}


def test_the_interactive_spec_reaches_the_adapter():
    assert _meta({"interactive": SPEC}) == {"interactive": SPEC}


def test_an_empty_interactive_spec_is_not_passed_on():
    assert "interactive" not in _meta({"interactive": {}})
    assert "interactive" not in _meta({"interactive": None})


def test_instagram_features_reach_the_adapter():
    assert _meta({"instagram_heart": True}) == {"like_heart": True}
    assert _meta({"instagram_share_post_id": "123"}) == {"share_media_id": "123"}
    assert _meta({"instagram_quick_replies": ["A", "B"]}) == {
        "quick_replies": [{"title": "A", "payload": "A"}, {"title": "B", "payload": "B"}]
    }


def test_the_human_agent_tag_reaches_the_adapter():
    assert _meta({"human_agent": True}) == {"human_agent": True}
    assert _meta({"human_agent": False}) == {}


def test_a_quoted_reply_names_the_quoted_message():
    assert _meta(reply="wamid.X") == {"reply_to_provider_id": "wamid.X"}


def test_a_reaction_names_its_target_instead_of_quoting_it():
    assert _meta(content_type="reaction", reply="wamid.X") == {"reaction_to_provider_id": "wamid.X"}


def test_no_target_means_no_key():
    assert _meta(content_type="reaction", reply=None) == {}
    assert _meta(reply="") == {}


def test_media_details_are_kept_beside_the_features():
    media = {"media_type": "image", "filename": "a.png"}
    out = _meta({"interactive": SPEC}, media=media, reply="wamid.X")
    assert out == {**media, "interactive": SPEC, "reply_to_provider_id": "wamid.X"}


def test_the_input_is_never_modified():
    media = {"media_type": "image"}
    _meta({"instagram_heart": True}, media=media, reply="wamid.X")
    assert media == {"media_type": "image"}

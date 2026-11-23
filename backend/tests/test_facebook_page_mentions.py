"""A tag of the Page is a mention, not a feed change.

The facebook subscription asks for the ``mention`` field, but the adapter inherited Messenger's
parser, which reads only ``feed``/``comments``: every tag arrived and produced nothing. These tests
pin the mention shape, its idempotency key and that ordinary feed comments still parse alongside.
"""

from __future__ import annotations

from app.modules.conversations.gateway.facebook import FacebookPageAdapter


def _payload(*changes: dict) -> dict:
    return {"object": "page", "entry": [{"id": "PAGE", "changes": list(changes)}]}


def test_a_comment_mention_becomes_one_row_keyed_by_the_comment() -> None:
    payload = _payload(
        {
            "field": "mention",
            "value": {
                "post_id": "post_1",
                "comment_id": "cmt_1",
                "message": "شوفوا @FIHRIST",
                "sender_id": "user_9",
                "created_time": "2026-11-23T06:00:00+0000",
            },
        }
    )

    mentions = FacebookPageAdapter().parse_mentions(payload)

    assert len(mentions) == 1
    mention = mentions[0]
    assert mention.platform_comment_id == "mention:cmt_1"
    assert mention.post_id == "post_1"
    assert mention.author_ref == "user_9"
    assert mention.parent_comment_id == "cmt_1"
    assert mention.body is None, "Meta sends ids only; the row is kept and the UI words the tag"
    assert mention.verb == "mention"


def test_a_caption_mention_without_a_comment_keys_on_the_post() -> None:
    payload = _payload({"field": "mention", "value": {"post_id": "post_2"}})

    mentions = FacebookPageAdapter().parse_mentions(payload)

    assert [m.platform_comment_id for m in mentions] == ["mention:post_2"]
    assert mentions[0].body is None, "Meta often sends ids only; the row is kept anyway"


def test_the_field_name_meta_documents_both_ways_is_accepted() -> None:
    payload = _payload({"field": "mentions", "value": {"post_id": "post_3", "comment_id": "c3"}})

    assert [m.platform_comment_id for m in FacebookPageAdapter().parse_mentions(payload)] == [
        "mention:c3"
    ]


def test_a_mention_without_any_id_is_skipped_instead_of_stored_empty() -> None:
    assert FacebookPageAdapter().parse_mentions(_payload({"field": "mention", "value": {}})) == []


def test_parse_comments_returns_feed_comments_and_mentions_together() -> None:
    payload = _payload(
        {
            "field": "feed",
            "value": {
                "item": "comment",
                "verb": "add",
                "comment_id": "feed_c1",
                "post_id": "post_4",
                "message": "كم السعر؟",
                "from": {"id": "user_1", "name": "سارة"},
            },
        },
        {"field": "mention", "value": {"post_id": "post_5", "comment_id": "cmt_5"}},
    )

    parsed = FacebookPageAdapter().parse_comments(payload)
    keys = {c.platform_comment_id for c in parsed}

    assert "feed_c1" in keys, "the inherited feed parser must keep working"
    assert "mention:cmt_5" in keys
    assert len(parsed) == 2

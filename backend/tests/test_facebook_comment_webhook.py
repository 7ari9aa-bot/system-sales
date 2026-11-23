"""Facebook Page comments reach the inbox by webhook, not only when the page is opened.

A Page connection used to subscribe to its Messenger fields only, so Meta never sent the
Page's `feed` changes and a new comment on a post never arrived until someone reloaded the
feed. The adapter already parses `feed` comments (it inherits Messenger's parser).
"""

from __future__ import annotations

from app.modules.conversations.gateway.facebook import facebook_adapter
from app.modules.customers.meta_oauth import subscribed_fields


def _feed(value: dict) -> dict:
    return {
        "object": "page",
        "entry": [{"id": "111", "time": 1, "changes": [{"field": "feed", "value": value}]}],
    }


COMMENT = {
    "item": "comment",
    "verb": "add",
    "comment_id": "555_777",
    "post_id": "111_555",
    "parent_id": "111_555",
    "from": {"id": "999", "name": "Sara Ahmed"},
    "message": "بكام المقاس 40؟",
    "created_time": 1_790_000_000,
}


def test_a_facebook_page_subscribes_to_its_feed_and_messenger_does_not() -> None:
    assert "feed" in subscribed_fields("facebook").split(",")
    # Facebook is the Page's posts and comments; private chat belongs to the Messenger channel.
    assert "messages" not in subscribed_fields("facebook").split(",")
    assert "messages" in subscribed_fields("messenger").split(",")
    assert "feed" not in subscribed_fields("messenger").split(",")


def test_messenger_and_facebook_pages_subscribe_to_reactions_but_instagram_does_not() -> None:
    """A customer's reaction to a Messenger message is a `message_reactions` Page field. Without
    it the adapter's reaction parser never sees an event."""
    assert "message_reactions" in subscribed_fields("messenger").split(",")
    # Private-chat reactions belong to the Messenger channel, not to a Facebook posts/comments link.
    assert "message_reactions" not in subscribed_fields("facebook").split(",")
    assert "message_reactions" not in subscribed_fields("instagram").split(",")


def test_instagram_page_subscription_has_no_instagram_only_fields() -> None:
    """comments / mentions / message_reactions / messaging_seen are fields of the `instagram`
    object, configured in the App Dashboard. Meta ignores or rejects them on a Page subscription,
    and a rejection used to fail the whole link."""
    fields = subscribed_fields("instagram").split(",")
    assert "feed" not in fields
    assert {"comments", "mentions", "message_reactions", "messaging_seen"}.isdisjoint(fields)


def test_a_new_comment_on_a_post_is_parsed() -> None:
    [comment] = facebook_adapter.parse_comments(_feed(COMMENT))
    assert comment.platform_comment_id == "555_777"
    assert comment.post_id == "111_555"
    assert comment.author_name == "Sara Ahmed"
    assert comment.body == "بكام المقاس 40؟"
    assert comment.verb == "add"


def test_an_edit_and_a_removal_are_kept_with_their_verb() -> None:
    [edited] = facebook_adapter.parse_comments(_feed({**COMMENT, "verb": "edited", "message": "x"}))
    assert edited.verb == "edited"
    [removed] = facebook_adapter.parse_comments(_feed({**COMMENT, "verb": "remove"}))
    assert removed.verb == "remove"
    assert removed.body is None


def test_a_like_a_reaction_and_a_post_are_not_comments() -> None:
    for value in (
        {"item": "like", "verb": "add", "post_id": "111_555", "from": {"id": "9"}},
        {"item": "reaction", "verb": "add", "reaction_type": "love", "post_id": "111_555"},
        {"item": "status", "verb": "add", "post_id": "111_556", "message": "a new post"},
    ):
        assert facebook_adapter.parse_comments(_feed(value)) == []


def test_a_malformed_delivery_yields_nothing_instead_of_failing() -> None:
    assert facebook_adapter.parse_comments({}) == []
    no_id = {"entry": [{"changes": [{"field": "feed", "value": {"item": "comment"}}]}]}
    assert facebook_adapter.parse_comments(no_id) == []


# ---------------------------------------------------------------- @mentions of the Page


def _mention(value: dict) -> dict:
    return {
        "object": "page",
        "entry": [{"id": "111", "time": 1, "changes": [{"field": "mention", "value": value}]}],
    }


MENTION_IN_COMMENT = {
    "item": "comment",
    "verb": "add",
    "post_id": "999_1",
    "comment_id": "999_2",
    "sender_id": "42",
    "sender_name": "Mona Ali",
    "message": "@Shop هل متوفر؟",
    "created_time": 1700000000,
}


def test_a_page_mention_in_a_comment_is_kept_as_a_comment_row() -> None:
    [row] = facebook_adapter.parse_comments(_mention(MENTION_IN_COMMENT))
    assert row.verb == "mention"
    assert row.platform_comment_id == "mention:999_2"
    assert (row.post_id, row.author_ref, row.author_name) == ("999_1", "42", "Mona Ali")
    assert row.body == "@Shop هل متوفر؟"
    assert row.commented_at is not None


def test_a_page_mention_in_a_post_is_keyed_by_the_post() -> None:
    value = {"item": "post", "verb": "add", "post_id": "999_1", "message": "love @Shop"}
    [row] = facebook_adapter.parse_comments(_mention(value))
    assert row.platform_comment_id == "mention:999_1" and row.verb == "mention"


def test_a_mention_never_collides_with_the_comment_that_carries_it() -> None:
    """The same comment id arrives as a `feed` comment and as a `mention`: two different rows."""
    both = {
        "object": "page",
        "entry": [
            {
                "id": "111",
                "changes": [
                    {"field": "feed", "value": {**COMMENT, "comment_id": "999_2"}},
                    {"field": "mention", "value": MENTION_IN_COMMENT},
                ],
            }
        ],
    }
    ids = [c.platform_comment_id for c in facebook_adapter.parse_comments(both)]
    assert sorted(ids) == ["999_2", "mention:999_2"]


def test_a_redelivered_mention_has_the_same_key() -> None:
    first = facebook_adapter.parse_comments(_mention(MENTION_IN_COMMENT))
    again = facebook_adapter.parse_comments(_mention(MENTION_IN_COMMENT))
    assert [c.platform_comment_id for c in first] == [c.platform_comment_id for c in again]


def test_an_older_mention_shape_with_a_from_object_is_read() -> None:
    value = {
        "item": "comment",
        "post_id": "999_1",
        "comment_id": "999_2",
        "from": {"id": "7", "name": "Old Shape"},
        "message": "hi",
    }
    [row] = facebook_adapter.parse_comments(_mention(value))
    assert (row.author_ref, row.author_name) == ("7", "Old Shape")


def test_a_removed_or_unidentifiable_mention_yields_nothing() -> None:
    assert facebook_adapter.parse_comments(_mention({**MENTION_IN_COMMENT, "verb": "remove"})) == []
    assert facebook_adapter.parse_comments(_mention({"item": "comment", "verb": "add"})) == []
    assert facebook_adapter.parse_comments(_mention("not a dict")) == []  # type: ignore[arg-type]


def test_messenger_does_not_read_mentions_so_a_shared_page_is_not_saved_twice() -> None:
    from app.modules.conversations.gateway.messenger import messenger_adapter

    assert messenger_adapter.parse_comments(_mention(MENTION_IN_COMMENT)) == []

"""Instagram: a redelivered reaction is one row, and an @-mention of the account is not lost.

A reaction event has no message id; it used to be stored with ``channel_message_id=None``, which
is exactly the value the dedupe check skips, so Meta resending the event stored it again. The
``mentions`` webhook field was never read at all.
"""

from __future__ import annotations

from app.modules.conversations.gateway.instagram import instagram_adapter as A


def _reaction(action: str = "react", emoji: str = "love", ts: int = 1700000000000) -> dict:
    reaction = {"mid": "m1", "action": action}
    if action == "react":
        reaction["reaction"] = emoji
        reaction["emoji"] = "\u2764\ufe0f"
    return {
        "object": "instagram",
        "entry": [
            {
                "id": "IG-1",
                "messaging": [
                    {
                        "sender": {"id": "U1"},
                        "recipient": {"id": "IG-1"},
                        "timestamp": ts,
                        "reaction": reaction,
                    }
                ],
            }
        ],
    }


def test_a_reaction_always_has_a_dedupe_id() -> None:
    [msg] = A.parse_inbound(_reaction())
    assert msg.channel_message_id


def test_a_redelivered_reaction_has_the_same_id() -> None:
    [a] = A.parse_inbound(_reaction())
    [b] = A.parse_inbound(_reaction())
    assert a.channel_message_id == b.channel_message_id


def test_react_and_unreact_do_not_collide() -> None:
    [a] = A.parse_inbound(_reaction("react"))
    [b] = A.parse_inbound(_reaction("unreact"))
    assert a.channel_message_id != b.channel_message_id


def test_two_reactions_at_different_times_are_two_rows() -> None:
    [a] = A.parse_inbound(_reaction(ts=1))
    [b] = A.parse_inbound(_reaction(ts=2))
    assert a.channel_message_id != b.channel_message_id


def _mention(**value) -> dict:
    return {
        "object": "instagram",
        "entry": [{"id": "IG-1", "changes": [{"field": "mentions", "value": value}]}],
    }


def test_a_comment_mention_is_kept() -> None:
    [c] = A.parse_comments(_mention(media_id="MEDIA-1", comment_id="C-9"))
    assert c.verb == "mention"
    assert c.platform_comment_id == "mention:C-9"
    assert c.post_id == "MEDIA-1"


def test_a_caption_mention_falls_back_to_the_media_id() -> None:
    [c] = A.parse_comments(_mention(media_id="MEDIA-1"))
    assert c.platform_comment_id == "mention:MEDIA-1"


def test_a_mention_with_no_ids_is_dropped() -> None:
    assert A.parse_comments(_mention()) == []


def test_a_redelivered_mention_is_the_same_row() -> None:
    first = A.parse_comments(_mention(media_id="M", comment_id="C"))
    again = A.parse_comments(_mention(media_id="M", comment_id="C"))
    assert first[0].platform_comment_id == again[0].platform_comment_id


def test_a_mention_does_not_swallow_ordinary_comments() -> None:
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "IG-1",
                "changes": [
                    {"field": "mentions", "value": {"media_id": "M", "comment_id": "C"}},
                    {
                        "field": "comments",
                        "value": {"id": "K1", "text": "nice", "media": {"id": "M"}},
                    },
                ],
            }
        ],
    }
    ids = sorted(c.platform_comment_id for c in A.parse_comments(payload))
    assert ids == ["K1", "mention:C"]

"""The Page's own feed: mentions are stored, post changes are applied, nothing is dropped silently.

`parse_meta_comment_changes` returns nothing for anything that is not a comment, so a Page's post
edit, share, hide or reaction vanished: FIHRIST kept showing the post exactly as it was published.
The `mention` field was subscribed and had no parser at all, so a tag produced nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.conversations.facebook_feed import PageEventProcessor
from app.modules.conversations.gateway.facebook import FacebookPageAdapter

TENANT = uuid.uuid4()


def _feed(*values, field="feed") -> dict:
    return {
        "object": "page",
        "entry": [{"id": "page-1", "changes": [{"field": field, "value": v} for v in values]}],
    }


class _Result:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, post=None) -> None:
        self.post = post
        self.queries = 0

    async def execute(self, stmt):
        self.queries += 1
        return _Result(self.post)


def _post(**kwargs):
    base = {
        "id": uuid.uuid4(),
        "post_id": "p-1",
        "caption": "الكابشن القديم",
        "like_count": 4,
        "publish_status": None,
        "posted_at": datetime(2026, 11, 1, tzinfo=UTC),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- mentions


def test_a_mention_in_a_post_is_stored_with_its_post_id():
    payload = _feed({"post_id": "p-9"}, field="mention")

    mentions = FacebookPageAdapter().parse_mentions(payload)

    assert len(mentions) == 1
    assert mentions[0].verb == "mention"
    assert mentions[0].post_id == "p-9"
    assert mentions[0].platform_comment_id == "mention:p-9"
    assert mentions[0].body is None, "Meta sends ids only; an empty body is the honest record"


def test_a_mention_in_a_comment_keys_on_the_comment_and_is_not_a_comment_body():
    payload = _feed({"post_id": "p-9", "comment_id": "c-3"}, field="mention")

    mention = FacebookPageAdapter().parse_mentions(payload)[0]

    assert mention.platform_comment_id == "mention:c-3"
    assert mention.post_id == "p-9"
    assert mention.parent_comment_id == "c-3"


def test_the_plural_spelling_is_accepted_too():
    payload = _feed({"post_id": "p-9"}, field="mentions")

    assert len(FacebookPageAdapter().parse_mentions(payload)) == 1


def test_a_mention_without_any_id_is_ignored():
    assert FacebookPageAdapter().parse_mentions(_feed({}, field="mention")) == []


def test_a_real_comment_is_not_mistaken_for_a_mention():
    payload = _feed({"item": "comment", "comment_id": "c-1", "message": "حلو"})

    assert FacebookPageAdapter().parse_mentions(payload) == []


# ---------------------------------------------------------------- feed


def test_the_processor_sees_every_feed_and_mention_change():
    payload = _feed({"item": "post", "post_id": "p-1"}, {"item": "comment", "comment_id": "c-1"})
    payload["entry"][0]["changes"].append(
        {"field": "mention", "value": {"post_id": "p-2"}}
    )

    assert len(FacebookPageAdapter().parse_feed_events(payload)) == 3


def test_classify_counts_each_kind():
    changes = [
        {"field": "feed", "value": {"item": "comment"}},
        {"field": "feed", "value": {"item": "reaction"}},
        {"field": "feed", "value": {"item": "post"}},
        {"field": "feed", "value": {"item": "something-new"}},
        {"field": "mention", "value": {"post_id": "p"}},
    ]

    assert PageEventProcessor.classify(changes) == {
        "comment": 1,
        "reaction": 1,
        "post": 1,
        "unsupported": 1,
        "mention": 1,
    }


@pytest.mark.asyncio
async def test_a_post_edit_updates_the_caption_we_hold():
    post = _post()
    session = _Session(post)

    outcome = await PageEventProcessor.apply(
        session, TENANT, "facebook", [{"field": "feed", "value": {"item": "post",
                                                                 "post_id": "p-1",
                                                                 "message": "كابشن جديد",
                                                                 "verb": "edited"}}]
    )

    assert post.caption == "كابشن جديد"
    assert outcome["updated"] == 1


@pytest.mark.asyncio
async def test_a_reaction_moves_the_counter_without_inventing_a_total():
    post = _post(like_count=4)
    session = _Session(post)

    await PageEventProcessor.apply(
        session, TENANT, "facebook",
        [{"field": "feed", "value": {"item": "reaction", "post_id": "p-1", "verb": "add"}}],
    )
    assert post.like_count == 5

    await PageEventProcessor.apply(
        session, TENANT, "facebook",
        [{"field": "feed", "value": {"item": "reaction", "post_id": "p-1", "verb": "remove"}}],
    )
    assert post.like_count == 4


@pytest.mark.asyncio
async def test_a_removal_marks_the_post_removed_instead_of_deleting_it():
    post = _post()
    session = _Session(post)

    await PageEventProcessor.apply(
        session, TENANT, "facebook",
        [{"field": "feed", "value": {"item": "post", "post_id": "p-1", "verb": "remove"}}],
    )

    assert post.publish_status == "removed"
    assert post.caption == "الكابشن القديم", "comments still point at this row"


@pytest.mark.asyncio
async def test_a_change_for_a_post_we_never_saw_is_counted_not_invented():
    session = _Session(None)

    outcome = await PageEventProcessor.apply(
        session, TENANT, "facebook",
        [{"field": "feed", "value": {"item": "post", "post_id": "ghost", "message": "x"}}],
    )

    assert outcome["unknown_post"] == 1
    assert outcome["updated"] == 0


@pytest.mark.asyncio
async def test_a_comment_change_is_left_to_the_comment_parser():
    session = _Session(None)

    outcome = await PageEventProcessor.apply(
        session, TENANT, "facebook",
        [{"field": "feed", "value": {"item": "comment", "comment_id": "c-1"}}],
    )

    assert outcome["ignored"] == 1
    assert session.queries == 0, "a comment must not trigger a post lookup"

"""Two Instagram fields that arrived and went nowhere: live_comments and story_insights.

`live_comments` had no parser, so a comment on a live broadcast was dropped. `story_insights` had
no parser AND no column, so every story metric Meta sent was lost, and the -1 Meta sends for "fewer
than five" was never handled anywhere.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.conversations.gateway.instagram import InstagramAdapter
from app.modules.conversations.instagram_insights import (
    StoryInsightsService,
    is_below_threshold,
)

TENANT = uuid.uuid4()


def _change(field: str, value: dict) -> dict:
    return {"object": "instagram", "entry": [{"id": "ig-1", "changes": [{"field": field, "value": value}]}]}


# ---------------------------------------------------------------- live comments


def test_a_live_comment_is_stored_as_a_comment_on_its_broadcast():
    payload = _change(
        "live_comments",
        {"id": "lc-1", "text": "بكام؟", "from": {"id": "u-9", "username": "hhamd.d"},
         "media_id": "m-1"},
    )

    comments = InstagramAdapter().parse_live_comments(payload)

    assert len(comments) == 1
    assert comments[0].platform_comment_id == "lc-1"
    assert comments[0].post_id == "m-1"
    assert comments[0].author_name == "hhamd.d"
    assert comments[0].body == "بكام؟"
    assert comments[0].verb == "add"


def test_a_live_comment_rides_the_normal_comment_path():
    """It is a comment: the same ingest stores it, so the merchant sees it in Activity."""
    payload = _change("live_comments", {"id": "lc-2", "text": "متاح؟", "media_id": "m-1"})

    ids = [c.platform_comment_id for c in InstagramAdapter().parse_comments(payload)]

    assert ids == ["lc-2"]


def test_a_live_comment_without_an_id_is_ignored():
    assert InstagramAdapter().parse_live_comments(_change("live_comments", {"text": "x"})) == []


def test_a_normal_comment_is_not_read_as_a_live_one():
    assert InstagramAdapter().parse_live_comments(_change("comments", {"id": "c-1"})) == []


# ---------------------------------------------------------------- story insights


def test_story_metrics_are_read_with_their_media_id():
    payload = _change("story_insights", {"media_id": "m-1", "impressions": 120, "reach": 90})

    deliveries = InstagramAdapter().parse_story_insights(payload)

    assert deliveries == [
        {"media_id": "m-1", "metrics": {"impressions": 120, "reach": 90},
         "raw": {"media_id": "m-1", "impressions": 120, "reach": 90}}
    ]


def test_minus_one_is_kept_and_understood_as_fewer_than_five():
    """Meta sends -1 when the real count is under five. It is not an error and not zero."""
    payload = _change("story_insights", {"media_id": "m-1", "taps_forward": -1, "reach": 8})

    metrics = InstagramAdapter().parse_story_insights(payload)[0]["metrics"]

    assert metrics["taps_forward"] == -1
    assert is_below_threshold(metrics["taps_forward"]) is True
    assert is_below_threshold(metrics["reach"]) is False


def test_a_story_insight_without_a_media_id_is_ignored():
    assert InstagramAdapter().parse_story_insights(_change("story_insights", {"reach": 5})) == []


# ---------------------------------------------------------------- storage


class _Result:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, post=None) -> None:
        self.post = post

    async def execute(self, stmt):
        return _Result(self.post)


@pytest.mark.asyncio
async def test_the_metrics_are_stored_on_the_story():
    post = SimpleNamespace(post_id="m-1", insights=None)

    outcome = await StoryInsightsService.apply(
        _Session(post), TENANT, "instagram",
        [{"media_id": "m-1", "metrics": {"impressions": 120, "reach": 90}}],
    )

    assert post.insights == {"impressions": 120, "reach": 90}
    assert outcome["updated"] == 1


@pytest.mark.asyncio
async def test_a_second_delivery_merges_and_never_drops_an_earlier_metric():
    post = SimpleNamespace(post_id="m-1", insights={"impressions": 120})

    await StoryInsightsService.apply(
        _Session(post), TENANT, "instagram", [{"media_id": "m-1", "metrics": {"reach": 90}}]
    )

    assert post.insights == {"impressions": 120, "reach": 90}


@pytest.mark.asyncio
async def test_a_story_we_never_saw_is_counted_not_invented():
    outcome = await StoryInsightsService.apply(
        _Session(None), TENANT, "instagram", [{"media_id": "ghost", "metrics": {"reach": 1}}]
    )

    assert outcome["unknown_story"] == 1
    assert outcome["updated"] == 0

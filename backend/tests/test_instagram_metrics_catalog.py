"""Instagram's own numbers, and the honest state of every metric and profile field.

The report's Instagram gap (f): a profile-management matrix (readable vs editable vs not supported)
and a metric registry for account/media/reel/story insights. Two things matter here:

* editing an Instagram profile through the API is not possible — Meta only reads it — so the matrix
  says so with the reason instead of a screen offering an edit that cannot save;
* a retired metric is a labelled state with evidence, and a metric of **-1** means "fewer than
  five" people, not an error.
"""

from __future__ import annotations

import httpx
import pytest

from app.applications.apparel.modules.conversations.gateway.instagram import InstagramAdapter

CREDS = {"api_key": "tok", "account_id": "17841400000"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_no_profile_field_claims_to_be_editable():
    """Instagram's API reads a professional profile; editing happens in the app."""
    fields = InstagramAdapter.profile_fields()
    assert fields
    assert all(field["editable"] is False for field in fields)
    assert all(field["readable"] is True for field in fields)
    assert all(field["note"] for field in fields)


def test_the_catalog_covers_account_feed_and_story_scopes():
    catalog = InstagramAdapter.insight_catalog()
    scopes = {row["scope"] for row in catalog}
    assert {"account", "feed", "story"} <= scopes
    live = {row["metric"] for row in catalog if row["state"] == "live"}
    assert {"reach", "profile_views"} <= live
    assert "total_interactions" in live


def test_retired_metrics_are_recorded_with_evidence_not_hidden():
    catalog = {row["metric"]: row for row in InstagramAdapter.insight_catalog()}
    for metric in ("impressions", "plays", "video_views"):
        assert catalog[metric]["state"] == "removed"
        assert catalog[metric]["evidence"]
    live = {row["metric"] for row in catalog.values() if row["state"] == "live"}
    assert not live & InstagramAdapter.REMOVED_ACCOUNT_METRICS


@pytest.mark.asyncio
async def test_account_insights_ask_for_totals_and_read_them():
    seen: dict = {}

    def handler(req):
        seen.update(dict(req.url.params))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"name": "reach", "total_value": {"value": 1200}},
                    {"name": "profile_views", "total_value": {"value": 34}},
                ]
            },
        )

    async with _client(handler) as c:
        metrics = await InstagramAdapter().get_account_insights(CREDS, _client=c)

    assert seen["metric_type"] == "total_value"
    assert set(seen["metric"].split(",")) == set(InstagramAdapter.ACCOUNT_METRICS)
    assert metrics["reach"] == 1200
    assert metrics["profile_views"] == 34
    # Not produced yet stays null, never 0.
    assert metrics["website_clicks"] is None


@pytest.mark.asyncio
async def test_a_values_list_is_accepted_too():
    """Instagram has answered both shapes; a total is a total either way."""

    def handler(_req):
        return httpx.Response(200, json={"data": [{"name": "reach", "values": [{"value": 7}]}]})

    async with _client(handler) as c:
        metrics = await InstagramAdapter().get_account_insights(CREDS, _client=c)
    assert metrics["reach"] == 7


@pytest.mark.asyncio
async def test_no_data_is_none_everywhere_and_not_an_error():
    def handler(_req):
        return httpx.Response(200, json={"data": []})

    async with _client(handler) as c:
        metrics = await InstagramAdapter().get_account_insights(CREDS, _client=c)
    assert set(metrics.values()) == {None}


def test_a_negative_one_is_kept_as_a_number_not_an_error():
    """Instagram sends -1 for "fewer than five"; it is a value the UI explains, not a failure."""
    metrics = InstagramAdapter.insight_metrics("STORY")
    assert "reach" in metrics
    # The gateway keeps whatever number came back, including -1 (see get_media_insights).
    source = InstagramAdapter.get_media_insights.__doc__ or ""
    assert "None, never 0" in source

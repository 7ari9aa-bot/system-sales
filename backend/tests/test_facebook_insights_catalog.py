"""Page and post insights: what Meta still serves, and what it retired.

The report asked for insights expanded to the metrics the current Graph version supports, with
retired or unsupported ones shown as capability states rather than errors. Two halves:

* `insight_catalog()` — every metric this client knows, with an honest state and the evidence, so a
  screen draws a labelled card instead of an empty one;
* `insights_report()` — one metric Meta refuses no longer takes the whole panel down: the refused
  metric is dropped, the rest is asked for again, and the drop is reported.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway import facebook_pages as fp

CREDS = {"api_key": "tok", "account_id": "111"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_the_catalog_marks_retired_metrics_instead_of_hiding_them():
    catalog = {row["metric"]: row for row in fp.insight_catalog()}

    for metric in fp.PAGE_METRICS + fp.POST_METRICS:
        assert catalog[metric]["state"] == "live"
    # Retired by Meta, with the evidence a screen can show.
    assert catalog["page_impressions"]["state"] == "removed"
    assert catalog["page_impressions"]["evidence"]
    # No API surface at all.
    assert catalog["page_rating"]["state"] == "not_supported"


def test_no_metric_is_both_live_and_removed():
    catalog = fp.insight_catalog()
    live = {row["metric"] for row in catalog if row["state"] == "live"}
    assert not live & fp.REMOVED_METRICS
    # Every removed metric still appears in the catalog, so nothing silently vanishes.
    assert fp.REMOVED_METRICS <= {row["metric"] for row in catalog}


@pytest.mark.asyncio
async def test_a_live_metric_set_comes_back_with_nothing_unavailable():
    def handler(req):
        return httpx.Response(200, json={"data": [{"name": "page_follows", "values": []}]})

    async with _client(handler) as c:
        report = await fp.facebook_pages.insights_report(CREDS, _client=c)
    assert report["unavailable"] == []
    assert report["data"]


@pytest.mark.asyncio
async def test_a_metric_meta_refuses_is_dropped_and_reported_not_raised():
    """Meta rejects the whole request for one bad metric; the panel must still show the rest."""
    seen: list[str] = []

    def handler(req):
        metrics = req.url.params["metric"]
        seen.append(metrics)
        if "page_video_views" in metrics:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "(#100) The value of the parameter metric is invalid: "
                        "page_video_views is not available for this Page"
                    }
                },
            )
        return httpx.Response(200, json={"data": [{"name": "page_follows", "values": []}]})

    async with _client(handler) as c:
        report = await fp.facebook_pages.insights_report(CREDS, _client=c)

    assert report["unavailable"] == ["page_video_views"]
    assert "page_video_views" not in seen[1]
    assert "page_follows" in seen[1]
    assert report["data"]


@pytest.mark.asyncio
async def test_a_refusal_that_names_no_metric_falls_back_to_the_core_set_once():
    seen: list[str] = []

    def handler(req):
        metrics = req.url.params["metric"]
        seen.append(metrics)
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {"message": "(#100) invalid request"}})
        return httpx.Response(200, json={"data": []})

    async with _client(handler) as c:
        report = await fp.facebook_pages.insights_report(CREDS, _client=c)

    assert len(seen) == 2
    assert set(seen[1].split(",")) == set(fp.PAGE_METRICS[:3])
    assert report["unavailable"] == [m for m in fp.PAGE_METRICS if m not in fp.PAGE_METRICS[:3]]


@pytest.mark.asyncio
async def test_a_second_refusal_is_still_an_error():
    def handler(req):
        return httpx.Response(500, json={"error": {"message": "boom"}})

    async with _client(handler) as c:
        with pytest.raises(ExternalProviderError):
            await fp.facebook_pages.insights_report(CREDS, _client=c)


@pytest.mark.asyncio
async def test_post_insights_ask_the_post_and_not_the_page():
    seen: list[str] = []

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200, json={"data": []})

    async with _client(handler) as c:
        await fp.facebook_pages.insights_report(CREDS, kind="post", post_id="p1", _client=c)
    assert seen[0].endswith("/p1/insights")

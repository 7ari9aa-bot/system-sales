"""Reconciliation: what Meta has that FIHRIST does not, within the provider's bounds.

The report's Messenger gap (a). A backfill that nobody compares to local state is a walk with no
conclusion, so these tests pin the conclusion: what is missing locally, what is stale, and — the
honest part — when the walk could NOT prove absence.
"""

from __future__ import annotations

import pytest

from app.modules.conversations.messenger_reconcile import reconcile_page


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Http:
    """A fake Graph that answers one page of conversations, then has no next link."""

    def __init__(self, ids, *, next_url=None, error=None, status=200):
        self.ids = ids
        self.next_url = next_url
        self.error = error
        self.status = status
        self.calls: list[str] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append(url)
        if self.error:
            return _Resp({"error": {"message": self.error}}, status_code=self.status)
        data = [{"id": value} for value in self.ids] if "/conversations" in url else []
        payload = {"data": data}
        if self.next_url:
            payload["paging"] = {"next": self.next_url}
        return _Resp(payload)


@pytest.mark.asyncio
async def test_a_thread_meta_has_and_we_never_stored_is_named():
    http = _Http(["t.1", "t.2"])
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_thread_ids={"t.1"})
    assert result["missing_locally"] == ["t.2"]
    assert result["stale_locally"] == []


@pytest.mark.asyncio
async def test_a_thread_we_have_that_meta_no_longer_lists_is_reported_not_deleted():
    http = _Http(["t.1"])
    result = await reconcile_page(
        http, page_id="PAGE1", token="tok", local_thread_ids={"t.1", "t.9"}
    )
    assert result["stale_locally"] == ["t.9"]
    assert result["missing_locally"] == []


@pytest.mark.asyncio
async def test_a_capped_walk_does_not_claim_anything_is_missing():
    """Half a listing cannot prove absence, and must not be read as a gap."""
    http = _Http(["t.1", "t.2", "t.3"], next_url="https://graph.facebook.com/next")
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_thread_ids={"t.1"})
    assert result["stopped"] == "capped"
    assert result["missing_locally"] == []
    assert result["stale_locally"] == []


@pytest.mark.asyncio
async def test_a_rate_limit_is_an_error_with_its_reason_not_an_empty_result():
    http = _Http([], error="(#4) Application request limit reached", status=429)
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_thread_ids={"t.1"})
    assert result["stopped"] == "error"
    assert "limit" in (result["error"] or "")
    assert result["missing_locally"] == []


@pytest.mark.asyncio
async def test_the_walk_is_bounded_by_the_provider_limits():
    http = _Http([f"t.{i}" for i in range(5)])
    result = await reconcile_page(
        http, page_id="PAGE1", token="tok", local_thread_ids=set(), provider="messenger"
    )
    assert result["bounds"]["max_pages"] == 5
    assert result["bounds"]["max_items"] == 100
    # One page was enough, so only one call was made.
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_whatsapp_is_reported_as_unsupported_rather_than_empty():
    http = _Http([])
    result = await reconcile_page(
        http, page_id="WABA1", token="tok", local_thread_ids=set(), provider="whatsapp"
    )
    assert result["supported"] is False
    assert "no history API" in result["reason"]
    # Nothing was asked of Meta at all.
    assert http.calls == []

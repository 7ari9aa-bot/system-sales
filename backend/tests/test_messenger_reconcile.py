"""Reconciliation: what Meta has that FIHRIST does not, within the provider's bounds.

The report's Messenger gap (a). A backfill that nobody compares to local state is a walk with no
conclusion, so these tests pin the conclusion: what is missing locally, what is stale, and — the
honest part — when the walk could NOT prove absence.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.modules.conversations.messenger_reconcile import reconcile_page


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
        # Meta's conversation id is a THREAD id (t_...), distinct from the person in it (the PSID).
        data = (
            [
                {
                    "id": f"t_thread_{psid}",
                    "participants": {"data": [{"id": "PAGE1"}, {"id": psid}]},
                }
                for psid in self.ids
            ]
            if "/conversations" in url
            else []
        )
        payload = {"data": data}
        if self.next_url:
            payload["paging"] = {"next": self.next_url}
        return _Resp(payload)


@pytest.mark.asyncio
async def test_a_person_meta_lists_and_we_never_stored_is_named():
    http = _Http(["psid-1", "psid-2"])
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_person_ids={"psid-1"})
    assert result["missing_locally"] == ["psid-2"]
    assert result["stale_locally"] == []


@pytest.mark.asyncio
async def test_a_person_we_have_that_meta_no_longer_lists_is_reported_not_deleted():
    http = _Http(["psid-1"])
    result = await reconcile_page(
        http, page_id="PAGE1", token="tok", local_person_ids={"psid-1", "psid-9"}
    )
    assert result["stale_locally"] == ["psid-9"]
    assert result["missing_locally"] == []


@pytest.mark.asyncio
async def test_a_capped_walk_does_not_claim_anything_is_missing():
    """Half a listing cannot prove absence, and must not be read as a gap."""
    http = _Http(["psid-1", "psid-2", "psid-3"], next_url="https://graph.facebook.com/next")
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_person_ids={"psid-1"})
    assert result["stopped"] == "capped"
    assert result["missing_locally"] == []
    assert result["stale_locally"] == []


@pytest.mark.asyncio
async def test_a_rate_limit_is_an_error_with_its_reason_not_an_empty_result():
    http = _Http([], error="(#4) Application request limit reached", status=429)
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_person_ids={"psid-1"})
    assert result["stopped"] == "error"
    assert "limit" in (result["error"] or "")
    assert result["missing_locally"] == []


@pytest.mark.asyncio
async def test_the_walk_is_bounded_by_the_provider_limits():
    http = _Http([f"t.{i}" for i in range(5)])
    result = await reconcile_page(
        http, page_id="PAGE1", token="tok", local_person_ids=set(), provider="messenger"
    )
    assert result["bounds"]["max_pages"] == 5
    assert result["bounds"]["max_items"] == 100
    # One page was enough, so only one call was made.
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_whatsapp_is_reported_as_unsupported_rather_than_empty():
    http = _Http([])
    result = await reconcile_page(
        http, page_id="WABA1", token="tok", local_person_ids=set(), provider="whatsapp"
    )
    assert result["supported"] is False
    assert "no history API" in result["reason"]
    # Nothing was asked of Meta at all.
    assert http.calls == []


@pytest.mark.asyncio
async def test_thread_ids_are_never_compared_with_customer_identities():
    """Meta's thread id (t_thread_psid-1) is not the PSID a customer identity stores.

    Comparing them made every thread look missing and every customer stale. A customer we already
    hold must not be reported missing just because its thread id differs from its PSID.
    """
    http = _Http(["psid-1", "psid-2"])
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_person_ids={"psid-1"})
    assert result["missing_locally"] == ["psid-2"]
    assert result["stale_locally"] == []
    assert result["people_seen"] == 2
    assert "t_thread_psid-1" not in result["missing_locally"]


@pytest.mark.asyncio
async def test_the_page_itself_is_not_a_person():
    http = _Http(["psid-1"])
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_person_ids=set())
    assert "PAGE1" not in result["missing_locally"]


@pytest.mark.asyncio
async def test_the_comparison_is_labelled_limited_history():
    http = _Http(["psid-1"])
    result = await reconcile_page(http, page_id="PAGE1", token="tok", local_person_ids=set())
    assert result["limited_history"] is True


def test_instagram_reconcile_is_reported_unsupported_not_run_against_messenger():
    """The route must answer 'not supported yet' for Instagram, never walk a Page for it."""
    import inspect

    from app.applications.apparel.modules.customers.routers import integrations

    source = inspect.getsource(integrations.messenger_reconcile)
    branch = source.split('if integration.provider == "instagram":', 1)[1]
    assert "not_supported_for_this_channel_yet" in branch.split("config = ", 1)[0]

"""The code-to-channel exchange has a total deadline, not just one per call (A17).

It is up to six Graph calls one after another inside the browser's redirect. Each had its own 8 s
limit and nothing bounded the sum, so a slow Meta left the popup spinning for as long as 48 s with
no word. Running out of time is now the same retryable "Meta is unavailable" the owner already gets
for an outage.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import ExternalProviderError
from app.applications.apparel.modules.customers import meta_oauth as oauth


def test_the_budget_is_well_under_the_sum_of_the_per_call_limits():
    assert 0 < oauth.OAUTH_EXCHANGE_BUDGET_SECONDS < 6 * 8


async def test_a_slow_exchange_is_cut_off_and_reported_as_retryable(monkeypatch):
    async def slow(session, code, state_payload):
        await asyncio.sleep(5)
        return "facebook", "Shop"

    monkeypatch.setattr(oauth, "_meta_exchange_and_connect", slow)

    with pytest.raises(ExternalProviderError) as caught:
        await oauth._bounded_exchange(None, "code", {}, budget=0.05)

    assert caught.value.retryable is True
    assert "too long" in str(caught.value)


async def test_a_fast_exchange_is_returned_untouched(monkeypatch):
    async def fast(session, code, state_payload):
        return "messenger", "My Page"

    monkeypatch.setattr(oauth, "_meta_exchange_and_connect", fast)

    assert await oauth._bounded_exchange(None, "code", {}) == ("messenger", "My Page")


async def test_the_pause_to_choose_a_page_passes_through_the_deadline(monkeypatch):
    async def choose(session, code, state_payload):
        raise oauth.PageChoiceRequired("ticket-1", [{"id": "1", "name": "A"}])

    monkeypatch.setattr(oauth, "_meta_exchange_and_connect", choose)

    with pytest.raises(oauth.PageChoiceRequired):
        await oauth._bounded_exchange(None, "code", {}, budget=1)


async def test_other_failures_are_not_mistaken_for_a_timeout(monkeypatch):
    async def broken(session, code, state_payload):
        raise ValueError("boom")

    monkeypatch.setattr(oauth, "_meta_exchange_and_connect", broken)

    with pytest.raises(ValueError, match="boom"):
        await oauth._bounded_exchange(None, "code", {}, budget=1)


async def test_the_default_budget_is_the_module_constant(monkeypatch):
    seen = {}

    real = asyncio.timeout

    def spy(delay):
        seen["delay"] = delay
        return real(delay)

    async def fast(session, code, state_payload):
        return "facebook", "x"

    monkeypatch.setattr(oauth, "_meta_exchange_and_connect", fast)
    monkeypatch.setattr(oauth.asyncio, "timeout", spy)

    await oauth._bounded_exchange(None, "code", {})
    assert seen["delay"] == oauth.OAUTH_EXCHANGE_BUDGET_SECONDS

"""A grant Meta says is gone must send the owner back through the link, not retry forever (A4).

Only 190/102 and 401/403 used to mean "reconnect". A dead channel kept looking `active` and was
retried every twelve hours for as long as nobody noticed. These pin the whole documented set, keep
the transient failures retryable, and make sure the refusal text never echoes Meta's response.
"""

from __future__ import annotations

import httpx
import pytest

from app.workers import meta_token_refresh as refresh


def _client(status: int, body: dict | str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _refresh_source(status: int, body: dict | str):
    async with _client(status, body) as client:
        return await refresh._refresh_source_token(
            client, "old-token", app_id="app", app_secret="secret"
        )


async def _refresh_page(status: int, body: dict | str):
    async with _client(status, body) as client:
        return await refresh._refresh_page_token(client, source_token="tok", page_id="P1")


@pytest.mark.parametrize("code", [190, 102, 10, 200, 368])
async def test_every_documented_dead_grant_code_asks_the_owner_to_reconnect(code):
    with pytest.raises(refresh.MetaNeedsReauthorization):
        await _refresh_source(400, {"error": {"code": code, "message": "x"}})


@pytest.mark.parametrize("subcode", [458, 459, 460, 463, 467])
async def test_the_session_subcodes_under_190_are_dead_too(subcode):
    error = {"code": 190, "error_subcode": subcode, "message": "Session is invalid"}
    with pytest.raises(refresh.MetaNeedsReauthorization):
        await _refresh_source(400, {"error": error})


@pytest.mark.parametrize("status", [401, 403])
async def test_an_http_auth_refusal_is_a_dead_grant_whatever_the_body_says(status):
    with pytest.raises(refresh.MetaNeedsReauthorization):
        await _refresh_source(status, {"error": {"code": 1, "message": "x"}})


@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_rate_limits_and_outages_are_retried_not_treated_as_dead(status):
    with pytest.raises(httpx.RequestError):
        await _refresh_source(status, {"error": {"code": 4, "message": "slow down"}})


async def test_an_unrecognised_error_is_a_plain_failure_that_keeps_the_channel():
    with pytest.raises(ValueError) as caught:
        await _refresh_source(400, {"error": {"code": 2500, "message": "weird"}})
    assert not isinstance(caught.value, refresh.MetaNeedsReauthorization)
    assert "2500" in str(caught.value)


async def test_the_failure_text_never_echoes_the_provider_body():
    leaky = {"error": {"code": 2500, "message": "token EAAB-LEAK was rejected"}}
    with pytest.raises(ValueError) as caught:
        await _refresh_source(400, leaky)
    assert "EAAB-LEAK" not in str(caught.value)

    with pytest.raises(refresh.MetaNeedsReauthorization) as dead:
        await _refresh_source(400, {"error": {"code": 190, "message": "token EAAB-LEAK"}})
    assert "EAAB-LEAK" not in str(dead.value)


async def test_an_html_error_page_is_a_failure_not_a_crash():
    with pytest.raises(ValueError):
        await _refresh_source(502, "<html>Bad gateway</html>")


@pytest.mark.parametrize("code", [190, 102, 10, 200, 368])
async def test_the_page_token_reload_uses_the_same_dead_grant_set(code):
    with pytest.raises(refresh.MetaNeedsReauthorization):
        await _refresh_page(400, {"error": {"code": code, "message": "x"}})


async def test_a_page_that_is_no_longer_listed_is_a_dead_grant():
    with pytest.raises(refresh.MetaNeedsReauthorization):
        await _refresh_page(200, {"data": [{"id": "OTHER", "access_token": "t"}]})


def test_the_dead_grant_set_is_exactly_what_meta_documents():
    assert refresh._DEAD_GRANT_CODES == frozenset({190, 102, 10, 200, 368})
    assert refresh._grant_is_dead({"code": 368}, 400) is True
    assert refresh._grant_is_dead({"code": 4}, 400) is False
    assert refresh._grant_is_dead(None, 200) is False
    assert refresh._grant_is_dead("not a dict", 200) is False

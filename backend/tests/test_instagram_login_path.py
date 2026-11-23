"""Instagram Login: the standalone grant, with no Facebook Page in between.

Meta runs two Instagram logins. Facebook Login returns a PAGE token and lives on
graph.facebook.com; Instagram Login returns an INSTAGRAM token and lives on graph.instagram.com.
An account with no linked Page can only use the second, so it must exist as its own path and must
never ask for a Page permission.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.conversations.gateway.instagram import InstagramAdapter
from app.modules.customers import instagram_login


def test_the_authorize_url_is_instagrams_own_and_asks_for_no_page_scope():
    url = instagram_login.authorize_url(
        app_id="ig-app", redirect_uri="https://api.fihrist.world/cb", state="st-1"
    )
    assert url.startswith("https://www.instagram.com/oauth/authorize?")
    assert "client_id=ig-app" in url
    assert "instagram_business_manage_messages" in url
    assert "instagram_manage_insights" in url
    # the whole point: a Page permission here would make Meta reject the dialog
    assert "pages_" not in url
    assert "instagram_business_account" not in url


@pytest.mark.asyncio
async def test_the_code_becomes_a_long_lived_instagram_token_and_an_account():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url.copy_with(query=None))))
        if str(request.url).startswith("https://api.instagram.com/oauth/access_token"):
            assert b"grant_type=authorization_code" in request.content
            return httpx.Response(200, json={"access_token": "short", "user_id": 1789})
        if "grant_type=ig_exchange_token" in str(request.url):
            return httpx.Response(200, json={"access_token": "long-lived", "expires_in": 5184000})
        if str(request.url).startswith("https://graph.instagram.com/me"):
            return httpx.Response(
                200,
                json={"user_id": "1789", "username": "fihrist.store", "account_type": "BUSINESS"},
            )
        raise AssertionError(f"unexpected call {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        account = await instagram_login.exchange_code(
            http, app_id="ig-app", app_secret="sec", redirect_uri="https://api/cb", code="c-1"
        )

    assert account["access_token"] == "long-lived"
    assert account["user_id"] == "1789"
    assert account["account_type"] == "BUSINESS"
    hosts = [url.split("/")[2] for _, url in seen]
    assert hosts == ["api.instagram.com", "graph.instagram.com", "graph.instagram.com"]
    # the secret travels in the body, never in a URL that could be logged
    assert all("sec" not in url for _, url in seen)


@pytest.mark.asyncio
async def test_a_personal_account_is_refused_with_a_reason_the_owner_can_act_on():
    def handler(request: httpx.Request) -> httpx.Response:
        if "access_token" in str(request.url) and request.method == "POST":
            return httpx.Response(200, json={"access_token": "short", "user_id": 5})
        if "ig_exchange_token" in str(request.url):
            return httpx.Response(200, json={"access_token": "long", "expires_in": 60})
        return httpx.Response(200, json={"user_id": "5", "account_type": "PERSONAL"})

    class _Session:
        async def execute(self, *a, **k):
            raise AssertionError("a personal account must be refused before anything is stored")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(Exception) as exc:
            await instagram_login.exchange_and_connect(
                _Session(),
                http,
                code="c",
                tenant_id=__import__("uuid").uuid4(),
                app_id="a",
                app_secret="s",
                redirect_uri="https://api/cb",
            )
    assert "احترافي" in str(exc.value)


@pytest.mark.asyncio
async def test_the_gateway_sends_a_standalone_token_to_instagram_not_facebook():
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url.copy_with(query=None)))
        return httpx.Response(200, json={"data": []})

    creds = {"api_key": "ig-token", "account_id": "1789", "login": "instagram"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await InstagramAdapter().list_media(creds, _client=http)

    assert urls and urls[0].startswith("https://graph.instagram.com/")
    assert "graph.facebook.com" not in urls[0]

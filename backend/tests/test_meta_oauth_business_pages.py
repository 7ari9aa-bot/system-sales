"""A Page owned by a Business Portfolio is missing from /me/accounts; the connect must still find it."""

from __future__ import annotations

import pytest

from app.modules.customers import meta_oauth


class _Resp:
    def __init__(self, payload):
        self.payload = payload
        self.is_success = True

    def json(self):
        return self.payload


class _Http:
    def __init__(self, routes):
        self.routes = routes
        self.urls: list[str] = []

    async def get(self, url, params=None):
        self.urls.append(url)
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                if isinstance(payload, Exception):
                    raise payload
                return _Resp(payload)
        return _Resp({"data": []})


@pytest.mark.asyncio
async def test_pages_owned_by_a_portfolio_are_found_with_their_token_and_ig_account(monkeypatch):
    monkeypatch.setattr(meta_oauth, "_graph_json", lambda response, step: response.json())
    page = {
        "id": "1504830666036731",
        "name": "Fidsas",
        "access_token": "page-token",
        "instagram_business_account": {"id": "17841400000000000"},
    }
    http = _Http(
        {
            "/me/businesses": {"data": [{"id": "B1"}]},
            "/B1/owned_pages": {"data": [page, {"id": "9", "name": "no token"}]},
        }
    )
    pages = await meta_oauth._business_portfolio_pages(http, "user-token")
    assert pages == [page]


@pytest.mark.asyncio
async def test_a_graph_failure_returns_no_pages_instead_of_breaking_the_connect(monkeypatch):
    monkeypatch.setattr(meta_oauth, "_graph_json", lambda response, step: response.json())
    http = _Http({"/me/businesses": RuntimeError("boom")})
    assert await meta_oauth._business_portfolio_pages(http, "user-token") == []

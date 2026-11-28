"""Second-review diagnostics: scopes, Graph host and what the connection model reads."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.applications.apparel.modules.customers import meta_channel_diagnostics as diag
from app.applications.apparel.modules.customers.meta_linking import MetaPageConnection


def test_facebook_management_does_not_require_the_messenger_permission() -> None:
    assert "pages_messaging" not in diag._required_scopes("facebook")
    # Messenger keeps its own.
    assert "pages_messaging" in diag._required_scopes("messenger")


def test_instagram_login_is_held_to_instagram_login_scopes_not_page_scopes() -> None:
    scopes = diag._required_scopes("instagram", {"login": "instagram"})
    assert "instagram_business_manage_messages" in scopes
    assert not [s for s in scopes if s.startswith("pages_")]
    # The Facebook-Login Instagram keeps the Page permission it genuinely needs.
    assert "pages_messaging" in diag._required_scopes("instagram", {})


@pytest.mark.asyncio
async def test_instagram_login_probes_go_to_the_instagram_host() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await diag.probe_permissions(http, token="t", graph=diag.INSTAGRAM_LOGIN_GRAPH)
        await diag.probe_subscription(
            http, asset_id="1", token="t", app_id=None, graph=diag.INSTAGRAM_LOGIN_GRAPH
        )
        await diag.probe_permissions(http, token="t")
    assert seen[0].startswith("https://graph.instagram.com/")
    assert seen[1].startswith("https://graph.instagram.com/")
    assert seen[2].startswith("https://graph.facebook.com/")


def _row(provider: str, config: dict, health: dict | None = None):
    return SimpleNamespace(
        provider=provider,
        config=config,
        status="active",
        credentials={"k": "v"},
        webhook_health=health,
    )


def test_the_connection_reads_the_real_seen_fields() -> None:
    row = _row("messenger", {"account_id": "P1"}, {"seen_fields": {"messages": "2026-01-01"}})
    assert MetaPageConnection.from_integration(row).seen_fields == frozenset({"messages"})


def test_the_connection_finds_a_messenger_page_in_account_id() -> None:
    assert (
        MetaPageConnection.from_integration(_row("messenger", {"account_id": "P1"})).page_id == "P1"
    )
    assert MetaPageConnection.from_integration(_row("facebook", {"page_id": "P2"})).page_id == "P2"


def test_an_instagram_account_id_is_never_taken_for_a_page() -> None:
    assert (
        MetaPageConnection.from_integration(_row("instagram", {"account_id": "IG1"})).page_id
        is None
    )


def test_no_health_means_nothing_was_seen() -> None:
    assert (
        MetaPageConnection.from_integration(_row("facebook", {"page_id": "P"}, None)).seen_fields
        == frozenset()
    )

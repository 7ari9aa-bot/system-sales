"""The disconnect route removes the Meta subscription and never depends on Meta answering."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.core.secrets import encrypt_credentials_dict
from app.modules.customers import meta_unsubscribe as mu
from app.modules.customers.routers import integrations as routes
from app.modules.platform.models import Integration
from tests.test_customers_http_surface import TENANT, _call


def _row(provider="messenger", status="active", config=None, credentials=None, **kw):
    return Integration(
        id=kw.pop("id", uuid.uuid4()),
        tenant_id=TENANT,
        provider=provider,
        kind="channel",
        status=status,
        config=config or {"account_id": "111"},
        credentials=encrypt_credentials_dict(credentials or {"api_key": "PAGE-TOKEN"}),
        **kw,
    )


# ------------------------------------------------------------------ the route's wiring


async def test_disconnect_records_what_meta_answered(monkeypatch) -> None:
    async def removed(ctx, integration):
        return {"state": mu.DONE, "at": "2026-01-01T00:00:00+00:00"}

    monkeypatch.setattr(routes, "_remove_meta_subscription", removed)
    row = _row()
    response, _ = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/disconnect",
        rows=[row],
        permissions={"settings:write"},
        body={"confirm": True},
    )
    assert response.status_code == 200, response.text
    assert row.status == "disconnected"
    assert row.config["_meta_cleanup"]["state"] == mu.DONE
    assert response.json()["meta_cleanup"]["state"] == mu.DONE


async def test_a_meta_failure_still_disconnects_locally_and_stays_retryable(monkeypatch) -> None:
    async def refused(ctx, integration):
        return {"state": mu.PENDING, "at": "t", "reason": "meta_refused", "meta": {"code": 200}}

    monkeypatch.setattr(routes, "_remove_meta_subscription", refused)
    row = _row()
    response, _ = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/disconnect",
        rows=[row],
        permissions={"settings:write"},
        body={"confirm": True},
    )
    assert response.status_code == 200, response.text
    assert row.status == "disconnected"  # the local disconnect is never undone by Meta
    assert mu.needs_cleanup(row.config) is True
    assert "PAGE-TOKEN" not in response.text


async def test_a_channel_with_no_meta_subscription_records_nothing(monkeypatch) -> None:
    async def none(ctx, integration):
        return None

    monkeypatch.setattr(routes, "_remove_meta_subscription", none)
    row = _row(provider="telegram", config={})
    response, _ = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/disconnect",
        rows=[row],
        permissions={"settings:write"},
        body={"confirm": True},
    )
    assert response.status_code == 200, response.text
    assert "_meta_cleanup" not in row.config
    assert response.json()["meta_cleanup"] is None


# ------------------------------------------------------------------ retry


async def test_retry_runs_the_removal_again_for_a_pending_channel(monkeypatch) -> None:
    calls: list[str] = []

    async def removed(ctx, integration):
        calls.append(integration.provider)
        return {"state": mu.DONE, "at": "t"}

    monkeypatch.setattr(routes, "_remove_meta_subscription", removed)
    row = _row(
        status="disconnected", config={"account_id": "1", "_meta_cleanup": {"state": "pending"}}
    )
    response, _ = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/retry-meta-cleanup",
        rows=[row],
        permissions={"settings:write"},
    )
    assert response.status_code == 200, response.text
    assert calls == ["messenger"]
    assert row.config["_meta_cleanup"]["state"] == mu.DONE


async def test_retry_does_not_call_meta_twice_once_it_succeeded(monkeypatch) -> None:
    async def boom(ctx, integration):
        raise AssertionError("Meta was called again")

    monkeypatch.setattr(routes, "_remove_meta_subscription", boom)
    row = _row(
        status="disconnected", config={"account_id": "1", "_meta_cleanup": {"state": "done"}}
    )
    response, _ = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/retry-meta-cleanup",
        rows=[row],
        permissions={"settings:write"},
    )
    assert response.status_code == 200, response.text


async def test_retry_refuses_a_channel_that_is_still_connected(monkeypatch) -> None:
    async def boom(ctx, integration):
        raise AssertionError("a live channel must keep its subscription")

    monkeypatch.setattr(routes, "_remove_meta_subscription", boom)
    row = _row(status="active")
    response, _ = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/retry-meta-cleanup",
        rows=[row],
        permissions={"settings:write"},
    )
    assert response.status_code == 400, response.text


async def test_retry_needs_settings_write() -> None:
    row = _row(status="disconnected")
    response, _ = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/retry-meta-cleanup",
        rows=[row],
        permissions=set(),
    )
    assert response.status_code == 403, response.text


# ------------------------------------------------------------------ which Page, which siblings


class _Ctx:
    """Just what _remove_meta_subscription reads: tenant, a session returning sibling rows."""

    def __init__(self, siblings):
        self.tenant_id = TENANT

        class _Scalars:
            def all(_self):
                return siblings

        class _Result:
            def scalars(_self):
                return _Scalars()

        class _Session:
            async def execute(_self, stmt):
                return _Result()

        self.session = _Session()


@pytest.fixture
def graph(monkeypatch):
    """Route every httpx client the route builds into one recorder."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"success": True})

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    async def decrypt(session, integration):
        from app.core.secrets import decrypt_credentials_dict

        return decrypt_credentials_dict(integration.credentials)

    monkeypatch.setattr(routes.IntegrationCredentialsService, "decrypt", staticmethod(decrypt))
    return calls


async def test_messenger_uses_its_account_id_as_the_page(graph) -> None:
    out = await routes._remove_meta_subscription(_Ctx([]), _row("messenger"))
    assert out["state"] == mu.DONE
    assert graph[0].url.path.endswith("/111/subscribed_apps")
    assert graph[0].method == "DELETE"


async def test_instagram_uses_the_page_in_its_connection_record_not_the_ig_account(graph) -> None:
    row = _row(
        "instagram",
        config={"account_id": "IG-9"},
        credentials={"api_key": "T", "_meta": {"page_id": "555"}},
    )
    await routes._remove_meta_subscription(_Ctx([]), row)
    assert graph[0].url.path.endswith("/555/subscribed_apps")


async def test_facebook_uses_its_page_id_and_page_token_key(graph) -> None:
    row = _row("facebook", config={"page_id": "777"}, credentials={"page_access_token": "FT"})
    await routes._remove_meta_subscription(_Ctx([]), row)
    assert graph[0].url.path.endswith("/777/subscribed_apps")
    assert graph[0].url.params["access_token"] == "FT"


async def test_a_sibling_on_the_same_page_keeps_the_subscription(graph) -> None:
    facebook = _row("facebook", config={"page_id": "111"}, credentials={"page_access_token": "T"})
    messenger = _row("messenger", config={"account_id": "111"})
    out = await routes._remove_meta_subscription(_Ctx([messenger]), facebook)
    assert out["state"] == mu.KEPT
    assert graph[0].method == "POST"  # narrowed, never deleted under the live Messenger channel


async def test_a_sibling_on_ANOTHER_page_does_not_keep_this_subscription(graph) -> None:
    facebook = _row("facebook", config={"page_id": "111"}, credentials={"page_access_token": "T"})
    other = _row("messenger", config={"account_id": "222"})
    out = await routes._remove_meta_subscription(_Ctx([other]), facebook)
    assert out["state"] == mu.DONE
    assert graph[0].method == "DELETE"


async def test_whatsapp_removes_the_waba(graph) -> None:
    row = _row(
        "whatsapp",
        config={"phone_number_id": "1", "waba_id": "999"},
        credentials={"access_token": "WT"},
    )
    out = await routes._remove_meta_subscription(_Ctx([]), row)
    assert out["state"] == mu.DONE
    assert graph[0].url.path.endswith("/999/subscribed_apps")


async def test_a_channel_missing_its_ids_is_not_needed_not_an_error(graph) -> None:
    row = _row("whatsapp", config={"phone_number_id": "1"}, credentials={"access_token": "WT"})
    out = await routes._remove_meta_subscription(_Ctx([]), row)
    assert out["state"] == mu.NOT_NEEDED
    assert graph == []


async def test_telegram_has_nothing_to_remove_on_meta(graph) -> None:
    assert await routes._remove_meta_subscription(_Ctx([]), _row("telegram", config={})) is None
    assert graph == []

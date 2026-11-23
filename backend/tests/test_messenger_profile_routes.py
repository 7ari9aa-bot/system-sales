"""The Messenger settings routes: greeting, Get Started, persistent menu, ice breakers.

The gateway client existed and was tested, but nothing called it — the Page's Messenger profile
could only be changed in Meta Business Suite. These tests drive the real routes and pin the three
promises the router makes:

* Messenger is its own function: without `pages_messaging` the write is refused with the
  permission named, before any Meta call;
* Meta answers first: a refusal never comes back as "saved";
* a read returns what Meta holds, so a setting made outside FIHRIST still shows.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.errors import PermissionDeniedError
from app.modules.conversations.routers import messenger_profile as mp
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from tests.security.test_role_authz_matrix import _authz_app

pytestmark = pytest.mark.asyncio

PERMS = {"conversations:read", "conversations:write"}
CONNECTED = {"page_access_token": "tok", "account_id": "111", "granted_scopes": ["pages_messaging"]}


def _graph(seen: list, *, status: int = 200, payload: dict | None = None):
    """A Graph stand-in that records what the route asked for."""

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, dict(req.url.params), req.content.decode() or None))
        if payload is not None:
            return httpx.Response(status, json=payload)
        return httpx.Response(status, json={"success": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _request(db, ctx, method, path, *, body=None, config=None, seen=None, **graph_kw):
    app = _authz_app()
    inner = TenantContext(
        session=db,
        user=AuthedUser(
            id=ctx.user.id, tenant_id=ctx.tenant_id, role_code="x", is_platform_admin=False
        ),
        tenant_id=ctx.tenant_id,
        role_code="x",
        permission_codes=PERMS,
    )
    app.dependency_overrides[get_tenant_ctx] = lambda: inner

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db

    client = _graph(seen if seen is not None else [], **graph_kw)

    async def _creds(_ctx, *, send):
        if config is _REFUSED:
            raise PermissionDeniedError("Messenger profile settings need the pages_messaging")
        return config if config is not None else CONNECTED

    original_creds, original_http = mp._credentials, mp._http
    mp._credentials = _creds
    mp._http = lambda _request: client
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=20
        ) as api:
            return await api.request(method, path, json=body)
    finally:
        mp._credentials, mp._http = original_creds, original_http
        await client.aclose()


_REFUSED = object()


async def test_a_greeting_is_sent_to_meta_before_anything_is_reported_saved(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "PUT",
        "/api/v1/messenger/profile/greeting",
        body={"text": "أهلاً بيك في المتجر"},
        seen=seen,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"setting": "greeting", "saved": True}
    method, path, _params, raw = seen[0]
    assert method == "POST" and path.endswith("/me/messenger_profile")
    assert '"greeting"' in raw and "أهلاً بيك في المتجر" in raw


async def test_the_four_settings_this_router_owns_are_the_four_meta_stores():
    assert mp.SETTINGS == ("greeting", "get_started", "persistent_menu", "ice_breakers")


async def test_an_unknown_setting_is_refused_without_calling_meta(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db, tenant_ctx, "PUT", "/api/v1/messenger/profile/whatever", body={}, seen=seen
    )
    assert resp.status_code == 400
    assert seen == []


async def test_a_greeting_longer_than_meta_allows_is_refused_before_the_call(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "PUT",
        "/api/v1/messenger/profile/greeting",
        body={"text": "x" * 161},
        seen=seen,
    )
    assert resp.status_code == 400
    assert seen == []


async def test_without_pages_messaging_the_write_is_refused_and_meta_is_never_called(
    db, tenant_ctx
):
    """Messenger is its own function: the Page-management permission does not stand in for it."""
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "PUT",
        "/api/v1/messenger/profile/get_started",
        body={"payload": "GET_STARTED"},
        config=_REFUSED,
        seen=seen,
    )
    assert resp.status_code == 403
    assert seen == []


async def test_a_refusal_from_meta_is_an_error_not_a_saved_setting(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "PUT",
        "/api/v1/messenger/profile/ice_breakers",
        body={"questions": [{"question": "الشحن بيوصل امتى؟"}]},
        seen=seen,
        status=400,
        payload={"error": {"message": "(#100) invalid ice breakers"}},
    )
    assert resp.status_code == 400
    assert "invalid ice breakers" in resp.text


async def test_reading_the_profile_returns_what_meta_holds(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db,
        tenant_ctx,
        "GET",
        "/api/v1/messenger/profile",
        seen=seen,
        payload={
            "data": [
                {
                    "greeting": [{"locale": "default", "text": "أهلاً"}],
                    "get_started": {"payload": "START"},
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    settings = resp.json()["settings"]
    assert settings["greeting"] == [{"locale": "default", "text": "أهلاً"}]
    assert settings["get_started"] == {"payload": "START"}
    assert settings["persistent_menu"] is None
    method, path, params, _raw = seen[0]
    assert method == "GET" and path.endswith("/me/messenger_profile")
    assert set(params["fields"].split(",")) == set(mp.SETTINGS)


async def test_clearing_a_setting_deletes_only_that_field(db, tenant_ctx):
    seen: list = []
    resp = await _request(
        db, tenant_ctx, "DELETE", "/api/v1/messenger/profile/persistent_menu", seen=seen
    )
    assert resp.status_code == 200, resp.text
    method, path, params, _raw = seen[0]
    assert method == "DELETE" and path.endswith("/me/messenger_profile")
    assert params["fields"] in ("persistent_menu", ["persistent_menu"])

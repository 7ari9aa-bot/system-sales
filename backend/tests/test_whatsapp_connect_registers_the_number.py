"""Connecting WhatsApp must leave a number Meta will actually deliver messages to.

Embedded Signup adds and verifies the number inside Meta's window, but a number only sends and
receives once it is REGISTERED, and registering is an API call (WhatsApp Manager cannot do it). This
drives the real ``/complete`` route against a real database with Meta faked at the HTTP layer, and
checks the stored row: connected, with the token still readable and the PIN we set kept encrypted.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.secrets import decrypt_credentials_dict
from app.applications.apparel.modules.customers import meta_whatsapp_signup as signup
from app.modules.platform.models import Integration
from tests._pos_helpers import ctx_for
from tests.test_pos_return_audit_and_day_holder import _app

pytestmark = pytest.mark.asyncio

_COMPLETE = "/api/v1/integrations/whatsapp/embedded-signup/complete"
_BODY = {"code": "AQD" + "x" * 30, "waba_id": "900", "phone_number_id": "777"}


def _fake_meta(
    *, status: str, seen: list[tuple[str, str]], register_ok: bool = True, on_biz_app: bool = True
):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append((request.method, path))
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "TOKEN-123"})
        if path.endswith("/phone_numbers"):
            return httpx.Response(200, json={"data": [{"id": "777"}]})
        if path.endswith("/subscribed_apps"):
            return httpx.Response(200, json={"success": True})
        if path.endswith("/register"):
            if not register_ok:
                return httpx.Response(400, json={"error": {"code": 100, "message": "no"}})
            return httpx.Response(200, json={"success": True})
        if request.method == "GET" and "status" in request.url.params.get("fields", ""):
            return httpx.Response(200, json={"status": status})
        # display name + the verifier's own read of the number, including the two fields the
        # connect requires: the number is on the Business app AND the Cloud API (coexistence).
        return httpx.Response(
            200,
            json={
                "id": "777",
                "display_phone_number": "+20 100 000 0000",
                "verified_name": "Fihrist Shop",
                "is_on_biz_app": on_biz_app,
                "platform_type": "CLOUD_API",
            },
        )

    return handler


async def _connect(monkeypatch, db, tenant_ctx, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        signup.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(signup, "_whatsapp_config", lambda: ("app", "secret", "cfg"))
    owner = await ctx_for(db, tenant_ctx, "owner")
    async with AsyncClient(transport=ASGITransport(app=_app(owner)), base_url="http://t") as c:
        return await c.post(_COMPLETE, json=_BODY)


async def _stored(db, tenant_ctx):
    row = (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_ctx.tenant_id, Integration.provider == "whatsapp"
            )
        )
    ).scalar_one()
    return row


async def test_a_coexistence_number_connects_without_spending_a_register_call(
    monkeypatch, db, tenant_ctx
) -> None:
    """Coexistence numbers stay registered inside the Business app, so the connect must NOT spend
    one of Meta's ten register attempts, and it stores no PIN."""
    seen: list[tuple[str, str]] = []
    r = await _connect(monkeypatch, db, tenant_ctx, _fake_meta(status="PENDING", seen=seen))
    assert r.status_code == 201, r.text

    paths = [p for _m, p in seen]
    assert not any(p.endswith("/register") for p in paths)
    # The WABA is still subscribed, otherwise nothing is ever delivered.
    assert f"/{signup._GRAPH_VERSION}/900/subscribed_apps" in paths

    row = await _stored(db, tenant_ctx)
    assert row.status == "active"
    creds = decrypt_credentials_dict(row.credentials)
    assert creds["access_token"] == "TOKEN-123"
    assert "registration_pin" not in creds


async def test_a_number_meta_already_connected_is_left_alone_and_stores_no_pin(
    monkeypatch, db, tenant_ctx
) -> None:
    seen: list[tuple[str, str]] = []
    r = await _connect(monkeypatch, db, tenant_ctx, _fake_meta(status="CONNECTED", seen=seen))
    assert r.status_code == 201, r.text
    assert not any(p.endswith("/register") for _m, p in seen)
    creds = decrypt_credentials_dict((await _stored(db, tenant_ctx)).credentials)
    assert "registration_pin" not in creds and creds["access_token"] == "TOKEN-123"


async def test_a_cloud_api_only_number_is_refused_and_stores_nothing(
    monkeypatch, db, tenant_ctx
) -> None:
    """A number that is not on the WhatsApp Business app cannot use coexistence, so the connect is
    refused before anything is written."""
    seen: list[tuple[str, str]] = []
    handler = _fake_meta(status="PENDING", seen=seen, on_biz_app=False)
    r = await _connect(monkeypatch, db, tenant_ctx, handler)
    assert r.status_code >= 400
    assert not any(p.endswith("/subscribed_apps") for _m, p in seen)
    rows = (
        (
            await db.execute(
                select(Integration).where(
                    Integration.tenant_id == tenant_ctx.tenant_id,
                    Integration.provider == "whatsapp",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == []

"""Connecting WhatsApp must leave a number Meta will actually deliver messages to.

Embedded Signup adds and verifies the number inside Meta's window, but a number only sends and
receives once it is REGISTERED, and registering is an API call (WhatsApp Manager cannot do it). This
drives the real ``/complete`` route against a real database with Meta faked at the HTTP layer, and
checks the stored row: connected, with the token still readable and the PIN we set kept encrypted.
"""

from __future__ import annotations

import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.secrets import decrypt_credentials_dict
from app.modules.customers import meta_whatsapp_signup as signup
from app.modules.platform.models import Integration
from tests._pos_helpers import ctx_for
from tests.test_pos_return_audit_and_day_holder import _app

pytestmark = pytest.mark.asyncio

_COMPLETE = "/api/v1/integrations/whatsapp/embedded-signup/complete"
_BODY = {"code": "AQD" + "x" * 30, "waba_id": "900", "phone_number_id": "777"}


def _fake_meta(*, status: str, seen: list[tuple[str, str]], register_ok: bool = True):
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
        # display name + the verifier's own read of the number
        return httpx.Response(
            200,
            json={
                "id": "777",
                "display_phone_number": "+20 100 000 0000",
                "verified_name": "Fihrist Shop",
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


async def test_connecting_an_unregistered_number_registers_it_and_keeps_the_pin_encrypted(
    monkeypatch, db, tenant_ctx
) -> None:
    seen: list[tuple[str, str]] = []
    r = await _connect(monkeypatch, db, tenant_ctx, _fake_meta(status="PENDING", seen=seen))
    assert r.status_code == 201, r.text

    assert ("POST", f"/{signup._GRAPH_VERSION}/777/register") in seen
    order = [p for _m, p in seen]
    # register first: a number Meta refuses must not leave a subscription behind (W8)
    assert order.index(f"/{signup._GRAPH_VERSION}/777/register") < order.index(
        f"/{signup._GRAPH_VERSION}/900/subscribed_apps"
    )

    row = await _stored(db, tenant_ctx)
    assert row.status == "active"
    creds = decrypt_credentials_dict(row.credentials)
    assert creds["access_token"] == "TOKEN-123"
    assert len(creds["registration_pin"]) == 6 and creds["registration_pin"].isdigit()
    # at rest it is ciphertext, and the PIN never reaches the API response
    assert creds["registration_pin"] not in json.dumps(row.credentials)
    assert creds["registration_pin"] not in r.text


async def test_a_number_meta_already_connected_is_left_alone_and_stores_no_pin(
    monkeypatch, db, tenant_ctx
) -> None:
    seen: list[tuple[str, str]] = []
    r = await _connect(monkeypatch, db, tenant_ctx, _fake_meta(status="CONNECTED", seen=seen))
    assert r.status_code == 201, r.text
    assert not any(p.endswith("/register") for _m, p in seen)
    creds = decrypt_credentials_dict((await _stored(db, tenant_ctx)).credentials)
    assert "registration_pin" not in creds and creds["access_token"] == "TOKEN-123"


async def test_a_refused_registration_stores_nothing(monkeypatch, db, tenant_ctx) -> None:
    """A number Meta will not register cannot receive: fail the connect, do not store it as live."""
    seen: list[tuple[str, str]] = []
    handler = _fake_meta(status="PENDING", seen=seen, register_ok=False)
    r = await _connect(monkeypatch, db, tenant_ctx, handler)
    assert r.status_code >= 400
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

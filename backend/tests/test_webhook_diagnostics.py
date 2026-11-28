"""Silent webhook refusals now leave a named, counted trace (and still answer the same way)."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import meta_diagnostics as md
from app.main import create_app

SECRET = "test-app-secret"


@pytest.fixture
def issues(monkeypatch):
    seen: list[tuple[str, str | None, dict]] = []

    async def fake(key, *, channel=None, tenant_id=None, details=None):
        seen.append((key, channel, details or {}))

    monkeypatch.setattr(md, "record_channel_issue", fake)
    return seen


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(
        "app.applications.apparel.modules.conversations.gateway.whatsapp.get_settings",
        lambda: type("S", (), {"whatsapp_app_secret": SECRET})(),
    )


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _sig(raw: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


async def test_bad_signature_is_named_and_still_a_403(client, issues):
    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        content=b'{"object":"whatsapp_business_account"}',
        headers={"content-type": "application/json", "x-hub-signature-256": "sha256=deadbeef"},
    )
    assert response.status_code == 403
    keys = [k for k, _c, _d in issues]
    assert keys == ["webhook.bad_signature"]
    assert issues[0][1] == "whatsapp"
    assert issues[0][2]["has_signature_header"] is True


async def test_missing_signature_header_is_visible_in_the_details(client, issues):
    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 403
    assert issues[0][2]["has_signature_header"] is False


async def test_unparsable_body_is_named_and_still_a_422(client, issues):
    raw = b"not json at all"
    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        content=raw,
        headers={"content-type": "application/json", "x-hub-signature-256": _sig(raw)},
    )
    assert response.status_code == 422
    assert [k for k, _c, _d in issues] == ["webhook.unparsable"]


async def test_failed_verification_handshake_is_named_and_still_a_403(client, issues, monkeypatch):
    monkeypatch.setattr(
        "app.applications.apparel.modules.conversations.gateway.whatsapp.WhatsAppAdapter.verify_request",
        lambda self, params: None,
        raising=False,
    )
    response = await client.get(
        "/api/v1/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
    )
    assert response.status_code == 403
    assert [k for k, _c, _d in issues] == ["webhook.verify_failed"]


async def test_a_valid_signed_delivery_records_no_issue(client, issues):
    raw = b'{"object":"whatsapp_business_account","entry":[]}'
    await client.post(
        "/api/v1/webhooks/whatsapp",
        content=raw,
        headers={"content-type": "application/json", "x-hub-signature-256": _sig(raw)},
    )
    assert not [k for k, _c, _d in issues if k.startswith("webhook.bad_signature")]


async def test_a_recording_failure_cannot_change_the_answer(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("trail unavailable")

    monkeypatch.setattr("app.platform.platform.security_events.record_security_event", boom)
    monkeypatch.setattr("app.core.redis.get_redis_or_none", lambda: None)
    md._fallback.clear()
    response = await client.post(
        "/api/v1/webhooks/whatsapp",
        content=b"{}",
        headers={"content-type": "application/json", "x-hub-signature-256": "sha256=00"},
    )
    assert response.status_code == 403

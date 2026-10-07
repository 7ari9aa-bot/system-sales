"""Package 5.1 — checklist 6: the generic webhook INGRESS routing guards.

The dispatcher at ``/api/v1/webhooks/{channel}`` is the one unauthenticated
door into the conversations module, so its refusals are pinned on the REAL app
(the only suite that exercises the route through the full middleware stack):

* an unknown channel is a unified-envelope 404 — on GET and POST, never a
  framework ``{"detail": "Not Found"}`` and never a 405/500;
* a signed body that is not JSON — or JSON that is not an object — is a 422
  with the unified envelope (a framework-shaped validation refusal), not the
  domain 400;
* the global body cap is honored on the webhook route: an oversized delivery
  answers 413 before any signature work happens;
* a bad signature is the unified 403;
* a genuine delivery whose tenant key matches no integration is ACKed without
  detail and without writing anything, while an attributed one persists
  exactly one durable signature_valid ingress row (a byte-identical replay
  does not create a second).

The signature is the WhatsApp adapter's HMAC over the raw body, with the
adapter's settings patched to a test secret; no provider traffic. The DB-backed
cases run through the conftest session binding, so their writes roll back.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.secrets import encrypt_credentials_dict
from app.main import create_app
from app.modules.platform.models import Integration, WebhookEvent

CHANNEL_SECRET = "test-app-secret"


def _sign(raw: bytes) -> str:
    return "sha256=" + hmac.new(CHANNEL_SECRET.encode(), raw, hashlib.sha256).hexdigest()


@pytest.fixture
def _whatsapp_secret(monkeypatch):
    """Give the WhatsApp adapter a verifiable secret for the signed-body cases."""
    monkeypatch.setattr(
        "app.modules.conversations.gateway.whatsapp.get_settings",
        lambda: type("S", (), {"whatsapp_app_secret": CHANNEL_SECRET})(),
    )


async def _post_whatsapp(
    client: AsyncClient, content: bytes, *, headers: dict | None = None
) -> object:
    return await client.post(
        "/api/v1/webhooks/whatsapp",
        content=content,
        headers={"content-type": "application/json", **(headers or {})},
    )


def _signed(raw: bytes) -> dict[str, str]:
    return {"x-hub-signature-256": _sign(raw)}


async def test_unknown_channel_answers_a_unified_404_on_get_and_post() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        gotten = await client.get("/api/v1/webhooks/definitely-not-a-channel")
        posted = await client.post(
            "/api/v1/webhooks/definitely-not-a-channel",
            content=b"{}",
            headers={"content-type": "application/json"},
        )

    for response in (gotten, posted):
        assert response.status_code == 404, response.text
        error = response.json()["error"]
        assert error["code"] == "not_found"
        assert error["retryable"] is False
        assert error["request_id"] == response.headers["x-request-id"]


@pytest.mark.usefixtures("_whatsapp_secret")
async def test_signed_non_json_payload_answers_a_unified_422() -> None:
    raw = b"this is not json {{{"
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _post_whatsapp(client, raw, headers=_signed(raw))

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["retryable"] is False


@pytest.mark.usefixtures("_whatsapp_secret")
async def test_signed_non_object_json_payload_answers_a_unified_422() -> None:
    """A JSON array (or scalar) is not a webhook envelope — 422, and the
    adapter's parser is never reached with it."""
    raw = json.dumps([1, 2, 3]).encode()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _post_whatsapp(client, raw, headers=_signed(raw))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


async def test_an_oversized_body_is_refused_with_413_before_signature_work() -> None:
    """The body cap (1 MiB) is enforced by middleware — an oversized delivery
    never reaches the adapter, so it is refused with or without a signature."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _post_whatsapp(client, b"x" * (1_048_577))

    assert response.status_code == 413, response.text
    error = response.json()["error"]
    assert error["code"] == "payload_too_large"


@pytest.mark.usefixtures("_whatsapp_secret")
async def test_a_bad_signature_is_the_unified_403() -> None:
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _post_whatsapp(
            client, json.dumps({"entry": []}).encode(), headers=_signed(b"tampered")
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


@pytest.mark.usefixtures("_whatsapp_secret")
async def test_an_unattributed_delivery_is_acked_without_ingest(
    db, tenant_ctx, app_sessions_on_test_connection
) -> None:
    """A genuine signature whose tenant key matches no integration: ACK with
    no detail (no existence leak), and NO ingress row — webhook_events is
    FORCE-RLS and an unattributed delivery cannot own one."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "no-such-id"},
                            "messages": [],
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _post_whatsapp(client, raw, headers=_signed(raw))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    counted = (
        await db.execute(
            select(func.count())
            .select_from(WebhookEvent)
            .where(
                WebhookEvent.tenant_id == tenant_ctx.tenant_id,
                WebhookEvent.provider == "whatsapp",
            )
        )
    ).scalar_one()
    assert counted == 0


@pytest.mark.usefixtures("_whatsapp_secret")
async def test_an_attributed_delivery_persists_one_durable_ingress_event(
    db, tenant_ctx, app_sessions_on_test_connection
) -> None:
    """The happy guard chain: signature → JSON object → known tenant key → a
    durable, signature_valid WebhookEvent row; the byte-identical replay is
    deduped by the ingress identity instead of double-written."""
    phone_key = "201006666666"
    db.add(
        Integration(
            id=uuid.uuid4(),
            tenant_id=tenant_ctx.tenant_id,
            provider="whatsapp",
            kind="channel",
            status="active",
            config={"phone_number_id": phone_key},
            credentials=encrypt_credentials_dict({"access_token": "t"}),
        )
    )
    await db.flush()

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_key},
                            "messages": [],
                        }
                    }
                ]
            }
        ]
    }
    raw = json.dumps(payload).encode()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await _post_whatsapp(client, raw, headers=_signed(raw))
        replay = await _post_whatsapp(client, raw, headers=_signed(raw))

    assert first.status_code == 200
    assert first.json() == {"ok": True, "queued": True}
    assert replay.status_code == 200
    assert replay.json() == {"ok": True, "duplicate": True}

    rows = (
        (
            await db.execute(
                select(WebhookEvent).where(
                    WebhookEvent.tenant_id == tenant_ctx.tenant_id,
                    WebhookEvent.provider == "whatsapp",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the byte-identical replay must not create a second row"
    assert rows[0].signature_valid is True
    assert rows[0].processing_status == "pending"

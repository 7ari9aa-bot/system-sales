"""WS-GATEWAY — inbound webhook authenticity, replay, and provider-response handling.

Audit of `app/modules/conversations/gateway/**` against the three things a channel
gateway must never get wrong:

1. **Signature verification on EVERY channel.** WhatsApp = app-secret HMAC over
   the RAW body; Telegram = the secret-token header. Both must fail CLOSED when
   the secret is unconfigured, and a body tampered with after signing must fail.
2. **Replay / idempotency of inbound webhooks.** The dedupe scope must carry the
   tenant (a channel-wide scope lets an attacker pre-register another tenant's
   `channel_message_id` and get the victim's real message dropped as a dup).
3. **Provider-response error handling on the OUTBOUND path.** Every way a
   provider can fail — a rejecting status, a non-JSON body, a JSON body of the
   wrong shape, `ok:true` with no result — must surface as `ExternalProviderError`
   AND must be accounted against the circuit breaker. A failure raised OUTSIDE
   `breaker.call()` is recorded as a SUCCESS, so the breaker never opens: the
   exact bug `test_channel_send_breaker.py` documents for HTTP-status rejections.

DB-free: driven through `httpx.MockTransport` and a stubbed session, so this runs
locally without Postgres and unchanged in CI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import httpx
import pytest

from app.core.circuit_breaker import (
    PROVIDER_TELEGRAM,
    PROVIDER_WHATSAPP,
    get_breaker,
    reset_breakers,
)
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
)
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.gateway.telegram import telegram_adapter
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter

_THRESHOLD = 2


class _Settings:
    """Every field the gateway reads off settings."""

    whatsapp_app_secret = "app-secret"
    whatsapp_verify_token = "verify-token"
    telegram_webhook_secret = "tg-secret"
    circuit_breaker_failure_threshold = _THRESHOLD
    circuit_breaker_recovery_seconds = 30.0
    circuit_breaker_half_open_successes = 1


@pytest.fixture(autouse=True)
def _isolated_breakers(monkeypatch):
    """The breaker registry is process-wide — no case may leak state into the next."""
    reset_breakers()
    monkeypatch.setattr("app.core.config.get_settings", lambda: _Settings())
    yield
    reset_breakers()


def _outbound() -> OutboundMessage:
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201234567890",
        body="hello",
    )


def _direct_credentials() -> ProviderCredentials:
    return ProviderCredentials(config={"phone_number_id": "P", "access_token": "T"})


def _tg_credentials() -> ProviderCredentials:
    return ProviderCredentials(config={"bot_token": "BOT"})


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _always(response: httpx.Response):
    """A transport that answers every request with the same response."""

    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return _client(handler)


# --------------------------------------------------------------------------
# 1. Signature verification, per channel
# --------------------------------------------------------------------------


def _wa_sign(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_whatsapp_signature_is_hmac_over_the_raw_body(monkeypatch):
    """A byte of tampering after signing must invalidate the delivery."""
    monkeypatch.setattr(
        "app.modules.conversations.gateway.whatsapp.get_settings", lambda: _Settings()
    )
    raw = json.dumps({"entry": [{"changes": []}]}).encode()
    headers = {"x-hub-signature-256": _wa_sign(_Settings.whatsapp_app_secret, raw)}
    assert whatsapp_adapter.check_signature(headers, raw) is True

    # Same signature, different body — the classic replay-with-a-twist.
    tampered = raw.replace(b"changes", b"changed")
    assert whatsapp_adapter.check_signature(headers, tampered) is False
    # Signature computed over the wrong secret.
    assert (
        whatsapp_adapter.check_signature(
            {"x-hub-signature-256": _wa_sign("attacker", raw)}, raw
        )
        is False
    )
    # Missing / malformed header.
    assert whatsapp_adapter.check_signature({}, raw) is False
    assert whatsapp_adapter.check_signature({"x-hub-signature-256": "deadbeef"}, raw) is False


def test_whatsapp_signature_fails_closed_without_a_configured_secret(monkeypatch):
    """No secret configured must reject ALL traffic, not accept ALL traffic."""
    monkeypatch.setattr(
        "app.modules.conversations.gateway.whatsapp.get_settings",
        lambda: type(
            "S", (), {"whatsapp_app_secret": "", "whatsapp_verify_token": "verify-token"}
        )(),
    )
    raw = b"{}"
    forged = {"x-hub-signature-256": "sha256=anything"}
    assert whatsapp_adapter.check_signature(forged, raw) is False


def test_telegram_secret_token_is_required_and_compared_exactly(monkeypatch):
    monkeypatch.setattr(
        "app.modules.conversations.gateway.telegram.get_settings", lambda: _Settings()
    )
    header = {"x-telegram-bot-api-secret-token": _Settings.telegram_webhook_secret}
    assert telegram_adapter.check_signature(header, b"{}") is True
    assert (
        telegram_adapter.check_signature({"x-telegram-bot-api-secret-token": "wrong"}, b"{}")
        is False
    )
    assert telegram_adapter.check_signature({}, b"{}") is False
    # A prefix of the real secret must not pass.
    assert (
        telegram_adapter.check_signature(
            {"x-telegram-bot-api-secret-token": _Settings.telegram_webhook_secret[:-1]}, b"{}"
        )
        is False
    )


def test_telegram_signature_fails_closed_without_a_configured_secret(monkeypatch):
    monkeypatch.setattr(
        "app.modules.conversations.gateway.telegram.get_settings",
        lambda: type("S", (), {"telegram_webhook_secret": ""})(),
    )
    assert (
        telegram_adapter.check_signature({"x-telegram-bot-api-secret-token": "anything"}, b"{}")
        is False
    )


def test_every_generic_webhook_channel_rejects_an_unsigned_body():
    """Registry-wide guard: a channel reachable on the generic dispatcher must
    refuse a body it cannot authenticate. Catches a future adapter that ships
    with a permissive `check_signature`."""
    from app.modules.conversations.router import _WEBHOOK_CHANNELS

    assert _WEBHOOK_CHANNELS, "the dispatcher accepts no channel at all"
    for channel in sorted(_WEBHOOK_CHANNELS):
        adapter = get_adapter(channel)
        assert adapter is not None, f"{channel} is routable but not registered"
        assert adapter.check_signature({}, b"{}") is False, channel


def test_webchat_is_not_reachable_on_the_generic_webhook_dispatcher():
    """Webchat has no provider signature, so it must not be on the shared route."""
    from app.modules.conversations.router import _WEBHOOK_CHANNELS

    assert "webchat" not in _WEBHOOK_CHANNELS


# --------------------------------------------------------------------------
# 2. Replay / idempotency of inbound webhooks
# --------------------------------------------------------------------------


async def test_ingest_dedupe_scope_carries_the_tenant(monkeypatch):
    """S3: a channel-wide scope let an attacker pre-register another tenant's
    `channel_message_id`, and the victim's real message was then dropped as a dup."""
    seen: dict[str, str] = {}

    async def _capture(session, scope, key):
        seen["scope"] = scope
        seen["key"] = key
        return True  # short-circuit: nothing past the dedupe check runs

    monkeypatch.setattr(IngestService, "already_processed", _capture)
    tenant_id = uuid.uuid4()
    result = await IngestService.ingest(
        None,
        tenant_id=tenant_id,
        message=InboundMessage(
            channel="whatsapp", channel_message_id="wamid.1", customer_ref="201234567890"
        ),
        idempotency_scope="webhook:whatsapp",
    )
    assert result is None
    assert str(tenant_id) in seen["scope"]
    assert seen["scope"] != "webhook:whatsapp"
    assert seen["key"] == "wamid.1"


async def test_a_message_without_a_provider_id_is_never_deduped_away():
    """A missing `channel_message_id` must not match every other keyless message —
    and must not even reach the database."""

    class _Boom:
        async def execute(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("queried the DB for a keyless message")

    assert await IngestService.already_processed(_Boom(), "webhook:whatsapp", None) is False


# --------------------------------------------------------------------------
# 3. Provider-response error handling (outbound)
# --------------------------------------------------------------------------


async def test_whatsapp_non_json_success_body_is_a_provider_error():
    """A 200 carrying an HTML error page (proxy / CDN / captive portal) is a
    provider failure, not an unhandled `json.JSONDecodeError`."""
    response = httpx.Response(
        200, text="<html>502 Bad Gateway</html>", headers={"content-type": "text/html"}
    )
    with pytest.raises(ExternalProviderError):
        await whatsapp_adapter.send(
            _direct_credentials(), _outbound(), _client=_always(response)
        )


async def test_whatsapp_error_shaped_200_is_a_provider_error():
    """Meta answers 200 with an `error` object; that is a rejection."""
    with pytest.raises(ExternalProviderError):
        await whatsapp_adapter.send(
            _direct_credentials(),
            _outbound(),
            _client=_always(httpx.Response(200, json={"error": {"message": "rate limited"}})),
        )


async def test_telegram_non_json_success_body_is_a_provider_error():
    with pytest.raises(ExternalProviderError):
        await telegram_adapter.send(
            _tg_credentials(), _outbound(), _client=_always(httpx.Response(200, text="oops"))
        )


async def test_telegram_non_object_json_body_is_a_provider_error():
    """`response.json()` can legally return a list or a scalar."""
    with pytest.raises(ExternalProviderError):
        await telegram_adapter.send(
            _tg_credentials(), _outbound(), _client=_always(httpx.Response(200, json=[1, 2, 3]))
        )


async def test_telegram_ok_without_a_result_is_a_provider_error():
    with pytest.raises(ExternalProviderError):
        await telegram_adapter.send(
            _tg_credentials(), _outbound(), _client=_always(httpx.Response(200, json={"ok": True}))
        )


async def test_a_malformed_whatsapp_200_counts_against_the_breaker():
    """The failure must be raised INSIDE `breaker.call()`. Raised outside it, a
    provider that is broken this way is recorded as a SUCCESS forever."""
    breaker = get_breaker(PROVIDER_WHATSAPP)
    response = httpx.Response(200, text="<html>502</html>")

    for _ in range(_THRESHOLD):
        with pytest.raises(ExternalProviderError):
            await whatsapp_adapter.send(
                _direct_credentials(), _outbound(), _client=_always(response)
            )

    assert breaker.is_open, "a provider returning garbage 200s must count against the breaker"


async def test_a_malformed_telegram_200_counts_against_the_breaker():
    breaker = get_breaker(PROVIDER_TELEGRAM)

    for _ in range(_THRESHOLD):
        with pytest.raises(ExternalProviderError):
            await telegram_adapter.send(
                _tg_credentials(), _outbound(), _client=_always(httpx.Response(200, text="oops"))
            )

    assert breaker.is_open


async def test_an_error_shaped_whatsapp_200_counts_against_the_breaker():
    """Valid JSON, but the provider rejected the send — still a failure."""
    breaker = get_breaker(PROVIDER_WHATSAPP)
    response = httpx.Response(200, json={"error": {"message": "rate limited"}})

    for _ in range(_THRESHOLD):
        with pytest.raises(ExternalProviderError):
            await whatsapp_adapter.send(
                _direct_credentials(), _outbound(), _client=_always(response)
            )

    assert breaker.is_open


async def test_a_successful_send_still_returns_the_provider_id():
    """The failure handling must not swallow the happy path."""
    wa = _always(httpx.Response(200, json={"messages": [{"id": "wamid.out1"}]}))
    assert (
        await whatsapp_adapter.send(_direct_credentials(), _outbound(), _client=wa)
        == "wamid.out1"
    )

    tg = _always(httpx.Response(200, json={"ok": True, "result": {"message_id": 77}}))
    assert await telegram_adapter.send(_tg_credentials(), _outbound(), _client=tg) == "77"

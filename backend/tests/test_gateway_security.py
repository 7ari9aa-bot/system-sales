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
from app.modules.conversations.gateway.email import EmailAdapter, email_adapter
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.instagram import instagram_adapter
from app.modules.conversations.gateway.messenger import messenger_adapter
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.gateway.telegram import telegram_adapter
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter

_THRESHOLD = 2


class _Settings:
    """Every field the gateway reads off settings."""

    whatsapp_app_secret = "app-secret"
    whatsapp_verify_token = "verify-token"
    instagram_app_secret = "ig-secret"
    messenger_app_secret = "msgr-secret"
    telegram_webhook_secret = "tg-secret"
    email_webhook_secret = ""
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
        whatsapp_adapter.check_signature({"x-hub-signature-256": _wa_sign("attacker", raw)}, raw)
        is False
    )


@pytest.mark.parametrize("adapter_name", ["instagram", "messenger"])
def test_meta_channel_signature_is_hmac_over_the_bare_digest(monkeypatch, adapter_name):
    """Instagram and Messenger validate the same way WhatsApp does: the hex
    digest is compared WITHOUT the `sha256=` prefix. These two channels
    shipped comparing the PREFIXED header against the bare digest — every
    genuine Meta delivery failed closed (403) and the channels were dead
    while the WhatsApp-only tests stayed green."""
    import importlib

    module = importlib.import_module(f"app.modules.conversations.gateway.{adapter_name}")
    adapter = getattr(module, f"{adapter_name}_adapter")
    monkeypatch.setattr(
        f"app.modules.conversations.gateway.{adapter_name}.get_settings",
        lambda: _Settings(),
    )
    raw = json.dumps({"entry": [{"id": "acc-1", "changes": []}]}).encode()
    secret = getattr(_Settings, f"{adapter_name}_app_secret")
    headers = {"x-hub-signature-256": _wa_sign(secret, raw)}
    assert adapter.check_signature(headers, raw) is True

    tampered = raw.replace(b"changes", b"changed")
    assert adapter.check_signature(headers, tampered) is False
    assert adapter.check_signature({"x-hub-signature-256": _wa_sign("attacker", raw)}, raw) is False
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


@pytest.mark.parametrize("adapter_name", ["messenger", "instagram"])
def test_meta_channel_handshake_fails_closed_without_a_verify_token(monkeypatch, adapter_name):
    """The GET handshake had the same hole the WhatsApp adapter closed: with
    the verify token unset (empty default), an EMPTY `hub.verify_token`
    compared equal to the configured value and the endpoint answered with the
    caller's own challenge. Not configured = cannot verify = reject."""
    import importlib

    module = importlib.import_module(f"app.modules.conversations.gateway.{adapter_name}")
    adapter = getattr(module, f"{adapter_name}_adapter")
    monkeypatch.setattr(
        f"app.modules.conversations.gateway.{adapter_name}.get_settings",
        lambda: type("S", (), {f"{adapter_name}_verify_token": ""})(),
    )
    for params in (
        {"hub.mode": "subscribe", "hub.challenge": "CH1"},
        {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "CH1"},
        {"hub.mode": "subscribe", "hub.verify_token": "anything", "hub.challenge": "CH1"},
    ):
        assert adapter.verify_request(params) is None, params


@pytest.mark.parametrize("adapter_name", ["messenger", "instagram"])
def test_meta_channel_handshake_completes_only_with_the_configured_token(monkeypatch, adapter_name):
    """The fail-closed guard must not take the happy path down with it."""
    import importlib

    module = importlib.import_module(f"app.modules.conversations.gateway.{adapter_name}")
    adapter = getattr(module, f"{adapter_name}_adapter")
    monkeypatch.setattr(
        f"app.modules.conversations.gateway.{adapter_name}.get_settings",
        lambda: type("S", (), {f"{adapter_name}_verify_token": "s3cret"})(),
    )
    assert (
        adapter.verify_request(
            {"hub.mode": "subscribe", "hub.verify_token": "s3cret", "hub.challenge": "CH1"}
        )
        == "CH1"
    )
    # Wrong or partial token: rejected.
    assert (
        adapter.verify_request(
            {"hub.mode": "subscribe", "hub.verify_token": "s3cret-toke", "hub.challenge": "CH1"}
        )
        is None
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
        await whatsapp_adapter.send(_direct_credentials(), _outbound(), _client=_always(response))


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
        await whatsapp_adapter.send(_direct_credentials(), _outbound(), _client=wa) == "wamid.out1"
    )

    tg = _always(httpx.Response(200, json={"ok": True, "result": {"message_id": 77}}))
    assert await telegram_adapter.send(_tg_credentials(), _outbound(), _client=tg) == "77"


# --------------------------------------------------------------------------
# 4. Package 5.1 — cross-provider signature isolation + hostile-header safety
# --------------------------------------------------------------------------

#: One DISTINCT secret per provider. The cross-provider matrix below proves a
#: delivery signed with provider B's credential can never pass provider A's
#: check — the package's fail-first scenario (checklist 1).
_ALL_SECRETS: dict[str, str] = {
    "whatsapp_app_secret": "sec-whatsapp",
    "messenger_app_secret": "sec-messenger",
    "instagram_app_secret": "sec-instagram",
    "telegram_webhook_secret": "sec-telegram",
    "email_webhook_secret": "sec-email",
}


class _AllSecrets:
    """Settings carrying EVERY channel secret at once (all distinct)."""

    whatsapp_app_secret = _ALL_SECRETS["whatsapp_app_secret"]
    whatsapp_verify_token = "verify-whatsapp"
    messenger_app_secret = _ALL_SECRETS["messenger_app_secret"]
    messenger_verify_token = "verify-messenger"
    instagram_app_secret = _ALL_SECRETS["instagram_app_secret"]
    instagram_verify_token = "verify-instagram"
    telegram_webhook_secret = _ALL_SECRETS["telegram_webhook_secret"]
    email_webhook_secret = _ALL_SECRETS["email_webhook_secret"]


def _patch_all_secret_settings(monkeypatch) -> None:
    """Point every adapter's settings reader at _AllSecrets."""
    for module in (
        "app.modules.conversations.gateway.whatsapp",
        "app.modules.conversations.gateway.messenger",
        "app.modules.conversations.gateway.instagram",
        "app.modules.conversations.gateway.telegram",
        "app.modules.conversations.gateway.email",
    ):
        monkeypatch.setattr(f"{module}.get_settings", lambda: _AllSecrets())


def _signed_headers(scheme: str, secret: str, raw: bytes) -> dict[str, str]:
    """The auth header a delivery signed with ``secret`` would carry."""
    if scheme in ("whatsapp", "messenger", "instagram"):
        return {
            "x-hub-signature-256": "sha256="
            + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        }
    if scheme == "telegram":
        # Telegram's scheme IS the shared secret echoed in a header.
        return {"x-telegram-bot-api-secret-token": secret}
    if scheme == "email-sendgrid":
        return {"authorization": f"Bearer {secret}"}
    if scheme == "email-mailgun":
        return {"x-mailgun-signature": hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}
    raise KeyError(scheme)


#: (scheme, adapter) pairs that must each bind to exactly ONE provider secret.
_SIGNED_SURFACES = [
    ("whatsapp", whatsapp_adapter),
    ("messenger", messenger_adapter),
    ("instagram", instagram_adapter),
    ("telegram", telegram_adapter),
    ("email-sendgrid", email_adapter),
    ("email-mailgun", EmailAdapter(provider="mailgun")),
]

_OWN_SECRET_ATTR = {
    "whatsapp": "whatsapp_app_secret",
    "messenger": "messenger_app_secret",
    "instagram": "instagram_app_secret",
    "telegram": "telegram_webhook_secret",
    "email-sendgrid": "email_webhook_secret",
    "email-mailgun": "email_webhook_secret",
}


@pytest.mark.parametrize(("scheme", "adapter"), _SIGNED_SURFACES)
def test_a_body_signed_with_another_providers_secret_is_rejected(monkeypatch, scheme, adapter):
    """Checklist 1, per channel: a payload authenticated with provider B's
    secret must NEVER pass channel A. Every pair of distinct secrets is
    exercised, plus the positive control (its own secret passes)."""
    _patch_all_secret_settings(monkeypatch)
    raw = json.dumps({"entry": []}).encode()
    own = _ALL_SECRETS[_OWN_SECRET_ATTR[scheme]]

    assert adapter.check_signature(_signed_headers(scheme, own, raw), raw) is True
    for attr, foreign_secret in _ALL_SECRETS.items():
        if foreign_secret == own:
            continue  # the positive control above
        foreign_headers = _signed_headers(scheme, foreign_secret, raw)
        assert adapter.check_signature(foreign_headers, raw) is False, (
            f"{scheme} accepted a signature made with {attr}"
        )


@pytest.mark.parametrize(("scheme", "adapter"), _SIGNED_SURFACES)
def test_a_hostile_non_ascii_signature_header_is_rejected_not_a_500(monkeypatch, scheme, adapter):
    """compare_digest raises TypeError on non-ASCII str — a hostile header
    must come back as a plain False (403 at the edge), never a 500. The
    comparisons therefore run on encoded bytes."""
    _patch_all_secret_settings(monkeypatch)
    raw = b"{}"
    hostile = "ÿþ\u20ac"  # non-ASCII — would raise on a str comparison
    headers = dict(_signed_headers(scheme, "x", raw))
    key = next(iter(headers))
    headers[key] = hostile
    assert adapter.check_signature(headers, raw) is False


def test_email_signature_fails_closed_without_a_configured_secret(monkeypatch):
    """No EMAIL_WEBHOOK_SECRET must reject ALL traffic — both ESP schemes."""
    monkeypatch.setattr(
        "app.modules.conversations.gateway.email.get_settings",
        lambda: type("S", (), {"email_webhook_secret": ""})(),
    )
    raw = b'{"from": "x@y.z"}'
    for adapter in (email_adapter, EmailAdapter(provider="mailgun")):
        assert adapter.check_signature({}, raw) is False
        assert adapter.check_signature({"authorization": "Bearer guess"}, raw) is False
        assert adapter.check_signature({"x-mailgun-signature": "a" * 64}, raw) is False


def test_email_signature_accepts_only_the_configured_credential(monkeypatch):
    """The happy path: the exact configured bearer / HMAC, and nothing else."""
    secret = "sec-email"
    monkeypatch.setattr(
        "app.modules.conversations.gateway.email.get_settings",
        lambda: type("S", (), {"email_webhook_secret": secret})(),
    )
    raw = b'{"from": "x@y.z"}'

    sendgrid = email_adapter
    assert sendgrid.check_signature({"authorization": f"Bearer {secret}"}, raw) is True
    # Same header WITHOUT the last character: rejected.
    assert sendgrid.check_signature({"authorization": f"Bearer {secret[:-1]}"}, raw) is False
    # The Bearer credential is NOT a body HMAC: swapping schemes must not pass.
    body_hmac = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert sendgrid.check_signature({"authorization": f"Bearer {body_hmac}"}, raw) is False

    mailgun = EmailAdapter(provider="mailgun")
    good = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert mailgun.check_signature({"x-mailgun-signature": good}, raw) is True
    tampered = raw.replace(b"x@y.z", b"evil@y.z")
    assert mailgun.check_signature({"x-mailgun-signature": good}, tampered) is False


def test_email_parse_inbound_normalizes_an_esp_delivery():
    """The email adapter normalizes like every other channel: sync, list, one
    message per delivery, empty list for an envelope without a sender."""
    messages = email_adapter.parse_inbound(
        {
            "from": "Alice <alice@example.test>",
            "to": "support@example.test",
            "text": "مرحبا",
            "messageId": "<m-1@example.test>",
        }
    )
    assert len(messages) == 1
    message = messages[0]
    assert message.channel == "email"
    assert message.customer_ref == "Alice <alice@example.test>"
    assert message.body == "مرحبا"
    assert message.channel_message_id == "<m-1@example.test>"
    assert email_adapter.parse_inbound({}) == []


async def test_email_send_returns_a_provider_message_id():
    """Outbound conformance: 202 with an empty SendGrid body still yields the
    X-Message-Id; a 2xx WITHOUT one is a provider failure, not a success."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, headers={"X-Message-Id": "sg-123"})

    provider_id = await email_adapter.send(
        ProviderCredentials(config={"api_key": "ESP-KEY"}),
        _outbound(),
        _client=_client(handler),
    )
    assert provider_id == "sg-123"

    def bare(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    with pytest.raises(ExternalProviderError):
        await email_adapter.send(
            ProviderCredentials(config={"api_key": "ESP-KEY"}),
            _outbound(),
            _client=_client(bare),
        )


@pytest.mark.parametrize(("scheme", "adapter"), _SIGNED_SURFACES)
def test_every_signed_channel_fails_closed_without_its_secret(monkeypatch, scheme, adapter):
    """Checklist 1, per channel, unconditional: an EMPTY secret rejects ALL
    traffic in ANY environment — there is no permissive mode to reach."""
    empty = type("S", (), {attr: "" for attr in _ALL_SECRETS})()
    for module, channel in (
        ("app.modules.conversations.gateway.whatsapp", "whatsapp"),
        ("app.modules.conversations.gateway.messenger", "messenger"),
        ("app.modules.conversations.gateway.instagram", "instagram"),
        ("app.modules.conversations.gateway.telegram", "telegram"),
        ("app.modules.conversations.gateway.email", "email-sendgrid"),
        ("app.modules.conversations.gateway.email", "email-mailgun"),
    ):
        if channel == scheme:
            monkeypatch.setattr(f"{module}.get_settings", lambda: empty)
    raw = b'{"entry": []}'
    assert adapter.check_signature({}, raw) is False, scheme
    assert adapter.check_signature(_signed_headers(scheme, "anything", raw), raw) is False, scheme

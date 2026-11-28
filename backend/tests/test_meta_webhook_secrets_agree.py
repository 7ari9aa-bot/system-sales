"""Facebook and Messenger are one Meta protocol, so one server must treat them the same way.

Facebook's adapter used to accept `META_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN` as fallbacks that
Messenger's did not, and the "server setup required" badge used Messenger's rule for both. One
deployment could then pass Meta's handshake on one webhook and fail it on the other, and show the
owner a setup warning for a Facebook webhook that worked.

The rule, for both:
* the signature is made with the Meta APP secret: `messenger_app_secret`, else `meta_app_secret`
  (the same app signs every one of its webhooks);
* the verify token is `messenger_verify_token` ONLY. `whatsapp_verify_token` is another channel's
  secret and must not open a Page's webhook subscription.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.conversations.gateway.facebook import facebook_adapter
from app.applications.apparel.modules.conversations.gateway.messenger import messenger_adapter
from app.modules.platform.models import Integration

BODY = b'{"object":"page","entry":[]}'
ADAPTERS = [
    pytest.param(facebook_adapter, id="facebook"),
    pytest.param(messenger_adapter, id="messenger"),
]


def _settings(**fields):
    base = {
        "messenger_app_secret": "",
        "meta_app_secret": "",
        "messenger_verify_token": "",
        "whatsapp_verify_token": "",
    }
    return SimpleNamespace(**{**base, **fields})


def _use(monkeypatch, **fields):
    # Facebook inherits Messenger's rule, so there is exactly one place to configure.
    settings = _settings(**fields)
    monkeypatch.setattr(
        "app.applications.apparel.modules.conversations.gateway.messenger.get_settings", lambda: settings
    )


def test_facebook_has_no_webhook_rule_of_its_own():
    """The drift came from re-implementing the handshake and signature in the subclass."""
    assert "verify_request" not in vars(type(facebook_adapter))
    assert "check_signature" not in vars(type(facebook_adapter))


def _sign(secret: str) -> dict[str, str]:
    digest = hmac.new(secret.encode(), BODY, hashlib.sha256).hexdigest()
    return {"x-hub-signature-256": f"sha256={digest}"}


def _handshake(token: str) -> dict[str, str]:
    return {"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "42"}


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_the_apps_own_secret_signs_both_when_no_messenger_secret_is_set(monkeypatch, adapter):
    _use(monkeypatch, meta_app_secret="meta-secret")
    assert adapter.check_signature(_sign("meta-secret"), BODY) is True


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_the_messenger_secret_wins_when_both_are_set(monkeypatch, adapter):
    _use(monkeypatch, messenger_app_secret="msgr", meta_app_secret="meta")
    assert adapter.check_signature(_sign("msgr"), BODY) is True
    assert adapter.check_signature(_sign("meta"), BODY) is False


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_a_wrong_or_missing_signature_is_refused(monkeypatch, adapter):
    _use(monkeypatch, messenger_app_secret="msgr")
    assert adapter.check_signature(_sign("someone-else"), BODY) is False
    assert adapter.check_signature({}, BODY) is False


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_no_secret_anywhere_fails_closed(monkeypatch, adapter):
    _use(monkeypatch)
    assert adapter.check_signature(_sign(""), BODY) is False


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_the_messenger_verify_token_opens_the_handshake_on_both(monkeypatch, adapter):
    _use(monkeypatch, messenger_verify_token="vt")
    assert adapter.verify_request(_handshake("vt")) == "42"
    assert adapter.verify_request(_handshake("other")) is None


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_the_whatsapp_verify_token_never_opens_a_page_webhook(monkeypatch, adapter):
    """Another channel's secret is not a credential for this one."""
    _use(monkeypatch, whatsapp_verify_token="wa-token")
    assert adapter.verify_request(_handshake("wa-token")) is None


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_no_verify_token_configured_fails_closed(monkeypatch, adapter):
    _use(monkeypatch)
    assert adapter.verify_request(_handshake("")) is None


# ---- the badge must tell the truth about the webhook it describes ----------------------------


def _badge(monkeypatch, provider: str, **fields) -> str:
    from app.applications.apparel.modules.customers.routers import integrations as routes

    settings = _settings(
        whatsapp_app_secret="",
        whatsapp_verify_token=fields.pop("whatsapp_verify_token", ""),
        instagram_app_secret="",
        instagram_verify_token="",
        telegram_webhook_secret="",
        **fields,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr(routes, "_telegram_webhook_base_url", lambda: "https://api.example")
    integration = Integration(
        tenant_id=uuid.uuid4(), provider=provider, kind="channel", config={}, status="active"
    )
    return routes._webhook_status(integration)


@pytest.mark.parametrize("provider", ["facebook", "messenger"])
def test_the_badge_is_ready_when_the_webhook_will_actually_work(monkeypatch, provider):
    status = _badge(monkeypatch, provider, meta_app_secret="meta", messenger_verify_token="vt")
    assert status != "server_setup_required"


@pytest.mark.parametrize("provider", ["facebook", "messenger"])
def test_the_badge_asks_for_setup_when_the_webhook_would_refuse_meta(monkeypatch, provider):
    assert _badge(monkeypatch, provider, meta_app_secret="meta") == "server_setup_required"
    assert _badge(monkeypatch, provider, messenger_verify_token="vt") == "server_setup_required"


@pytest.mark.parametrize("provider", ["facebook", "messenger"])
def test_a_whatsapp_token_does_not_make_the_badge_green(monkeypatch, provider):
    status = _badge(monkeypatch, provider, meta_app_secret="meta", whatsapp_verify_token="wa-token")
    assert status == "server_setup_required"

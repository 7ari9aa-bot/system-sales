"""WhatsApp webhook handshake (GET /webhooks/whatsapp) must fail CLOSED.

`check_signature` already rejects everything when `WHATSAPP_APP_SECRET` is unset
("cannot verify; reject"), and Telegram does the same. The GET handshake did not:
with `WHATSAPP_VERIFY_TOKEN` unset (the default is the empty string) a request
carrying an EMPTY `hub.verify_token` compared equal to the configured value and
was answered with the caller's own `hub.challenge`.

The impact is small — it only echoes a value the caller supplied — but it is the
one webhook surface that could not tell "not configured" from "configured", on an
endpoint that is public by design. It should behave like its two siblings.
"""

from __future__ import annotations

import pytest

from app.modules.conversations.gateway.whatsapp import whatsapp_adapter


def _configure(monkeypatch: pytest.MonkeyPatch, token: str) -> None:
    monkeypatch.setattr(
        "app.modules.conversations.gateway.whatsapp.get_settings",
        lambda: type("S", (), {"whatsapp_app_secret": "", "whatsapp_verify_token": token})(),
    )


def _handshake(token: str | None, mode: str = "subscribe") -> dict[str, str]:
    params = {"hub.mode": mode, "hub.challenge": "CH123"}
    if token is not None:
        params["hub.verify_token"] = token
    return params


def test_unset_token_rejects_an_empty_verify_token(monkeypatch):
    _configure(monkeypatch, "")
    assert whatsapp_adapter.verify_request(_handshake("")) is None


def test_unset_token_rejects_a_missing_verify_token(monkeypatch):
    _configure(monkeypatch, "")
    assert whatsapp_adapter.verify_request(_handshake(None)) is None


def test_unset_token_rejects_any_token(monkeypatch):
    _configure(monkeypatch, "")
    assert whatsapp_adapter.verify_request(_handshake("anything")) is None


def test_configured_token_still_completes_the_handshake(monkeypatch):
    _configure(monkeypatch, "s3cret-token")
    assert whatsapp_adapter.verify_request(_handshake("s3cret-token")) == "CH123"


def test_wrong_or_partial_token_is_rejected(monkeypatch):
    _configure(monkeypatch, "s3cret-token")
    assert whatsapp_adapter.verify_request(_handshake("s3cret-toke")) is None
    assert whatsapp_adapter.verify_request(_handshake("S3CRET-TOKEN")) is None
    assert whatsapp_adapter.verify_request(_handshake("")) is None
    assert whatsapp_adapter.verify_request(_handshake(None)) is None


def test_only_the_subscribe_mode_is_accepted(monkeypatch):
    _configure(monkeypatch, "s3cret-token")
    assert whatsapp_adapter.verify_request(_handshake("s3cret-token", mode="unsubscribe")) is None


def test_non_ascii_input_is_rejected_without_raising(monkeypatch):
    """`hmac.compare_digest` raises TypeError on non-ASCII *str* operands, which
    would turn a hostile query string into a 500. It must compare bytes."""
    _configure(monkeypatch, "s3cret-token")
    assert whatsapp_adapter.verify_request(_handshake("توكن-سري")) is None


def test_non_ascii_configured_token_is_accepted_when_it_matches(monkeypatch):
    _configure(monkeypatch, "توكن-سري")
    assert whatsapp_adapter.verify_request(_handshake("توكن-سري")) == "CH123"

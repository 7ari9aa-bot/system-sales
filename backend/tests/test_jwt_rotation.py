"""JWT signing: pinned algorithm both sides + kid-aware secret rotation.

encode used to honor settings.jwt_algorithm while decode hardcoded HS256 —
flip the setting and the deployment minted tokens it then refused to verify
(a full auth outage from one config edit). Both sides are now pinned to
security.JWT_ALGORITHM, and config refuses anything else outside local/test.

The kid header makes rotation zero-logout: tokens carry the fingerprint of
the secret that signed them, so decode_token picks current or previous
(JWT_SECRET_PREVIOUS) — and kid-less legacy tokens (pre-kid stock) are tried
against current then previous, so a roll invalidates nothing early.
"""

from __future__ import annotations

import uuid

import jwt as pyjwt
import pytest

from app.core import security
from app.core.security import (
    JWT_ALGORITHM,
    _create_token,
    _kid,
    create_access_token,
    decode_token,
)


class _CurrentOnly:
    """A deployment with one signing secret and no rotation in progress."""

    access_token_ttl_seconds = 900
    jwt_secret = "current-secret-" + "c" * 20
    jwt_secret_previous = ""


class _Rotating:
    """The next deployment: a NEW current secret, the old one as previous."""

    access_token_ttl_seconds = 900
    jwt_secret = "next-secret-" + "n" * 24
    jwt_secret_previous = _CurrentOnly.jwt_secret


@pytest.fixture(autouse=True)
def _current_settings(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: _CurrentOnly())
    yield


def test_both_sides_are_pinned_to_hs256() -> None:
    assert JWT_ALGORITHM == "HS256"
    token = create_access_token(str(uuid.uuid4()))
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "HS256"


def test_tokens_carry_the_signing_secrets_kid() -> None:
    token = create_access_token(str(uuid.uuid4()))
    assert pyjwt.get_unverified_header(token)["kid"] == _kid(_CurrentOnly.jwt_secret)


def test_the_kid_is_a_short_deterministic_fingerprint() -> None:
    assert _kid("s1") == _kid("s1")
    assert _kid("s1") != _kid("s2")
    assert len(_kid("s1")) == 8


def test_a_token_minted_before_the_roll_still_verifies_after_it(monkeypatch) -> None:
    """Zero-logout rotation: old secret signs, new deployment (old as
    previous) verifies via the token's kid."""
    old_token = _create_token("user-1", 900, "access", {})

    monkeypatch.setattr(security, "get_settings", lambda: _Rotating())
    payload = decode_token(old_token)
    assert payload["sub"] == "user-1"


def test_a_kid_less_legacy_token_verifies_via_the_previous_secret(monkeypatch) -> None:
    """Tokens minted before the kid header existed carry no kid — tried
    against current then previous, so the rotation stays backward compatible."""
    from datetime import UTC, datetime

    now = int(datetime.now(UTC).timestamp())
    legacy = pyjwt.encode(
        {
            "sub": "user-2",
            "type": "access",
            "iss": "sales-os",
            "aud": "sales-os",
            "iat": now,
            "exp": now + 900,
        },
        _CurrentOnly.jwt_secret,
        algorithm="HS256",
    )  # no kid header — pre-rotation stock

    monkeypatch.setattr(security, "get_settings", lambda: _Rotating())
    payload = decode_token(legacy)
    assert payload["sub"] == "user-2"


def test_an_unknown_kid_is_refused_without_secret_guessing(monkeypatch) -> None:
    forged = pyjwt.encode(
        {"sub": "user-3", "type": "access", "iss": "sales-os", "aud": "sales-os"},
        "attacker-secret",
        algorithm="HS256",
        headers={"kid": "not-ours"},
    )
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(forged)


def test_a_wrong_signature_is_still_rejected(monkeypatch) -> None:
    forged = pyjwt.encode(
        {"sub": "user-4", "type": "access", "iss": "sales-os", "aud": "sales-os"},
        "attacker-secret",
        algorithm="HS256",
        headers={"kid": _kid(_CurrentOnly.jwt_secret)},
    )
    with pytest.raises(pyjwt.InvalidSignatureError):
        decode_token(forged)


def test_an_expired_but_correctly_signed_token_reports_expiry(monkeypatch) -> None:
    """A signature-valid expired token must raise ExpiredSignatureError, not
    be retried against the other rotation secret and mis-reported."""
    expired = _create_token("user-5", -10, "access", {})
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(expired)


def test_no_rotation_configured_still_verifies_plainly() -> None:
    token = create_access_token("user-6", {"tenant_id": "t"})
    assert decode_token(token)["sub"] == "user-6"

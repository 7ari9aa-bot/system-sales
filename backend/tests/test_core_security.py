"""app/core/security.py invariants: hashing params + JWT claim discipline.

Complements test_jwt_rotation.py (kid/rotation mechanics) and the hashing part
of test_password_reset.py (long inputs): this file pins the primitives —
bcrypt cost, the legacy-hash migration path, malformed-hash containment, the
EXACT token-type claim names every consumer keys on, and that decode_token
enforces iss/aud and REQUIRES exp/sub to be present.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import jwt as pyjwt
import pytest

from app.core import security
from app.core.security import (
    _BCRYPT_SHA256_PREFIX,
    JWT_ALGORITHM,
    _kid,
    create_access_token,
    create_oauth_state_token,
    create_refresh_token,
    create_stream_token,
    create_visitor_token,
    decode_token,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)

_SETTINGS = SimpleNamespace(
    jwt_secret="core-security-test-secret-" + "s" * 16,
    jwt_secret_previous="",
    access_token_ttl_seconds=900,
    refresh_token_ttl_seconds=900,
    webchat_session_ttl_seconds=900,
)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(security, "get_settings", lambda: _SETTINGS)


# ------------------------------------------------------------- hashing -----


def test_bcrypt_cost_factor_is_pinned_at_12() -> None:
    # Fail-first: lowering bcrypt.gensalt() rounds below 12 changes the "$2b$12$"
    # prefix and this assertion fails — the cost is the offline-brute-force budget.
    stored = hash_password("correct horse battery staple")
    assert stored.startswith(_BCRYPT_SHA256_PREFIX)
    assert stored[len(_BCRYPT_SHA256_PREFIX) :].startswith("$2b$12$")


def test_equal_passwords_hash_differently_salts_are_random() -> None:
    # Fail-first: a fixed or empty salt would make both hashes identical.
    assert hash_password("same-input") != hash_password("same-input")


def test_legacy_raw_bcrypt_hashes_verify_with_truncation_semantics() -> None:
    # Fail-first: removing the legacy branch (always applying _bcrypt_material)
    # makes verify_password return False for pre-migration rows — the True
    # assertion below is exactly what would break.
    password = "L" * 80  # beyond bcrypt's 72-byte limit
    legacy = bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()
    assert verify_password(password, legacy)
    # A different first-72-bytes password must not verify against the row.
    assert not verify_password("M" + "L" * 79, legacy)


def test_a_malformed_hash_is_a_failed_verify_not_a_crash() -> None:
    # Fail-first: without the try/except in verify_password, ValueError from
    # bcrypt.checkpw propagates — a corrupt row would 500 every login attempt.
    assert verify_password("whatever", "not-a-bcrypt-hash") is False
    assert verify_password("whatever", "") is False


async def test_async_wrappers_match_the_sync_primitives() -> None:
    # Fail-first: if a wrapper stopped calling the sync primitive (or dropped
    # to_thread and returned before the work finished), the verify below would
    # fail. Salted hashes never repeat, so equality is asserted via verify.
    stored = hash_password("async-round-trip")
    assert await verify_password_async("async-round-trip", stored) is True
    assert await verify_password_async("wrong", stored) is False
    fresh = await hash_password_async("async-round-trip")
    assert verify_password("async-round-trip", fresh) is True


# ------------------------------------------------- JWT claim discipline ----


def test_every_token_kind_stamps_the_exact_type_claim_name() -> None:
    # Fail-first: the "type" VALUES are a contract with every consumer —
    # identity/deps.py:159 requires "access", realtime/router.py:93 "stream",
    # security.decode_visitor_token "webchat_visitor", meta_oauth.py:395
    # "oauth_state". Renaming any value silently locks out that flow.
    user = str(uuid4())
    assert decode_token(create_access_token(user))["type"] == "access"
    assert decode_token(create_refresh_token(user))["type"] == "refresh"
    assert decode_token(create_oauth_state_token(user))["type"] == "oauth_state"
    stream = decode_token(create_stream_token(user, str(uuid4())))
    assert stream["type"] == "stream"
    visitor = decode_token(create_visitor_token("session-key", str(uuid4()), widget="w"))
    assert visitor["type"] == "webchat_visitor"


def _signed(payload_extra: dict, *, kid: bool = True) -> str:
    """A correctly-signed token with hand-picked claims (bypasses _create_token)."""
    now = int(datetime.now(UTC).timestamp())
    payload = {"sub": "user-1", "type": "access", "exp": now + 900, **payload_extra}
    headers = {"kid": _kid(_SETTINGS.jwt_secret)} if kid else None
    return pyjwt.encode(payload, _SETTINGS.jwt_secret, algorithm=JWT_ALGORITHM, headers=headers)


def test_a_foreign_issuer_is_refused() -> None:
    # Fail-first: removing issuer= from jwt.decode makes this token verify —
    # a token minted for another system would be accepted here.
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(_signed({"iss": "other-system", "aud": "sales-os"}))


def test_a_foreign_audience_is_refused() -> None:
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(_signed({"iss": "sales-os", "aud": "other-audience"}))


def test_a_signature_valid_token_without_exp_is_refused() -> None:
    # Fail-first: decode_token's options={"require": ["exp", ...]} is the ONLY
    # thing standing between this test and a never-expiring accepted token —
    # PyJWT validates exp only when it is present.
    token = pyjwt.encode(
        {"sub": "user-1", "type": "access", "iss": "sales-os", "aud": "sales-os"},
        _SETTINGS.jwt_secret,
        algorithm=JWT_ALGORITHM,
        headers={"kid": _kid(_SETTINGS.jwt_secret)},
    )
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(token)


def test_a_signature_valid_token_without_sub_is_refused() -> None:
    # Fail-first: sub is the identity the request is attributed to; accepting
    # a subject-less token would break every downstream ownership check.
    now = int(datetime.now(UTC).timestamp())
    token = pyjwt.encode(
        {"type": "access", "iss": "sales-os", "aud": "sales-os", "exp": now + 900},
        _SETTINGS.jwt_secret,
        algorithm=JWT_ALGORITHM,
        headers={"kid": _kid(_SETTINGS.jwt_secret)},
    )
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(token)

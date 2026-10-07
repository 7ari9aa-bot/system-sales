"""JWT + password primitives (Stage 2 builds the full auth flows on these)."""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

_BCRYPT_SHA256_PREFIX = "bcrypt-sha256-v1$"

# BOTH token sides are pinned to this algorithm (config.py refuses any other
# JWT_ALGORITHM outside local/test): encode used to honor settings.jwt_algorithm
# while decode hardcoded HS256, so flipping the setting minted tokens the very
# same deployment refused to verify — a full auth outage from one config edit.
JWT_ALGORITHM = "HS256"


def _kid(secret: str) -> str:
    """Stable key id: the SHA-256 fingerprint prefix of a signing secret.

    Computed, never configured — the kid rides in the token header so a
    verifier can select the right secret during a rotation without a registry.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]


def _bcrypt_material(password: str) -> bytes:
    """Pre-hash UTF-8 passwords so bcrypt's 72-byte input limit is explicit.

    The bcrypt salt and cost still protect every stored hash. Domain separation
    prevents this digest from being reused as an unrelated application hash.
    """
    digest = hashlib.sha256(
        b"sales-os:password:v1\0" + password.encode("utf-8")
    ).hexdigest()
    return digest.encode("ascii")


def hash_password(password: str) -> str:
    encoded_hash = bcrypt.hashpw(_bcrypt_material(password), bcrypt.gensalt()).decode()
    return f"{_BCRYPT_SHA256_PREFIX}{encoded_hash}"


async def hash_password_async(password: str) -> str:
    """hash_password off the event loop: one bcrypt call costs ~100-300ms,
    and four concurrent logins used to stall every request behind them."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    """The verify half of hash_password_async — see there."""
    return await asyncio.to_thread(verify_password, password, password_hash)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith(_BCRYPT_SHA256_PREFIX):
            material = _bcrypt_material(password)
            stored_hash = password_hash[len(_BCRYPT_SHA256_PREFIX) :]
        else:
            # Legacy hashes used raw bcrypt input. Preserve the historical
            # 72-byte truncation semantics for those rows during migration.
            material = password.encode("utf-8")[:72]
            stored_hash = password_hash
        return bcrypt.checkpw(material, stored_hash.encode())
    except (ValueError, TypeError):
        return False


def _create_token(subject: str, ttl_seconds: int, token_type: str, claims: dict[str, Any]) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    # Security-critical claims are set AFTER caller claims so they can never
    # be overridden (H4): sub/type/jti/iat/exp win, always.
    payload = {
        **(claims or {}),
        "sub": subject,
        "type": token_type,
        # jti guarantees uniqueness even for two tokens issued in the same
        # second — deterministic payloads would collide on token_hash.
        "jti": str(uuid.uuid4()),
        "iss": "sales-os",
        "aud": "sales-os",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    # The kid names the signing secret's fingerprint so a rotation (see
    # decode_token) can verify old tokens with the previous secret without a
    # logout wave.
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
        headers={"kid": _kid(settings.jwt_secret)},
    )


def create_access_token(user_id: str, claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    return _create_token(
        user_id, settings.access_token_ttl_seconds, "access", claims or {}
    )


def create_oauth_state_token(
    user_id: str, claims: dict[str, Any] | None = None, *, ttl_seconds: int = 600
) -> str:
    """A short-lived signed state for two-phase flows (OAuth callbacks).

    type='oauth_state' — decode_token callers MUST reject it as an access
    token; the short TTL bounds the window between authorize and callback.
    """
    return _create_token(user_id, ttl_seconds, "oauth_state", claims or {})


def create_refresh_token(user_id: str, claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    return _create_token(
        user_id, settings.refresh_token_ttl_seconds, "refresh", claims or {}
    )


STREAM_TOKEN_TTL_SECONDS = 300


def create_stream_token(
    user_id: str,
    tenant_id: str,
    ttl_seconds: int = STREAM_TOKEN_TTL_SECONDS,
    *,
    auth_version: int = 0,
) -> str:
    """A short-lived, stream-only credential (SEC-1 / ADR-059 R5).

    The SSE gateway accepts this type — and ONLY this type — through the
    ``?token=`` query fallback a browser EventSource needs. A five-minute
    single-purpose token sitting in a server access log is noise; a
    30-minute access token there is a replayable credential.
    """
    return _create_token(
        user_id,
        ttl_seconds,
        "stream",
        {"tenant_id": tenant_id, "auth_version": int(auth_version)},
    )


def decode_token(token: str) -> dict[str, Any]:
    """Raise jwt.PyJWTError subclasses on invalid/expired tokens.

    Pins iss/aud and an explicit algorithm allowlist (no alg confusion).

    kid-aware verification (zero-logout rotation): a token whose header names
    the CURRENT secret's kid is verified with the current secret; one naming
    the PREVIOUS secret's kid (JWT_SECRET_PREVIOUS) is verified with that;
    a kid-less token — everything minted before the kid header existed — is
    tried against current then previous, so a secret roll invalidates nothing
    before its natural expiry. An UNKNOWN kid fails immediately: the signature
    is never offered to a secret the token does not claim.

    ``exp`` and ``sub`` are REQUIRED claims, not validated-if-present: PyJWT
    only enforces a claim that exists, so a signature-valid token without
    ``exp`` would otherwise be an unbounded-accept path (it never expires).
    Every ``_create_token`` mint sets both.
    """
    settings = get_settings()
    kid: str | None
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError:
        raise  # malformed token — no point trying any secret

    if kid:
        if kid == _kid(settings.jwt_secret):
            candidates = [settings.jwt_secret]
        elif settings.jwt_secret_previous and kid == _kid(
            settings.jwt_secret_previous
        ):
            candidates = [settings.jwt_secret_previous]
        else:
            raise jwt.InvalidTokenError(
                "token kid does not match any configured signing secret"
            )
    else:
        candidates = [settings.jwt_secret]
        if settings.jwt_secret_previous:
            candidates.append(settings.jwt_secret_previous)

    last_error: Exception | None = None
    for secret in candidates:
        try:
            return jwt.decode(
                token,
                secret,
                algorithms=[JWT_ALGORITHM],  # allowlist — never follow token headers
                issuer="sales-os",
                audience="sales-os",
                # Missing exp/sub is final (see docstring): without this a
                # signature-valid token lacking exp would be accepted forever.
                options={"require": ["exp", "sub"]},
            )
        except jwt.InvalidSignatureError as exc:
            # Wrong half of the rotation pair — the next candidate may match.
            # Any other decode error (expired, bad aud) is final: the signature
            # already verified, so trying another secret cannot help.
            last_error = exc
    raise last_error if last_error is not None else jwt.InvalidTokenError(
        "no signing secret available"
    )


def create_visitor_token(session_key: str, tenant_id: str, *, widget: str) -> str:
    """Mint a webchat visitor session (S2).

    The visitor's identity is the ``session_key`` — and it must be OURS, not
    something the caller typed. A client-chosen key meant anyone could
    impersonate a visitor and read their conversation by guessing it.
    """
    settings = get_settings()
    return _create_token(
        session_key,
        settings.webchat_session_ttl_seconds,
        "webchat_visitor",
        {"tenant_id": str(tenant_id), "widget": widget},
    )


def decode_visitor_token(token: str) -> dict[str, Any]:
    """Decode a visitor session token; raises ValidationError, never a 500."""
    from app.core.errors import ValidationError

    try:
        payload = decode_token(token)
    except Exception as exc:  # noqa: BLE001 — expired/forged/wrong-signature
        raise ValidationError("invalid visitor session") from exc
    if payload.get("type") != "webchat_visitor":
        raise ValidationError("wrong token type")
    if not payload.get("sub") or not payload.get("tenant_id"):
        raise ValidationError("incomplete visitor session")
    return payload

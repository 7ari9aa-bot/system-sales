"""JWT + password primitives (Stage 2 builds the full auth flows on these)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
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
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    return _create_token(
        user_id, settings.access_token_ttl_seconds, "access", claims or {}
    )


def create_refresh_token(user_id: str, claims: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    return _create_token(
        user_id, settings.refresh_token_ttl_seconds, "refresh", claims or {}
    )


def decode_token(token: str) -> dict[str, Any]:
    """Raise jwt.PyJWTError subclasses on invalid/expired tokens.

    Pins iss/aud and an explicit algorithm allowlist (no alg confusion).
    """
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],  # allowlist — never follow token headers
        issuer="sales-os",
        audience="sales-os",
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

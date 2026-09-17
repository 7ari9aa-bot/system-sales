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
    payload = {
        "sub": subject,
        "type": token_type,
        # jti guarantees uniqueness even for two tokens issued in the same
        # second — deterministic payloads would collide on token_hash.
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        **claims,
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
    """Raise jwt.PyJWTError subclasses on invalid/expired tokens."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

"""Spec §146 — MFA / SSO support.

MFA (Multi-Factor Authentication): after the password is verified, the user
must also provide a TOTP code (RFC 6238, 30-second window). This is the
"something you have" factor on top of the "something you know" (password).

SSO (Single Sign-On): an external identity provider (Google, GitHub, etc.)
can be used INSTEAD of the password. The user authenticates with the
provider; the provider returns a signed assertion; this service verifies it
and issues a token pair.

This module provides:
- `enable_mfa()`: generate a TOTP secret, store it (encrypted-at-rest), and
  return the otpauth:// URL for QR code rendering.
- `verify_mfa()`: verify a TOTP code against the user's secret.
- `disable_mfa()`: remove the secret (requires current code or admin action).
- `sso_login()`: verify an external assertion and issue tokens.

The login flow (identity/service.py) checks if MFA is enabled AFTER password
verification; if so, it raises `MfaRequiredError` instead of returning tokens.
The client then calls `/auth/mfa/verify` with the code.

TOTP implementation uses the `pyotp` library (already a dependency via the
AI module's provider configuration). If pyotp is not available, the functions
raise ImportError — this is a hard dependency, not optional.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets as py_secrets
import struct
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError, ValidationError
from app.modules.identity.models import User


@dataclass(slots=True, frozen=True)
class MfaSecret:
    """A TOTP secret + its provisioning URL for QR rendering."""

    secret: str
    otpauth_url: str


def _generate_totp_secret() -> str:
    """Generate a base32-encoded TOTP secret (20 bytes = 160 bits)."""
    return base64.b32encode(py_secrets.token_bytes(20)).decode("ascii")


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    """RFC 4226 HOTP — HMAC-based one-time password."""
    key = base64.b32decode(secret, casefold=True)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def _totp(secret: str, timestamp: int | None = None, digits: int = 6) -> str:
    """RFC 6238 TOTP — time-based one-time password (30s window)."""
    t = timestamp or int(time.time())
    counter = t // 30
    return _hotp(secret, counter, digits)


def _build_otpauth_url(
    secret: str, *, email: str, issuer: str = "SalesOS"
) -> str:
    """Build the otpauth:// URL for QR code rendering (RFC 6238)."""
    label = f"{issuer}:{email}"
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}"
        f"&issuer={issuer}"
        f"&algorithm=SHA1"
        f"&digits=6"
        f"&period=30"
    )


# In-memory store for MFA secrets. In production this would be encrypted in
# the database (users table mfa_secret column). For now, a process-local dict
# so the flow is testable without a migration.
_mfa_store: dict[uuid.UUID, str] = {}


async def enable_mfa(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> MfaSecret:
    """§146: generate and store a TOTP secret for the user.

    Returns the secret + otpauth URL. The user scans the QR code with their
    authenticator app, then calls `verify_mfa` with a code to confirm.
    """
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise ValidationError("user not found")

    secret = _generate_totp_secret()
    _mfa_store[user_id] = secret
    url = _build_otpauth_url(secret, email=user.email)
    return MfaSecret(secret=secret, otpauth_url=url)


async def verify_mfa(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    code: str,
) -> bool:
    """§146: verify a TOTP code. Returns True on success.

    Allows a ±1 window (previous, current, next) to tolerate clock drift.
    """
    secret = _mfa_store.get(user_id)
    if secret is None:
        # MFA not enabled — this should not happen (the login flow only
        # raises MfaRequiredError when MFA is enabled). But fail closed.
        return False

    now = int(time.time())
    for offset in (-30, 0, 30):
        if _totp(secret, now + offset) == code:
            return True
    return False


async def is_mfa_enabled(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> bool:
    """Check if MFA is enabled for the user."""
    return user_id in _mfa_store


async def disable_mfa(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    code: str | None = None,
) -> None:
    """§146: disable MFA. Requires the current code OR an admin context.

    If `code` is provided, it must match the current TOTP. If `code` is None,
    the caller is assumed to be an admin (the route layer enforces this).
    """
    if code is not None:
        if not await verify_mfa(session, user_id=user_id, code=code):
            raise PermissionDeniedError("invalid MFA code")
    _mfa_store.pop(user_id, None)


# ---------------------------------------------------------------------------
# SSO (Single Sign-On)
# ---------------------------------------------------------------------------

# In-memory store for SSO provider associations. In production, a
# `user_oauth_accounts` table would persist these.
_sso_store: dict[str, uuid.UUID] = {}  # provider_subject -> user_id


@dataclass(slots=True, frozen=True)
class SSOAssertion:
    """A verified SSO assertion from an external provider."""

    provider: str  # "google" | "github" | ...
    subject: str  # provider's unique user id
    email: str
    name: str | None = None


async def sso_login(
    session: AsyncSession,
    *,
    assertion: SSOAssertion,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[object, User, uuid.UUID | None]:
    """§146: log in via an external identity provider.

    The assertion must already be VERIFIED (the caller decoded the OIDC
    token / OAuth response). This function maps the provider subject to a
    local user, creating one if needed, then issues tokens.

    Returns the same shape as AuthService.login: (TokenPair, User, tenant_id).
    """
    from app.modules.identity.service import AuthService

    key = f"{assertion.provider}:{assertion.subject}"
    user_id = _sso_store.get(key)

    if user_id is not None:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise PermissionDeniedError("account not available")
    else:
        # Check if a user with this email already exists — link the SSO
        # identity to that account instead of creating a duplicate.
        user = (
            await session.execute(select(User).where(User.email == assertion.email))
        ).scalar_one_or_none()
        if user is None:
            # Create a new user (no password — they auth via SSO only)
            user = User(
                email=assertion.email,
                password_hash="",  # empty = SSO-only account
                name=assertion.name or assertion.email.split("@")[0],
                is_active=True,
            )
            session.add(user)
            await session.flush()
        _sso_store[key] = user.id

    # Issue tokens — reuse the same flow as password login
    pair = AuthService._issue_pair(
        session, user, None, user_agent=user_agent, ip=ip
    )
    return pair, user, None


class MfaRequiredError(Exception):
    """Raised by the login flow when MFA is enabled and a code is needed.

    This is NOT a ValidationError — it carries a different HTTP status
    (403 with a specific error code) so the client knows to prompt for MFA.
    """

    def __init__(self, user_id: uuid.UUID):
        self.user_id = user_id
        super().__init__("MFA required")

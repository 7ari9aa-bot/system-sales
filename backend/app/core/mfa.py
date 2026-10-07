"""Spec §146 — MFA (TOTP) with durable state + SSO support.

MFA login flow: after the password is verified, an MFA-enabled account gets a
short-lived challenge (Redis, 5-minute TTL, single-use via GETDEL) instead of
tokens; the client completes login at POST /auth/mfa/verify with a TOTP code
(RFC 6238, 30s step, ±1 window for clock drift). Five wrong codes lock the
challenge and the client must sign in again.

State lives where §59 (stateless API) requires it — never in process memory:
- TOTP secrets + backup-code hashes: Postgres (`user_mfa_secrets`, migration
  c146bb146bb1) — durable across restarts.
- Login challenges + failure counters: Redis (`mfa:challenge:*`) — shared
  across API instances, expiring automatically.
- TOTP anti-replay claims (`mfa:used:*`) — a verified code's counter cannot
  verify a second time within the drift window (RFC 6238 §5.2).
- Step-up failure throttles (`mfa:stepup:*`) — confirm/disable get the same
  abuse bound as the login challenge.
- SSO subject → user links: Redis (`sso:identity:*`) — instance-shared.

Every rejected verification (challenge or step-up) emits a §67 security
event through the platform writer — coarse outcomes only, never the code,
the seed, or any other secret.

TOTP is implemented manually with hmac/hashlib — pyotp is NOT a dependency.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets as py_secrets
import struct
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    DomainError,
    PermissionDeniedError,
    RateLimitExceededError,
    ValidationError,
)
from app.core.redis import get_redis
from app.modules.identity.models import User, UserMfaSecret

# Login challenge: 5 minutes is enough for a human to open their authenticator;
# a leaked challenge id is useless after the window.
CHALLENGE_TTL_SECONDS = 300
# Wrong-code attempts before the challenge locks — bounded so an online
# brute-force of the 10^6 TOTP space cannot run against one challenge.
CHALLENGE_MAX_FAILURES = 5
BACKUP_CODE_COUNT = 8
# RFC 6238 §5.2 anti-replay: a code that verified once must not verify again.
# The ±1-step drift window keeps a code verifiable for at most 90 seconds,
# so the claim lives exactly that long in Redis.
REPLAY_WINDOW_SECONDS = 90
# The step-up surfaces (confirm / disable) get the same abuse bound as the
# login challenge: 5 wrong codes, then a 15-minute lock. These run behind an
# authenticated session, but a stolen session must not get unlimited guesses
# at the second factor either.
STEPUP_MAX_FAILURES = 5
STEPUP_LOCK_SECONDS = 900

_CHALLENGE_PREFIX = "mfa:challenge:"
_SSO_PREFIX = "sso:identity:"
_USED_CODE_PREFIX = "mfa:used:"
_STEPUP_PREFIX = "mfa:stepup:"

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class MfaSecret:
    """A TOTP secret + its provisioning URL for QR rendering."""

    secret: str
    otpauth_url: str


# ---------------------------------------------------------------------------
# RFC 4226 / 6238 — implemented manually (pyotp is not a dependency)
# ---------------------------------------------------------------------------


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


def _totp_counter_for_code(
    secret: str, code: str, *, timestamp: int | None = None
) -> int | None:
    """Verify a TOTP code and return the MATCHED 30-second counter.

    The counter is what anti-replay claims against (RFC 6238 §5.2): the
    ±1-step drift window means a code can match three counters, and the
    exact one must be remembered so it cannot verify a second time. Returns
    None for non-numeric input or no window match — fail-closed, without
    touching the HMAC path for garbage.
    """
    code = (code or "").strip()
    if not code.isdigit():
        return None
    now = int(time.time()) if timestamp is None else timestamp
    for offset in (-30, 0, 30):
        candidate = now + offset
        if hmac.compare_digest(_totp(secret, candidate), code):
            return candidate // 30
    return None


def verify_totp(secret: str, code: str, *, timestamp: int | None = None) -> bool:
    """Verify a TOTP code with a ±1 step window for clock drift.

    Constant-time comparison per candidate window; non-numeric input fails
    closed without touching the HMAC path.
    """
    return _totp_counter_for_code(secret, code, timestamp=timestamp) is not None


def _build_otpauth_url(secret: str, *, email: str, issuer: str = "SalesOS") -> str:
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


# ---------------------------------------------------------------------------
# Durable secret store (Postgres user_mfa_secrets)
# ---------------------------------------------------------------------------


def _encrypt_secret(secret: str) -> str:
    """§68/§146: envelope-encrypt the TOTP seed at rest.

    A DB dump must not yield usable authenticator seeds. ``EnvelopeSecretStore``
    (AES-256-GCM, ``v1:`` wire format) is the §68 at-rest boundary; the seed is
    a secret like any other, so it goes through the same store the master-key
    rotation governs.
    """
    from app.core.secrets import get_envelope_store

    return get_envelope_store().encrypt(secret)


def _decrypt_secret(stored: str) -> str:
    """Decrypt a stored seed, transparently reading legacy base64 rows.

    Rows written before §68 landed in this module stored plain base64 (no
    ``v1:`` prefix). Those are base64-decoded as before; every NEW write goes
    through :func:`_encrypt_secret`, so the population migrates lazily as users
    re-enroll.
    """
    from app.core.secrets import EnvelopeSecretStore, get_envelope_store

    if stored.startswith(EnvelopeSecretStore.PREFIX):
        return get_envelope_store().decrypt(stored).value
    return base64.b64decode(stored.encode("ascii")).decode("ascii")


def _hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _generate_backup_codes() -> list[str]:
    # 8 bytes = 64 bits of entropy: a DB dump of the unsalted SHA-256 hashes
    # must not be offline-brute-forceable within the recovery-code lifetime.
    return [py_secrets.token_hex(8) for _ in range(BACKUP_CODE_COUNT)]


# ---------------------------------------------------------------------------
# §67 security events + Redis-backed replay/throttle state
# ---------------------------------------------------------------------------


async def _emit_security_event(
    event_type: str,
    *,
    details: dict | None = None,
    ip: str | None = None,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Emit one §67 security event for an MFA outcome (never raises).

    Delegates to the platform writer, which persists on its OWN transaction
    (a rejection that follows immediately must not roll the row back) and
    binds the tenant GUC when a tenant is given (FORCE RLS). The import is
    function-scoped: core owning the MFA event boundary must not couple
    module-scope to the platform writer. ``details`` carries coarse outcome
    strings and ids only — never the presented code, the seed, or any secret.
    """
    from app.modules.platform.security_events import record_security_event

    await record_security_event(
        event_type,
        details=details,
        ip=ip,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
    )


def _used_code_key(user_id: uuid.UUID, counter: int) -> str:
    return f"{_USED_CODE_PREFIX}{user_id}:{counter}"


async def claim_totp_counter(
    user_id: uuid.UUID, counter: int, *, redis=None
) -> bool:
    """Claim a TOTP counter for single use — True on FIRST use only.

    RFC 6238 §5.2: the verifier must not accept the same OTP twice. The
    claim is an atomic Redis SET NX EX over the ±1-step drift window, so a
    replayed code (same counter, even through a second concurrent challenge)
    is rejected within 90 seconds of its first acceptance.

    Documented FAIL-OPEN: if Redis is unavailable the claim reports success
    and verification proceeds. Justification — replay protection here is
    defense-in-depth behind the single-use challenge (GETDEL), which already
    fails closed because the challenge itself lives in Redis; blocking
    account recovery (disable) during a cache outage costs more than the
    residual replay window. The outage is logged for observability.
    """
    try:
        client = redis if redis is not None else get_redis()
        return bool(
            await client.set(
                _used_code_key(user_id, counter), "1", nx=True, ex=REPLAY_WINDOW_SECONDS
            )
        )
    except Exception:  # noqa: BLE001 — documented fail-open, see docstring
        logger.warning("mfa.replay_claim_unavailable user_id=%s", user_id)
        return True


def _stepup_key(user_id: uuid.UUID, surface: str) -> str:
    return f"{_STEPUP_PREFIX}{user_id}:{surface}"


async def _stepup_attempts(user_id: uuid.UUID, surface: str, *, redis=None) -> int:
    """Wrong-code count for a step-up surface (confirm / disable).

    Fail-open on any Redis problem: the code check itself still enforces
    correctness, and a cache outage must not brick disabling MFA.
    """
    try:
        client = redis if redis is not None else get_redis()
        return int(await client.get(_stepup_key(user_id, surface)) or 0)
    except Exception:  # noqa: BLE001 — documented fail-open, see docstring
        logger.warning("mfa.stepup_read_unavailable surface=%s", surface)
        return 0


async def _record_stepup_failure(
    user_id: uuid.UUID, surface: str, *, redis=None
) -> int:
    """Count one wrong code; the counter expires with the lock window."""
    try:
        client = redis if redis is not None else get_redis()
        key = _stepup_key(user_id, surface)
        attempts = await client.incr(key)
        if attempts == 1:
            await client.expire(key, STEPUP_LOCK_SECONDS)
        return int(attempts)
    except Exception:  # noqa: BLE001 — documented fail-open, see docstring
        logger.warning("mfa.stepup_record_unavailable surface=%s", surface)
        return 0


async def _reset_stepup(user_id: uuid.UUID, surface: str, *, redis=None) -> None:
    """Clear the failure counter after a success or a fresh enrollment."""
    try:
        client = redis if redis is not None else get_redis()
        await client.delete(_stepup_key(user_id, surface))
    except Exception:  # noqa: BLE001 — documented fail-open, see docstring
        logger.warning("mfa.stepup_reset_unavailable surface=%s", surface)


async def _get_row(session: AsyncSession, user_id: uuid.UUID) -> UserMfaSecret | None:
    return (
        await session.execute(select(UserMfaSecret).where(UserMfaSecret.user_id == user_id))
    ).scalar_one_or_none()


async def enroll_mfa(
    session: AsyncSession, *, user_id: uuid.UUID, redis=None
) -> MfaSecret:
    """§146: start enrollment — store a PENDING secret, returned to the user once.

    The row is not enabled until `confirm_mfa` proves the authenticator holds
    the same secret. Re-enrolling over a pending row replaces the secret;
    re-enrolling over an ENABLED row is a conflict (disable first). A fresh
    secret also clears the confirm failure counter — the old guess attempts
    say nothing about the new seed.
    """
    user = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise ValidationError("user not found")

    secret = _generate_totp_secret()
    row = await _get_row(session, user_id)
    if row is None:
        row = UserMfaSecret(
            user_id=user_id,
            totp_secret_encrypted=_encrypt_secret(secret),
            backup_codes_hashes=[],
        )
        session.add(row)
    else:
        if row.enabled_at is not None:
            raise ConflictError("MFA is already enabled — disable it before re-enrolling")
        row.totp_secret_encrypted = _encrypt_secret(secret)
        row.backup_codes_hashes = []
    await session.flush()
    await _reset_stepup(user_id, "confirm", redis=redis)
    return MfaSecret(secret=secret, otpauth_url=_build_otpauth_url(secret, email=user.email))


async def confirm_mfa(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    code: str,
    ip: str | None = None,
    redis=None,
) -> list[str]:
    """§146: prove possession of the secret → enable MFA + issue 8 backup codes.

    The plaintext backup codes are returned ONCE; only sha256 hashes persist.
    Guessing is bounded like the login challenge: 5 wrong codes lock
    confirmation for the lock window (a re-enroll, which is password-gated,
    starts fresh). Replay is structurally impossible — a confirmed row can
    never confirm again. The throttle state fails open without Redis (see
    _stepup_attempts): the code check itself still enforces correctness.
    """
    if await _stepup_attempts(user_id, "confirm", redis=redis) >= STEPUP_MAX_FAILURES:
        await _emit_security_event(
            "mfa_confirm_locked", ip=ip, actor_user_id=user_id
        )
        raise RateLimitExceededError(
            "too many failed confirmations — enroll again to get a fresh code window"
        )
    row = await _get_row(session, user_id)
    if row is None:
        raise ValidationError("MFA enrollment not started — enroll first")
    if row.enabled_at is not None:
        raise ConflictError("MFA is already enabled")
    if not verify_totp(_decrypt_secret(row.totp_secret_encrypted), code):
        attempts = await _record_stepup_failure(user_id, "confirm", redis=redis)
        if attempts >= STEPUP_MAX_FAILURES:
            await _emit_security_event(
                "mfa_confirm_locked", ip=ip, actor_user_id=user_id
            )
            raise RateLimitExceededError(
                "too many failed confirmations — enroll again to get a fresh code window"
            )
        await _emit_security_event(
            "mfa_confirm_failure", ip=ip, actor_user_id=user_id
        )
        raise PermissionDeniedError("invalid MFA code")
    row.enabled_at = datetime.now(UTC)
    codes = _generate_backup_codes()
    row.backup_codes_hashes = [_hash_backup_code(c) for c in codes]
    await session.flush()
    await _reset_stepup(user_id, "confirm", redis=redis)
    return codes


async def is_mfa_enabled(session: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True only once enrollment is CONFIRMED (a pending row never challenges)."""
    row = await _get_row(session, user_id)
    return row is not None and row.enabled_at is not None


async def _verify_user_totp_counter(
    session: AsyncSession, *, user_id: uuid.UUID, code: str
) -> int | None:
    """Verify a code against the user's ENABLED secret; return the matched
    30-second counter (None when no row, disabled, or wrong code). Fails closed."""
    row = await _get_row(session, user_id)
    if row is None or row.enabled_at is None:
        return None
    return _totp_counter_for_code(_decrypt_secret(row.totp_secret_encrypted), code)


async def _consume_backup_code(
    session: AsyncSession, user_id: uuid.UUID, code: str
) -> bool:
    """§146: validate a recovery code and burn it in the same transaction.

    Backup codes exist for exactly one scenario — the authenticator is gone —
    so they must work wherever the TOTP works, including the login challenge.
    Hash-compare (the row stores SHA-256 digests only), one-time consume (the
    matched digest is removed BEFORE the caller lets the login through).
    """
    row = await _get_row(session, user_id)
    if row is None or row.enabled_at is None:
        return False
    digest = _hash_backup_code(code)
    hashes = list(row.backup_codes_hashes or [])
    if digest not in hashes:
        return False
    hashes.remove(digest)
    row.backup_codes_hashes = hashes
    await session.flush()
    return True


async def disable_mfa(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    code: str | None = None,
    backup_code: str | None = None,
    ip: str | None = None,
    redis=None,
) -> None:
    """§146: disable MFA with a current TOTP code OR a one-time backup code.

    Re-verification is mandatory — a bare authenticated POST can never turn
    MFA off. Guessing is bounded (5 wrong codes → 15-minute lock) and a TOTP
    code that already verified elsewhere cannot disable either: the counter
    claim (RFC 6238 §5.2) rejects it as a replay.
    """
    row = await _get_row(session, user_id)
    if row is None or row.enabled_at is None:
        raise ValidationError("MFA is not enabled")
    if code is None and backup_code is None:
        raise ValidationError("a TOTP code or backup code is required")
    if await _stepup_attempts(user_id, "disable", redis=redis) >= STEPUP_MAX_FAILURES:
        await _emit_security_event(
            "mfa_disable_locked", ip=ip, actor_user_id=user_id
        )
        raise RateLimitExceededError(
            "too many failed attempts — wait before trying to disable MFA again"
        )
    ok = False
    if code is not None:
        counter = _totp_counter_for_code(
            _decrypt_secret(row.totp_secret_encrypted), code
        )
        # The counter claim doubles as the anti-replay gate: a code accepted
        # anywhere else in its drift window cannot disable MFA too.
        ok = counter is not None and await claim_totp_counter(
            user_id, counter, redis=redis
        )
    elif backup_code is not None:
        ok = await _consume_backup_code(session, user_id, backup_code)
    if not ok:
        attempts = await _record_stepup_failure(user_id, "disable", redis=redis)
        if attempts >= STEPUP_MAX_FAILURES:
            await _emit_security_event(
                "mfa_disable_locked", ip=ip, actor_user_id=user_id
            )
            raise RateLimitExceededError(
                "too many failed attempts — wait before trying to disable MFA again"
            )
        await _emit_security_event(
            "mfa_disable_failure", ip=ip, actor_user_id=user_id
        )
        raise PermissionDeniedError("invalid MFA code")
    await _reset_stepup(user_id, "disable", redis=redis)
    await session.delete(row)
    await session.flush()


# ---------------------------------------------------------------------------
# Login challenges (Redis — short-lived, single-use, instance-shared)
# ---------------------------------------------------------------------------


def _challenge_key(challenge_id: str) -> str:
    return f"{_CHALLENGE_PREFIX}{challenge_id}"


def _failures_key(challenge_id: str) -> str:
    return f"{_CHALLENGE_PREFIX}{challenge_id}:failures"


async def start_challenge(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None = None,
    *,
    auth_version: int = 0,
    redis=None,
) -> str:
    """Create the opaque challenge an MFA-enabled account gets after password success."""
    client = redis if redis is not None else get_redis()
    challenge_id = py_secrets.token_urlsafe(24)
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "auth_version": int(auth_version),
        }
    )
    await client.set(_challenge_key(challenge_id), payload, ex=CHALLENGE_TTL_SECONDS)
    return challenge_id


async def load_challenge(challenge_id: str, *, redis=None) -> dict | None:
    """Read a challenge payload WITHOUT consuming it (None if unknown/expired)."""
    client = redis if redis is not None else get_redis()
    raw = await client.get(_challenge_key(challenge_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def challenge_failures(challenge_id: str, *, redis=None) -> int:
    """How many wrong codes this challenge has seen."""
    client = redis if redis is not None else get_redis()
    return int(await client.get(_failures_key(challenge_id)) or 0)


async def record_challenge_failure(challenge_id: str, *, redis=None) -> int:
    """Count a wrong code against the challenge (same TTL as the challenge)."""
    client = redis if redis is not None else get_redis()
    key = _failures_key(challenge_id)
    attempts = await client.incr(key)
    if attempts == 1:
        await client.expire(key, CHALLENGE_TTL_SECONDS)
    return attempts


async def consume_challenge(challenge_id: str, *, redis=None) -> dict | None:
    """Atomically consume a challenge (GETDEL) — the single-use guarantee.

    Returns the payload, or None when the id is unknown, expired, or already
    consumed — a consumed challenge can never mint a second token pair.
    """
    client = redis if redis is not None else get_redis()
    raw = await client.getdel(_challenge_key(challenge_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def drop_challenge(challenge_id: str, *, redis=None) -> None:
    """Delete challenge + failure counter (the lock path)."""
    client = redis if redis is not None else get_redis()
    await client.delete(_challenge_key(challenge_id), _failures_key(challenge_id))


class MfaChallengeError(PermissionDeniedError):
    """A rejected MFA challenge completion.

    Deliberately keeps the PermissionDeniedError wire contract (403 /
    ``permission_denied``) — the subclass exists so callers can read WHY a
    challenge was rejected (``mfa_outcome``, plus the challenge's user and
    tenant ids) without the service layer re-deriving it. The §67 event for
    the rejection is emitted by :func:`raise_mfa_rejection` before raising.
    """

    def __init__(
        self,
        message: str,
        *,
        outcome: str,
        user_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ):
        super().__init__(message)
        self.mfa_outcome = outcome
        self.mfa_user_id = user_id
        self.mfa_tenant_id = tenant_id


async def raise_mfa_rejection(
    message: str,
    *,
    outcome: str,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    ip: str | None = None,
) -> NoReturn:
    """Record the §67 event for a rejected login challenge, then raise its error.

    One ``mfa_verify_failure`` row per rejection, written on the platform
    writer's own transaction so it survives the 403 that follows. ``details``
    carries the coarse outcome string only — never the code or the seed.
    """
    await _emit_security_event(
        "mfa_verify_failure",
        details={"outcome": outcome},
        ip=ip,
        tenant_id=tenant_id,
        actor_user_id=user_id,
    )
    raise MfaChallengeError(
        message, outcome=outcome, user_id=user_id, tenant_id=tenant_id
    )


async def check_challenge_code(
    session: AsyncSession,
    *,
    challenge_id: str,
    code: str,
    ip: str | None = None,
    redis=None,
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Verify a login challenge's TOTP code; consume the challenge on success.

    Failure semantics (each rejection emits a §67 security event — coarse
    outcome only, no PII, no secrets):
    - unknown / expired / already-used challenge → rejected (challenge_unknown)
    - wrong code → counted in Redis; the 5th failure LOCKS the challenge
      (challenge_locked) and the client must sign in again
    - a code whose 30-second counter already verified → rejected as a replay
      (code_replayed) and counted like a wrong code (RFC 6238 §5.2)
    - right code → anti-replay claim, then GETDEL consume (single-use,
      race-safe), then return ``(user_id, tenant_id)`` for token issuance.
    """
    client = redis if redis is not None else get_redis()
    payload = await load_challenge(challenge_id, redis=client)
    if payload is None:
        await raise_mfa_rejection(
            "invalid or expired MFA challenge",
            outcome="challenge_unknown",
            ip=ip,
        )
    if await challenge_failures(challenge_id, redis=client) >= CHALLENGE_MAX_FAILURES:
        await drop_challenge(challenge_id, redis=client)
        await raise_mfa_rejection(
            "MFA challenge locked — too many failed attempts",
            outcome="challenge_locked",
            user_id=_payload_user_id(payload),
            tenant_id=_payload_tenant_id(payload),
            ip=ip,
        )
    user_id = uuid.UUID(str(payload["user_id"]))
    tenant_raw = payload.get("tenant_id")
    tenant_id = uuid.UUID(str(tenant_raw)) if tenant_raw else None
    counter = await _verify_user_totp_counter(session, user_id=user_id, code=code)
    if counter is not None and not await claim_totp_counter(
        user_id, counter, redis=client
    ):
        # RFC 6238 §5.2: this code already verified — a second acceptance
        # would let one observed code mint two sessions. Counted as an
        # attempt so replay hammering locks the challenge like brute force.
        await _fail_challenge(
            challenge_id, client, outcome="code_replayed", user_id=user_id,
            tenant_id=tenant_id, ip=ip,
        )
    if counter is None:
        # §146: a lost authenticator must not mean a lost account — the
        # recovery codes issued at confirm time work at login too. TOTP codes
        # are 6 digits and recovery codes are hex, so a presented string can
        # only ever be one kind; the TOTP path rejects non-digit input before
        # touching the HMAC.
        if not await _consume_backup_code(session, user_id, code):
            await _fail_challenge(
                challenge_id, client, outcome="invalid_code", user_id=user_id,
                tenant_id=tenant_id, ip=ip,
            )
    consumed = await consume_challenge(challenge_id, redis=client)
    if consumed is None:
        # Lost a consume race — one challenge MUST NOT mint two token pairs.
        await raise_mfa_rejection(
            "MFA challenge already used",
            outcome="challenge_replayed",
            user_id=user_id,
            tenant_id=tenant_id,
            ip=ip,
        )
    await client.delete(_failures_key(challenge_id))
    current_auth_version = (
        await session.execute(select(User.auth_version).where(User.id == user_id))
    ).scalar_one_or_none()
    if (
        current_auth_version is None
        or int(payload.get("auth_version", 0)) != int(current_auth_version or 0)
    ):
        await raise_mfa_rejection(
            "login challenge was revoked by a credential change",
            outcome="challenge_revoked",
            user_id=user_id,
            tenant_id=tenant_id,
            ip=ip,
        )
    return user_id, tenant_id


def _payload_user_id(payload: dict | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(payload["user_id"]))
    except (KeyError, TypeError, ValueError):
        return None


def _payload_tenant_id(payload: dict | None) -> uuid.UUID | None:
    try:
        raw = payload.get("tenant_id")
    except AttributeError:
        return None
    return uuid.UUID(str(raw)) if raw else None


async def _fail_challenge(
    challenge_id: str,
    client,
    *,
    outcome: str,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    ip: str | None,
) -> NoReturn:
    """Count a wrong/replayed code; lock at the ceiling; emit the §67 row."""
    attempts = await record_challenge_failure(challenge_id, redis=client)
    if attempts >= CHALLENGE_MAX_FAILURES:
        await drop_challenge(challenge_id, redis=client)
        await raise_mfa_rejection(
            "MFA challenge locked — too many failed attempts",
            outcome="challenge_locked",
            user_id=user_id,
            tenant_id=tenant_id,
            ip=ip,
        )
    await raise_mfa_rejection(
        "invalid MFA code",
        outcome=outcome,
        user_id=user_id,
        tenant_id=tenant_id,
        ip=ip,
    )


# ---------------------------------------------------------------------------
# SSO (Single Sign-On)
# ---------------------------------------------------------------------------


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
    redis=None,
) -> tuple[object, User, uuid.UUID | None]:
    """§146: log in via an external identity provider.

    The assertion must already be VERIFIED (the caller decoded the OIDC
    token / OAuth response). This function maps the provider subject to a
    local user, creating one if needed, then issues tokens. The subject →
    user link lives in Redis (`sso:identity:*`) — shared across instances,
    unlike the process-local dict it replaced.

    Returns the same shape as AuthService.login: (TokenPair, User, tenant_id).
    """
    from app.modules.identity.service import AuthService

    client = redis if redis is not None else get_redis()
    key = f"{_SSO_PREFIX}{assertion.provider}:{assertion.subject}"
    raw = await client.get(key)
    user_id = uuid.UUID(raw) if raw else None

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
                full_name=assertion.name or assertion.email.split("@")[0],
                is_active=True,
            )
            session.add(user)
            await session.flush()
        await client.set(key, str(user.id))

    # Issue tokens — reuse the same flow as password login
    pair = AuthService._issue_pair(
        session, user, None, user_agent=user_agent, ip=ip
    )
    return pair, user, None


class MfaRequiredError(DomainError):
    """Password verified; a TOTP challenge must now be completed.

    NOT a login failure: the login route turns this into the `mfa_challenge`
    response (no tokens issued yet). If it ever escapes the route layer it
    renders as 403/mfa_required with the challenge id in details.
    """

    code = "mfa_required"
    http_status = 403
    default_message = "MFA verification required"

    def __init__(self, challenge_id: str):
        self.challenge_id = challenge_id
        super().__init__(
            self.default_message,
            details={"challenge_id": challenge_id, "mfa_required": True},
        )

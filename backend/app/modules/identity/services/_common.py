"""Shared helpers used across all identity sub-services.

Extracted from the original monolithic service.py so each sub-service can
import them without pulling 1,800 lines.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import sqlalchemy as sa

from app.core import auth_lockout
from app.core.errors import ConflictError
from app.core.redis import get_redis_or_none
from app.core.security import hash_password_async
from app.modules.identity.models import RefreshToken

logger = logging.getLogger(__name__)


class EmailAlreadyRegistered(ConflictError):
    """register() found an existing account for the email (audit finding 3).

    Subclasses ConflictError so any pre-existing caller keeps its 409 lineage,
    but the ROUTE distinguishes it: the register endpoint must answer a
    known address with the SAME neutral response as a fresh one. A distinct
    409 "email already registered" was a user-enumeration oracle — probing
    signup with an arbitrary address disclosed account existence before the
    attacker ever proved a credential — and it was half of the account
    pre-hijack attack (register a victim's address first, then let an
    invitation to that address bind the victim's role to the attacker).
    """


async def _record_audit(
    session,
    tenant_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: object,
    *,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Write this module's audit rows through the shared §66 core writer."""
    import sys
    svc = sys.modules.get("app.modules.identity.service")
    if svc and hasattr(svc, "_record_audit") and svc._record_audit is not _record_audit:
        return await svc._record_audit(
            session,
            tenant_id,
            actor_user_id,
            action,
            resource_type,
            resource_id,
            before=before,
            after=after,
        )

    from app.core.audit import write_audit_row

    await write_audit_row(
        session,
        tenant_id,
        actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        before=before,
        after=after,
    )


async def _record_security_event(
    event_type: str,
    *,
    details: dict | None = None,
    ip: str | None = None,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Persist a security event on its OWN transaction (§67)."""
    import sys
    svc = sys.modules.get("app.modules.identity.service")
    if svc and hasattr(svc, "_record_security_event") and svc._record_security_event is not _record_security_event:
        return await svc._record_security_event(
            event_type,
            details=details,
            ip=ip,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
        )

    from app.modules.platform.security_events import record_security_event

    await record_security_event(
        event_type,
        details=details,
        ip=ip,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
    )


async def _revoke_family_on_reuse(user_id: uuid.UUID) -> None:
    """Revoke every live refresh token for `user_id`, on its OWN transaction."""
    import sys
    svc = sys.modules.get("app.modules.identity.service")
    if svc and hasattr(svc, "_revoke_family_on_reuse") and svc._revoke_family_on_reuse is not _revoke_family_on_reuse:
        return await svc._revoke_family_on_reuse(user_id)

    from app.core.db import get_sessionmaker

    try:
        async with get_sessionmaker()() as session:
            async with session.begin():
                await session.execute(
                    sa.update(RefreshToken)
                    .where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                    )
                    .values(revoked_at=_now())
                )
    except Exception:  # noqa: BLE001 — revocation must not mask the 401 it accompanies
        logger.error("auth.reuse_revocation_failed user=%s", user_id, exc_info=True)


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# How long a JUST-rotated refresh token may be replayed without being treated
# as theft (audit finding 5). Two tabs hitting /auth/refresh in the same second
# serialize on the row lock: the winner rotates, the loser then re-reads the row
# as revoked. Without a grace window that loser was "reuse", and reuse revokes
# EVERY session the user owns — parallel tabs nuked the whole family. Within
# this window the same token is a concurrent duplicate, not an attack. The
# window is measured from the row's ORIGINAL revoked_at and the tolerated path
# never refreshes that timestamp, so replaying cannot extend it: past the
# window, the next replay is genuine reuse and revokes the family. An attacker
# who already holds the token can therefore mint at most a few extra pairs
# inside 45 seconds — they already had that credential — and loses everything
# the moment they hesitate.
_REFRESH_REUSE_GRACE_SECONDS = 45


_dummy_password_hash_cache: str | None = None


async def _dummy_password_hash() -> str:
    """A real bcrypt hash used when the account does not exist.

    Login used to short-circuit on `user is None` BEFORE hashing, so a missing
    account answered measurably faster than a wrong password — a timing oracle
    that enumerates registered emails (S12). Comparing against this hash makes
    both paths cost the same bcrypt work.

    The hash is cached as a STRING, never as the coroutine: an ``lru_cache`` on
    an ``async def`` stores the coroutine object itself, so the second caller
    awaits an already-consumed coroutine and every nonexistent-email login
    after the first 500s for the life of the process.
    """
    global _dummy_password_hash_cache
    if _dummy_password_hash_cache is None:
        # Benign race: concurrent first callers each compute a valid hash of
        # the same constant; the last write wins and both verify correctly.
        _dummy_password_hash_cache = await hash_password_async("not-a-real-password")
    return _dummy_password_hash_cache


async def _lockout_op(
    op: Callable[..., Awaitable[auth_lockout.LockoutStatus | None]],
    *,
    ip: str | None,
    email: str,
) -> auth_lockout.LockoutStatus | None:
    """Run one lockout op, fail-open on any Redis problem.

    get_redis_or_none() only reflects the §163 breaker's state — on the FIRST
    failed connection the breaker is still closed and the raw client raises
    (a live local outage, not a hypothetical). A cache outage must never take
    sign-in down, so every failure here degrades to "no lockout this try",
    mirroring the layered limiter's except policy (core/ratelimit.py): this
    layer only narrows brute force while the §25 auth bucket in front of
    login keeps failing closed.
    """
    import sys
    svc = sys.modules.get("app.modules.identity.service")
    _get_redis = getattr(svc, "get_redis_or_none", get_redis_or_none) if svc else get_redis_or_none
    redis = _get_redis()
    if redis is None:
        return None
    try:
        return await op(redis, ip=ip or "", email=email)
    except Exception:  # noqa: BLE001 — any Redis failure means "skip the layer"
        logger.warning("auth.lockout_unreachable op=%s", op.__name__, exc_info=True)
        return None

"""Manager PIN: a manager approves ONE action at the cashier's till.

The cashier stays signed in as themself. When something is above their authority (a discount over
the ceiling, a return on another cashier's drawer) the manager types a short PIN into the till.
That approval covers the single request it arrived with and nothing else: no session is handed
over, and the audit row names the MANAGER who approved, not the cashier who asked.

Why the checks are shaped the way they are:

* A 4-8 digit PIN has at most 10^8 values, so the hash does not protect it. What protects it is
  that guessing is throttled per manager (a shared Redis counter, the same progressive lock the
  login uses) and that the throttle is consulted BEFORE the hash is compared.
* Every way of failing returns the SAME message: no such manager, a manager with no PIN, a wrong
  PIN, a manager who no longer holds ``pos:override`` or no longer belongs to the shop. Telling
  them apart would let a cashier at the till map out who has a PIN.
* The slow hash runs even when there is nothing to compare against, so the response time does not
  say "that user has no PIN" either.
* The permission is read at approval time, not at PIN-setting time: a manager demoted yesterday
  cannot approve today with the PIN they set last month.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import Depends, Header, Request
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import auth_lockout
from app.core.audit import write_audit_row
from app.core.db import bind_tenant
from app.core.errors import CircuitOpenError, RateLimitExceededError
from app.core.redis import get_redis
from app.core.security import hash_password_async, verify_password_async
from app.modules.errors import PermissionDeniedError, ValidationError
from app.modules.identity.deps import TenantContext, TenantCtxDep
from app.modules.pos.models import ManagerPin

OVERRIDE_PERMISSION = "pos:override"

#: 4 to 8 digits. Shorter is guessable in one lock window; longer is not typed at a till.
_PIN_RE = re.compile(r"^[0-9]{4,8}$")

#: The one thing a caller is ever told about a failed approval.
_REFUSED = "manager approval refused"
_UNAVAILABLE = "manager approval is unavailable right now; try again shortly"

#: A real bcrypt hash of nothing in particular, so a lookup that finds no PIN still pays for a
#: hash comparison. Computed lazily (bcrypt is slow on purpose) and cached for the process.
_DECOY_HASH: str | None = None


async def _decoy() -> str:
    global _DECOY_HASH
    if _DECOY_HASH is None:
        _DECOY_HASH = await hash_password_async("00000000")
    return _DECOY_HASH


@dataclass(frozen=True, slots=True)
class OverrideGrant:
    """Who approved, and whether anyone did.

    ``active`` is what the money gates read in place of ``"pos:override" in permission_codes``.
    ``approved_by`` is the manager's user id when a PIN approved this request, or ``None`` when
    the caller is simply a manager acting on their own authority.
    """

    active: bool
    approved_by: UUID | None = None


NO_GRANT = OverrideGrant(active=False)


def _lock_key(tenant_id: UUID, manager_id: UUID) -> str:
    # auth_lockout hashes whatever it is given, so the key can carry ids safely.
    return f"pos_pin:{tenant_id}:{manager_id}"


class ManagerPinService:
    @staticmethod
    def validate_format(pin: object) -> str:
        if not isinstance(pin, str) or not _PIN_RE.fullmatch(pin):
            raise ValidationError("a PIN is 4 to 8 digits")
        return pin

    @staticmethod
    async def set_pin(session: AsyncSession, tenant_id: UUID, user_id: UUID, pin: object) -> None:
        """Create or replace this manager's PIN. The caller has already proven who they are."""
        clean = ManagerPinService.validate_format(pin)
        digest = await hash_password_async(clean)
        row = (
            await session.execute(
                sa.select(ManagerPin).where(
                    ManagerPin.tenant_id == tenant_id, ManagerPin.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(ManagerPin(tenant_id=tenant_id, user_id=user_id, pin_hash=digest))
        else:
            row.pin_hash = digest
            row.set_at = sa.func.now()
        await session.flush()
        # A new PIN starts with a clean slate: the old one's failures say nothing about it.
        await auth_lockout.reset(get_redis(), ip=str(tenant_id), email=str(user_id))

    @staticmethod
    async def set_own_pin(
        session: AsyncSession, tenant_id: UUID, user_id: UUID, *, password: str, pin: object
    ) -> None:
        """A manager sets their own PIN, after proving it is really them with their password.

        A wrong password counts against the same lock as a wrong PIN: otherwise this endpoint is
        a free password-guessing oracle for anyone holding a manager's open session.
        """
        redis = get_redis()
        scope = {"ip": str(tenant_id), "email": str(user_id)}
        try:
            status = await auth_lockout.check(redis, **scope)
        except RedisError:
            # Without the counter there is no limit on password guesses: refuse, never fall open.
            raise CircuitOpenError(_UNAVAILABLE) from None
        if status.locked:
            raise RateLimitExceededError(
                "too many wrong attempts; try again later",
                details={"retry_after": int(status.retry_after_seconds) + 1},
            )
        stored = (
            await session.execute(
                sa.text("SELECT password_hash FROM users WHERE id = :u"), {"u": user_id}
            )
        ).scalar_one_or_none()
        if not stored or not await verify_password_async(password, stored):
            await auth_lockout.record_failure(redis, **scope)
            raise PermissionDeniedError("password is incorrect")
        await ManagerPinService.set_pin(session, tenant_id, user_id, pin)
        await write_audit_row(
            session,
            tenant_id,
            user_id,
            action="pos.manager_pin.set",
            resource_type="pos_override",
            resource_id=str(user_id),
        )

    @staticmethod
    async def has_pin(session: AsyncSession, tenant_id: UUID, user_id: UUID) -> bool:
        return (
            await session.execute(
                sa.select(ManagerPin.id).where(
                    ManagerPin.tenant_id == tenant_id, ManagerPin.user_id == user_id
                )
            )
        ).first() is not None

    @staticmethod
    async def list_approvers(session: AsyncSession, tenant_id: UUID) -> list[dict[str, str]]:
        """The managers a cashier can ask: active here, role grants ``pos:override``, PIN set.

        Same test as ``_holds_override`` (so nobody is listed who could not approve), and only
        id + name come back: a cashier needs to pick a person, not to read an address book.
        """
        rows = await session.execute(
            sa.text(
                "SELECT DISTINCT u.id, COALESCE(NULLIF(u.full_name, ''), u.email) AS name "
                "FROM manager_pins mp "
                "JOIN tenant_users tu ON tu.user_id = mp.user_id AND tu.tenant_id = mp.tenant_id "
                "JOIN users u ON u.id = tu.user_id "
                "JOIN role_permissions rp ON rp.role_id = tu.role_id "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE mp.tenant_id = :t AND u.is_active AND p.code = :code "
                "ORDER BY name"
            ),
            {"t": tenant_id, "code": OVERRIDE_PERMISSION},
        )
        return [{"id": str(r.id), "name": r.name} for r in rows]

    @staticmethod
    async def _holds_override(session: AsyncSession, tenant_id: UUID, user_id: UUID) -> bool:
        """The manager is an active member of THIS shop and their role grants ``pos:override``."""
        row = await session.execute(
            sa.text(
                "SELECT 1 FROM tenant_users tu "
                "JOIN users u ON u.id = tu.user_id "
                "JOIN role_permissions rp ON rp.role_id = tu.role_id "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE tu.tenant_id = :t AND tu.user_id = :u AND u.is_active "
                "AND p.code = :code LIMIT 1"
            ),
            {"t": tenant_id, "u": user_id, "code": OVERRIDE_PERMISSION},
        )
        return row.first() is not None

    @staticmethod
    async def approve(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        cashier_id: UUID,
        manager_id: UUID,
        pin: str,
        operation: str,
    ) -> OverrideGrant:
        """Check the PIN and return a grant for ONE request, or refuse with a uniform message.

        Raises ``RateLimitExceededError`` while the manager's PIN is locked and
        ``PermissionDeniedError`` for every other failure. Both a refusal and a grant leave an
        audit row.
        """
        redis = get_redis()
        scope = {"ip": str(tenant_id), "email": str(manager_id)}

        try:
            status = await auth_lockout.check(redis, **scope)
        except RedisError:
            # Without the counter there is no limit on guesses: refuse (fail closed), say why, and
            # leave a trace. Never fall through to "no lock", and never a bare 500.
            await _audit_refusal(
                session, tenant_id, cashier_id, "pos.override.unavailable", manager_id, operation
            )
            raise CircuitOpenError(_UNAVAILABLE) from None
        if status.locked:
            await _audit_refusal(
                session, tenant_id, cashier_id, "pos.override.locked", manager_id, operation
            )
            raise RateLimitExceededError(
                "too many wrong PINs; try again later",
                details={"retry_after": int(status.retry_after_seconds) + 1},
            )

        stored = (
            await session.execute(
                sa.select(ManagerPin.pin_hash).where(
                    ManagerPin.tenant_id == tenant_id, ManagerPin.user_id == manager_id
                )
            )
        ).scalar_one_or_none()
        # Always pay for one comparison, whatever we found.
        matches = await verify_password_async(pin, stored or await _decoy())
        authorised = (
            stored is not None
            and matches
            and await ManagerPinService._holds_override(session, tenant_id, manager_id)
        )

        if not authorised:
            try:
                await auth_lockout.record_failure(redis, **scope)
            except RedisError:
                pass  # still a refusal and still audited below; only the count is lost
            await _audit_refusal(
                session, tenant_id, cashier_id, "pos.override.denied", manager_id, operation
            )
            raise PermissionDeniedError(_REFUSED)

        try:
            await auth_lockout.reset(redis, **scope)
        except RedisError:
            pass  # the PIN was right; a stale counter only means an earlier typo still counts
        await _audit(session, tenant_id, manager_id, "pos.override.granted", cashier_id, operation)
        return OverrideGrant(active=True, approved_by=manager_id)


async def _audit(
    session: AsyncSession,
    tenant_id: UUID,
    actor_id: UUID,
    action: str,
    other_id: UUID,
    operation: str,
) -> None:
    """One row per attempt. For a grant the actor is the manager; for a refusal, the cashier."""
    await write_audit_row(
        session,
        tenant_id,
        actor_id,
        action=action,
        resource_type="pos_override",
        resource_id=str(other_id),
        after={"operation": operation},
    )


async def _audit_refusal(
    session: AsyncSession,
    tenant_id: UUID,
    actor_id: UUID,
    action: str,
    other_id: UUID,
    operation: str,
) -> None:
    """Record a REFUSED attempt in its own transaction, so the refusal itself cannot erase it.

    A refusal raises, the request's transaction rolls back, and an audit row written on that
    transaction goes with it: a manager's PIN could be guessed any number of times and leave no
    trace. This row is committed on a separate connection before the error is raised. A grant needs
    no such care: it is part of the sale it authorises and commits (or not) with it.
    """
    try:
        own_factory = async_sessionmaker(session.bind, expire_on_commit=False)
        async with own_factory() as own, own.begin():
            await bind_tenant(own, tenant_id)
            await _audit(own, tenant_id, actor_id, action, other_id, operation)
    except IntegrityError:
        # The acting user is not visible to a second connection: they exist only inside the
        # caller's still-open transaction (a test fixture; never a signed-in user in production).
        # Fall back to the caller's own transaction rather than lose the row or the refusal.
        await _audit(session, tenant_id, actor_id, action, other_id, operation)


async def resolve_override(
    request: Request,
    ctx: TenantCtxDep,
    x_manager_id: Annotated[str | None, Header()] = None,
    x_manager_pin: Annotated[str | None, Header()] = None,
) -> OverrideGrant:
    """What authority does THIS request carry above the cashier's own?

    * A caller who holds ``pos:override`` themselves is already a manager: active, nobody else
      approved it.
    * Otherwise, a manager id + PIN in the headers is checked and, if good, grants override for
      this request only.
    * Neither: no grant, and the money gates apply their normal limits.

    A PIN sent by someone who already holds the permission is ignored (they do not need it, and
    it must not be a way to burn a colleague's lockout budget).
    """
    if OVERRIDE_PERMISSION in ctx.permission_codes:
        return OverrideGrant(active=True)
    if x_manager_id is None and x_manager_pin is None:
        return NO_GRANT
    if not x_manager_id or not x_manager_pin:
        raise PermissionDeniedError(_REFUSED)
    try:
        manager_id = UUID(x_manager_id)
    except ValueError:
        raise PermissionDeniedError(_REFUSED) from None
    # Approving yourself is not a second pair of eyes. This only matters when the cashier also
    # has a PIN, which a non-manager never does, but the rule belongs here and not in luck.
    if manager_id == ctx.user.id:
        raise PermissionDeniedError(_REFUSED)
    return await ManagerPinService.approve(
        ctx.session,
        ctx.tenant_id,
        cashier_id=ctx.user.id,
        manager_id=manager_id,
        pin=x_manager_pin,
        operation=f"{request.method} {request.url.path}",
    )


OverrideDep = Annotated[OverrideGrant, Depends(resolve_override)]

__all__ = [
    "NO_GRANT",
    "OVERRIDE_PERMISSION",
    "ManagerPinService",
    "OverrideDep",
    "OverrideGrant",
    "TenantContext",
    "resolve_override",
]

"""Identity services — auth, users, tenants, invitations.

Rules:
- Services own the rules; routers stay thin.
- Every service takes an AsyncSession and never commits — the request-level
  transaction (or test harness) owns commit/rollback.
- Refresh tokens are stored hashed (sha256); rotation revokes the old row.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy import select

from app.core.config import get_settings
from app.core.currency import storage_refusal
from app.core.db import bind_tenant
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.model_kit import AppendOnlyCreatedAtMixin  # noqa: F401  (convention anchor)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.identity.models import (
    Invitation,
    Location,
    RefreshToken,
    Role,
    Tenant,
    TenantUser,
    User,
    UserLocationAccess,
    Workspace,
)
from app.modules.identity.schemas import TokenPair

logger = logging.getLogger(__name__)


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
    """Persist a security event on its OWN transaction (§67).

    Delegates to the platform writer. It commits independently of the caller's
    transaction because the auth failure paths raise immediately after
    recording, which rolls the REQUEST transaction back — so
    `session.add(SecurityEvent(...))` on that transaction meant the audit row
    never survived and the §67 trail was silently empty. The platform writer
    also binds the tenant GUC for tenant-scoped rows, which `security_events`
    (FORCE RLS) requires.
    """
    from app.modules.platform.security_events import record_security_event

    await record_security_event(
        event_type,
        details=details,
        ip=ip,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
    )


async def _revoke_family_on_reuse(user_id: uuid.UUID) -> None:
    """Revoke every live refresh token for `user_id`, on its OWN transaction.

    Reuse detection is only real if the revocation outlives the request that
    detected it: `refresh` raises straight after, which rolls the REQUEST
    transaction back, so a family-revoking UPDATE issued on that transaction was
    discarded and replaying a stolen token kept working for the full token
    lifetime — the legitimate session was never killed. A short-lived session
    (the same mechanism `record_security_event` uses) makes the revocation
    durable. `refresh_tokens` is a global, RLS-exempt table (migration
    b2c3d4e5f6a7), so no tenant GUC is required.

    Never raises: a failed revocation must not turn the 401 it accompanies into
    a 500, so the failure is logged loudly instead.
    """
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


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """A real bcrypt hash used when the account does not exist.

    Login used to short-circuit on `user is None` BEFORE hashing, so a missing
    account answered measurably faster than a wrong password — a timing oracle
    that enumerates registered emails (S12). Comparing against this hash makes
    both paths cost the same bcrypt work.
    """
    return hash_password("not-a-real-password")


class AuthService:
    @staticmethod
    async def register(
        session,
        *,
        tenant_name: str | None,
        tenant_slug: str | None,
        email: str,
        password: str,
        full_name: str | None,
    ) -> tuple[User, Tenant]:
        local_part = email.split("@", 1)[0]
        # Display name ignores plus-addressing and trailing unique suffixes
        # ("hamed.adel+a12@x.com", "hamed.adel-3f2a1b@x.com" -> "Hamed Adel").
        segments = [seg for seg in re.split(r"[._-]+", local_part.split("+", 1)[0]) if seg]
        if len(segments) > 1 and re.fullmatch(r"\d+|[0-9a-f]{6,}", segments[-1]):
            segments = segments[:-1]
        display_name = " ".join(segments).strip().title() or local_part
        tenant_name = tenant_name or display_name
        full_name = full_name or display_name

        existing_email = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing_email is not None:
            raise ConflictError("email already registered")

        if tenant_slug is None:
            # Auto-derived slug from the email local part; dedupe with a short
            # random suffix on collision so minimal signup can never fail here.
            base = re.sub(r"[^a-z0-9]+", "-", local_part.lower()).strip("-")[:40] or "workspace"
            tenant_slug = base
            for _attempt in range(6):
                taken = (
                    await session.execute(select(Tenant).where(Tenant.slug == tenant_slug))
                ).scalar_one_or_none()
                if taken is None:
                    break
                tenant_slug = f"{base}-{uuid.uuid4().hex[:6]}"
            else:
                raise ConflictError("tenant slug already taken")
        else:
            existing_slug = (
                await session.execute(select(Tenant).where(Tenant.slug == tenant_slug))
            ).scalar_one_or_none()
            if existing_slug is not None:
                raise ConflictError("tenant slug already taken")

        owner_role = (
            await session.execute(select(Role).where(Role.code == "owner"))
        ).scalar_one()
        tenant = Tenant(slug=tenant_slug, name=tenant_name)
        user = User(email=email, password_hash=hash_password(password), full_name=full_name)
        session.add_all([tenant, user])
        await session.flush()
        # Bind the user GUC so the self-access policy on tenant_users allows
        # writing the owner's own membership row.
        await session.execute(
            sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)}
        )
        # We just created this tenant — binding it is legitimate and lets the
        # audit row and membership insert pass RLS.
        await bind_tenant(session, tenant.id)
        session.add(
            TenantUser(
                tenant_id=tenant.id, user_id=user.id, role_id=owner_role.id, is_default=True
            )
        )
        await session.flush()
        # A tenant is not operational just because it exists: without a
        # business calendar, an SLA policy and a subscription the new surfaces
        # have nothing to read (review N-05). Seeded here so it cannot be
        # forgotten.
        from app.modules.identity.bootstrap import seed_tenant_defaults

        await seed_tenant_defaults(session, tenant.id)
        await AuthService._audit(
            session, None, "auth.registered", "user", str(user.id), tenant_id=tenant.id
        )
        return user, tenant

    @staticmethod
    async def _assert_tenant_allows_login(
        session,
        tenant_id: uuid.UUID | None,
        *,
        user_id: uuid.UUID | None = None,
        ip: str | None = None,
    ) -> None:
        """§48: a suspended or deleted tenant cannot sign in.

        Offboarding deliberately KEEPS sign-in — the admin has to be able to
        export their data before offboarding deletes it. Enforced here rather
        than in `identity.deps` because login and refresh run before any tenant
        context exists; the `allows_api` gate in deps covers everything after.

        An unknown state fails CLOSED, consistent with the deps gate.
        """
        if tenant_id is None:
            return
        state = (
            await session.execute(
                sa.select(Tenant.lifecycle_state).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()
        policy = STATE_POLICIES.get(state) if state else None
        if policy is None or not policy.allows_login:
            await _record_security_event(
                "tenant_login_blocked",
                details={"lifecycle_state": state or "unknown"},
                ip=ip,
                actor_user_id=user_id,
            )
            raise PermissionDeniedError(
                f"workspace is {state or 'unavailable'} — sign-in is disabled"
            )

    @staticmethod
    async def login(
        session,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[TokenPair, User, uuid.UUID | None]:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        # S12: hash even when the account is missing, so the response time does
        # not reveal whether the email is registered (timing oracle).
        password_ok = verify_password(
            password, user.password_hash if user is not None else _dummy_password_hash()
        )
        if user is None or not password_ok:
            # §67: security event — login failure (no PII; domain + ip only).
            # Written on its OWN transaction: the raise below rolls the request
            # transaction back, which used to discard this row entirely.
            await _record_security_event(
                "login_failure",
                details={"email_domain": email.split("@")[-1] if "@" in email else ""},
                ip=ip,
            )
            # Unified message: "no such account" and "wrong password" are
            # indistinguishable to the caller.
            raise PermissionDeniedError("invalid credentials")

        if not user.is_active:
            await _record_security_event(
                "account_disabled_login",
                details={"email": user.email},
                ip=ip,
                actor_user_id=user.id,
            )
            raise PermissionDeniedError("account disabled")

        # Membership discovery at login: bind the user GUC so the
        # tenant_users self-access policy lets us see our own rows.
        await session.execute(
            sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)}
        )
        membership = (
            await session.execute(
                select(TenantUser)
                .where(TenantUser.user_id == user.id)
                .order_by(TenantUser.is_default.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        tenant_id = membership.tenant_id if membership else None
        await AuthService._assert_tenant_allows_login(
            session, tenant_id, user_id=user.id, ip=ip
        )
        # §146: password OK is factor one — an MFA-enabled account does NOT
        # get tokens yet; it gets a short-lived single-use challenge (Redis)
        # and must complete POST /auth/mfa/verify with a TOTP code.
        from app.core.mfa import MfaRequiredError, is_mfa_enabled, start_challenge

        if await is_mfa_enabled(session, user_id=user.id):
            challenge_id = await start_challenge(user.id, tenant_id)
            raise MfaRequiredError(challenge_id)
        pair = AuthService._issue_pair(session, user, tenant_id, user_agent=user_agent, ip=ip)
        return pair, user, tenant_id

    @staticmethod
    async def mfa_verify(
        session,
        *,
        challenge_id: str,
        code: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[TokenPair, User, uuid.UUID | None]:
        """§146 second step: a verified challenge + TOTP code mints the pair.

        The challenge is consumed atomically (GETDEL) inside
        check_challenge_code, so a replayed challenge can never mint a
        second pair; the tenant policy is re-asserted because minutes may
        have passed since the password was checked.
        """
        from app.core.mfa import check_challenge_code

        user_id, tenant_id = await check_challenge_code(
            session, challenge_id=challenge_id, code=code
        )
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise PermissionDeniedError("account not available")
        await AuthService._assert_tenant_allows_login(
            session, tenant_id, user_id=user.id, ip=ip
        )
        pair = AuthService._issue_pair(session, user, tenant_id, user_agent=user_agent, ip=ip)
        return pair, user, tenant_id

    @staticmethod
    async def refresh(
        session, *, refresh_token: str, user_agent: str | None = None, ip: str | None = None
    ) -> tuple[TokenPair, User, uuid.UUID | None]:
        token_hash = _hash_token(refresh_token)
        row = (
            await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if row is None:
            raise PermissionDeniedError("invalid refresh token")
        if row.revoked_at is not None:
            # Reuse of a revoked token → revoke the whole family (all user tokens).
            #
            # BOTH writes must outlive this request: the raise below rolls the
            # REQUEST transaction back, so a revocation or audit row issued on
            # that transaction never reached the database. Reuse detection used
            # to be a silent no-op in production for exactly this reason — the
            # old test passed only because it called the service directly,
            # outside any request transaction. `_revoke_family_on_reuse` and
            # `_record_security_event` each own a short-lived transaction.
            await _revoke_family_on_reuse(row.user_id)
            await _record_security_event(
                "token_reuse_detected",
                details={"token_id": str(row.id)},
                ip=ip,
                tenant_id=row.tenant_id,
                actor_user_id=row.user_id,
            )
            raise PermissionDeniedError("refresh token revoked")
        if row.expires_at < _now():
            raise PermissionDeniedError("refresh token expired")

        user = (await session.execute(select(User).where(User.id == row.user_id))).scalar_one()
        if not user.is_active:
            raise PermissionDeniedError("account disabled")
        await AuthService._assert_tenant_allows_login(
            session, row.tenant_id, user_id=user.id, ip=ip
        )
        row.revoked_at = _now()  # rotation
        pair = AuthService._issue_pair(session, user, row.tenant_id, user_agent=user_agent, ip=ip)
        return pair, user, row.tenant_id

    @staticmethod
    async def logout(session, *, refresh_token: str) -> None:
        token_hash = _hash_token(refresh_token)
        row = (
            await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = _now()

    @staticmethod
    async def switch_tenant(
        session, *, user: User, tenant_id: uuid.UUID, refresh_token: str
    ) -> TokenPair:
        # Security: a disabled user must never mint a fresh token family via
        # tenant switching (login/refresh both check is_active — so must this).
        if not user.is_active:
            raise PermissionDeniedError("account disabled")
        # RLS: the membership query is self-discovery via the app.user_id GUC.
        await session.execute(
            sa.text("SELECT set_config(:guc, :user_id, true)"),
            {"guc": "app.user_id", "user_id": str(user.id)},
        )
        membership = (
            await session.execute(
                select(TenantUser).where(
                    TenantUser.user_id == user.id, TenantUser.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            # §67: an authenticated user probing a tenant they do not belong to
            # is a cross-tenant access attempt. tenant_id stays None on purpose:
            # the caller has no legitimate context in the target tenant, so we
            # must not bind (and write into) that tenant's trail.
            await _record_security_event(
                "cross_tenant_access_denied",
                details={"requested_tenant_id": str(tenant_id)},
                actor_user_id=user.id,
            )
            raise PermissionDeniedError("not a member of this tenant")
        # §48: switching INTO a suspended/deleted tenant must not mint a token
        # family any more than logging into one would.
        await AuthService._assert_tenant_allows_login(session, tenant_id, user_id=user.id)
        # Ownership: only revoke a refresh token that belongs to the caller.
        old_hash = _hash_token(refresh_token)
        row = (
            await session.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == old_hash, RefreshToken.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.revoked_at = _now()
        return AuthService._issue_pair(session, user, tenant_id)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _issue_pair(
        session,
        user: User,
        tenant_id: uuid.UUID | None,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> TokenPair:
        settings = get_settings()
        claims: dict = {"tenant_id": str(tenant_id)} if tenant_id else {}
        # §146: is_platform_admin in JWT — the break-glass claim. The
        # middleware checks this to grant platform-level access (cross-tenant
        # admin, billing, audit). The claim is set from the user row, not
        # from a request parameter, so it cannot be forged.
        if getattr(user, "is_platform_admin", False):
            claims["is_platform_admin"] = True
        access = create_access_token(str(user.id), claims)
        refresh = create_refresh_token(str(user.id), claims)
        session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=_hash_token(refresh),
                tenant_id=tenant_id,
                expires_at=_now() + timedelta(seconds=settings.refresh_token_ttl_seconds),
                user_agent=user_agent,
                ip=ip,
            )
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.access_token_ttl_seconds,
        )

    @staticmethod
    async def _audit(session, actor_user_id, action, resource_type, resource_id, tenant_id=None):
        await _record_audit(
            session, tenant_id, actor_user_id, action, resource_type, resource_id
        )


class TenantService:
    @staticmethod
    async def list_for_user(session, user_id: uuid.UUID) -> list[tuple[Tenant, str | None]]:
        rows = (
            await session.execute(
                select(Tenant, Role.code)
                .join(TenantUser, TenantUser.tenant_id == Tenant.id)
                .outerjoin(Role, Role.id == TenantUser.role_id)
                .where(TenantUser.user_id == user_id, Tenant.is_active.is_(True))
            )
        ).all()
        return [(tenant, role_code) for tenant, role_code in rows]

    @staticmethod
    async def invite(
        session, *, tenant_id: uuid.UUID, email: str, role_code: str, invited_by: uuid.UUID
    ) -> Invitation:
        role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one_or_none()
        if role is None:
            raise ValidationError(f"unknown role: {role_code}")
        pending = (
            await session.execute(
                select(Invitation).where(
                    Invitation.tenant_id == tenant_id,
                    Invitation.email == email,
                    Invitation.status == "pending",
                )
            )
        ).scalar_one_or_none()
        if pending is not None:
            raise ConflictError("invitation already pending for this email")
        invitation = Invitation(
            tenant_id=tenant_id,
            email=email,
            role_id=role.id,
            invited_by_user_id=invited_by,
            token=secrets.token_urlsafe(24),
            status="pending",  # explicit: server_default is invisible in the identity map
            expires_at=_now() + timedelta(days=7),
        )
        session.add(invitation)
        return invitation

    @staticmethod
    async def revoke_invitation(
        session, *, tenant_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> Invitation:
        invitation = (
            await session.execute(
                select(Invitation).where(
                    Invitation.id == invitation_id,
                    Invitation.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise NotFoundError("invitation not found")
        if invitation.status != "pending":
            raise ConflictError("invitation is not pending")
        invitation.status = "revoked"
        return invitation

    @staticmethod
    async def accept_invitation(
        session, *, token: str, password: str, full_name: str
    ) -> tuple[User, Invitation]:
        invitation = (
            await session.execute(select(Invitation).where(Invitation.token == token))
        ).scalar_one_or_none()
        if invitation is None:
            raise NotFoundError("invitation not found")
        if invitation.status != "pending":
            raise ConflictError("invitation already used or revoked")
        if invitation.expires_at < _now():
            invitation.status = "expired"
            from app.modules.platform.models import SecurityEvent

            session.add(
                SecurityEvent(
                    event_type="invitation_expired",
                    tenant_id=invitation.tenant_id,
                    actor_user_id=None,
                    details={"email": invitation.email, "invitation_id": str(invitation.id)},
                    ip=None,
                )
            )
            raise ValidationError("invitation expired")
        existing = (
            await session.execute(select(User).where(User.email == invitation.email))
        ).scalar_one_or_none()

        async def _bind_self_guc(uid: uuid.UUID) -> None:
            # RLS: tenant_users allows the app.user_id self-discovery path —
            # bind it before reading/writing membership rows for this user.
            await session.execute(
                sa.text("SELECT set_config(:guc, :user_id, true)"),
                {"guc": "app.user_id", "user_id": str(uid)},
            )

        if existing is not None:
            user = existing
            await _bind_self_guc(user.id)
            membership_exists = (
                await session.execute(
                    select(TenantUser).where(
                        TenantUser.user_id == user.id,
                        TenantUser.tenant_id == invitation.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if membership_exists is not None:
                raise ConflictError("already a member of this tenant")
        else:
            user = User(
                email=invitation.email,
                password_hash=hash_password(password),
                full_name=full_name,
            )
            session.add(user)
            await session.flush()
            await _bind_self_guc(user.id)
        session.add(
            TenantUser(
                tenant_id=invitation.tenant_id,
                user_id=user.id,
                role_id=invitation.role_id,
                is_default=False,
            )
        )
        invitation.status = "accepted"
        invitation.accepted_at = _now()
        return user, invitation


#: ``tenants.timezone`` is ``VARCHAR(64)`` with a shape CHECK (migration
#: e3b7d2a9c4f1). Bound the same way here, so an owner gets a 400 that explains
#: itself rather than a 500 from the constraint.
_TIMEZONE_MAX_LEN = 64
_TIMEZONE_SHAPE = re.compile(r"[A-Za-z][A-Za-z0-9_/+-]*(?:/[A-Za-z0-9_+-]+)*")


def timezone_refusal(value: str | None) -> str | None:
    """Why this is not a zone the tenant may count its days in, or ``None``.

    The §47 currency precedent, with ``zoneinfo`` in place of the ISO table: a
    name the runtime cannot resolve is refused, never stored and never rounded
    down to "close enough". The database check only bounds the SHAPE (tzdata
    lives in Python, not in Postgres), so this function is where resolvability
    is actually asserted — and `analytics.timekit.resolve_timezone` re-checks it
    on every read, so a stored name that ever stops resolving fails closed
    instead of silently bucketing a Cairo shop in UTC.
    """
    name = (value or "").strip()
    if not name:
        return "a timezone is required (an IANA name such as 'Africa/Cairo')"
    if len(name) > _TIMEZONE_MAX_LEN or not _TIMEZONE_SHAPE.fullmatch(name):
        return f"'{name}' is not shaped like an IANA timezone name (e.g. 'Africa/Cairo')"
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        return f"'{name}' is not a timezone this system can resolve: {exc}"
    return None


class TenantSettingsService:
    """§47 — the commercial settings of a tenant: the one currency it trades in,
    and (§47/M10 remainder) the one timezone it counts its days in.

    Everything else in the money path *compares against* ``tenants.currency`` —
    checkout stamps it, a price tier must be quoted in it, a payment in another
    currency is refused. That makes this column the single answer to "what is
    money here", so setting it is validated rather than trusted:

    * the code has to be one this system knows how to quote (``core.currency``),
    * it has to fit the two decimal places every MONEY column actually stores,
    * and once the tenant has traded in another currency it cannot move, because
      orders keep the currency they were sold in and every money aggregate
      would quietly become a sum of two currencies.

    ``timezone`` is the same decision one axis over: analytics buckets a
    calendar DAY (§55/gap M10), and until §47/M10 remainder the only answer was
    the deployment's ``ANALYTICS_TIMEZONE``, so every merchant on the planet
    shared a midnight. It is validated the same way — refused, not converted —
    and audited the same way.
    """

    @staticmethod
    async def set_currency(
        session,
        tenant_id: uuid.UUID,
        currency: str,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> Tenant:
        code = (currency or "").strip().upper()
        refusal = storage_refusal(code)
        if refusal is not None:
            raise ValidationError(refusal)

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        previous = (tenant.currency or "").upper()
        if previous == code:
            return tenant

        # "Already traded" means an order in a currency that is not the new one.
        # A raw read rather than an import of the orders model: `orders` depends
        # on `identity`, so the reverse edge would be a module cycle, and this
        # is one EXISTS over one column (same trade customers/service.py makes
        # when it reads orders for a customer's money).
        traded = (
            await session.execute(
                sa.text(
                    "SELECT 1 FROM orders WHERE tenant_id = :tid "
                    "AND currency <> :code LIMIT 1"
                ),
                {"tid": tenant_id, "code": code},
            )
        ).first()
        if traded is not None:
            raise ConflictError(
                f"this tenant has already traded in {previous}: orders keep the "
                f"currency they were sold in, so the default cannot move to {code} "
                "out from under them"
            )

        tenant.currency = code
        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.currency_changed",
            "tenant",
            tenant.id,
            before={"currency": previous},
            after={"currency": code},
        )
        await session.flush()
        return tenant

    @staticmethod
    async def set_timezone(
        session,
        tenant_id: uuid.UUID,
        timezone: str | None,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> Tenant:
        """§47/M10 remainder: declare the calendar day this merchant counts in.

        The rule is §47's, applied to the clock: one zone per tenant, on the
        tenant's own row, refused rather than converted. Unlike the currency
        there is nothing to become inconsistent with — a day label re-derives
        from the instants on every read, so moving the zone re-reads history
        instead of falsifying it — which is why no "you already traded" guard
        exists here. An empty value clears the column, and clearing is honest:
        NULL means "the deployment zone", which is what every tenant had before
        this column existed.

        Nothing guesses a value for a tenant that never chose one; that guess is
        exactly what a merchant would read as their own numbers.
        """
        zone = (timezone or "").strip()
        if zone:
            refusal = timezone_refusal(zone)
            if refusal is not None:
                raise ValidationError(refusal)

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        previous = tenant.timezone
        if (previous or "") == zone:
            return tenant

        tenant.timezone = zone or None
        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.timezone_changed",
            "tenant",
            tenant.id,
            before={"timezone": previous},
            after={"timezone": zone or None},
        )
        await session.flush()
        return tenant


class UserService:
    @staticmethod
    async def get(session, user_id: uuid.UUID) -> User:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise NotFoundError("user not found")
        return user

    @staticmethod
    async def update_profile(session, user_id: uuid.UUID, *, full_name: str | None = None) -> User:
        user = await UserService.get(session, user_id)
        if full_name is not None:
            user.full_name = full_name
        return user

    @staticmethod
    async def set_active(session, user_id: uuid.UUID, *, is_active: bool) -> User:
        user = await UserService.get(session, user_id)
        user.is_active = is_active
        return user

    @staticmethod
    async def decode_access(token: str) -> dict:
        """Decode + sanity-check an access token (type claim)."""
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise PermissionDeniedError("wrong token type")
        return payload


# --- tenant lifecycle (spec §48) -------------------------------------------
#
# State machine — every transition is validated, never assigned directly:
#
#   provisioning ──> trial ──> active <──> past_due ──> grace
#         │            │         │  ▲          │           │
#         └──> active ─┘         │  └──────────┘           │
#                               │  (payment received)     │
#                               ▼                         ▼
#                           suspended ──> offboarding ──> deleted [terminal]
#
# `is_active` (the coarse flag) is derived from the state via
# TenantLifecycleService.is_coarse_active. The two can never disagree because
# transition() is the only writer of both.
TENANT_LIFECYCLE_STATES: tuple[str, ...] = (
    "provisioning",
    "trial",
    "active",
    "past_due",
    "grace",
    "suspended",
    "offboarding",
    "deleted",
)

TENANT_INITIAL_STATE = "provisioning"

# current state -> states it may move to. `deleted` is terminal.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "provisioning": frozenset({"trial", "active", "deleted"}),
    "trial": frozenset({"active", "past_due", "suspended", "offboarding", "deleted"}),
    "active": frozenset({"past_due", "suspended", "offboarding", "deleted"}),
    "past_due": frozenset({"active", "grace", "suspended", "offboarding", "deleted"}),
    "grace": frozenset({"active", "suspended", "offboarding", "deleted"}),
    "suspended": frozenset({"active", "offboarding", "deleted"}),
    "offboarding": frozenset({"active", "deleted"}),
    "deleted": frozenset(),
}

# States in which the tenant still operates normally — the ones where the
# coarse `is_active` flag is True.
TENANT_OPERATIONAL_STATES: frozenset[str] = frozenset(
    {"provisioning", "trial", "active", "past_due", "grace"}
)

# Entering one of these states takes capability away from the tenant, so the
# operator must say why (that reason is what the audit row preserves).
_REASON_REQUIRED: frozenset[str] = frozenset({"suspended", "offboarding", "deleted"})

# §67: a lifecycle change is a security-relevant capability change, so every
# transition also writes a security event. The capability-reducing targets get a
# distinct type so "who suspended/deleted this tenant" is a direct query;
# leaving one of them for an operational state is a reactivation.
_LIFECYCLE_SECURITY_EVENTS: dict[str, str] = {
    "suspended": "tenant_suspended",
    "offboarding": "tenant_offboarding_started",
    "deleted": "tenant_deleted",
}

# How long a tenant keeps working after payment fails, and how long after
# offboarding starts the data is retained before deletion.
GRACE_PERIOD_DAYS = 14
OFFBOARDING_RETENTION_DAYS = 30


@dataclass(frozen=True, slots=True)
class TenantCapabilityPolicy:
    """What a tenant is allowed to do in a given lifecycle state (§48).

    This is the whole point of the state machine: suspension is NOT "disable
    everything". A suspended tenant loses login / API / AI / channels /
    automation but KEEPS data access, so its admin can export everything before
    offboarding deletes it.
    """

    allows_login: bool
    allows_api: bool
    allows_ai: bool
    allows_channels: bool
    allows_automation: bool
    allows_data_access: bool


_FULL = TenantCapabilityPolicy(
    allows_login=True,
    allows_api=True,
    allows_ai=True,
    allows_channels=True,
    allows_automation=True,
    allows_data_access=True,
)
# Setup is not yet operational: the admin can sign in and use the API to
# configure the tenant, but nothing customer-facing is live.
_SETUP = TenantCapabilityPolicy(
    allows_login=True,
    allows_api=True,
    allows_ai=False,
    allows_channels=False,
    allows_automation=False,
    allows_data_access=True,
)
# Suspension: the business stops, the data stays reachable for export.
_SUSPENDED = TenantCapabilityPolicy(
    allows_login=False,
    allows_api=False,
    allows_ai=False,
    allows_channels=False,
    allows_automation=False,
    allows_data_access=True,
)
# Offboarding: read/export only — the admin signs in to take their data out.
_OFFBOARDING = TenantCapabilityPolicy(
    allows_login=True,
    allows_api=False,
    allows_ai=False,
    allows_channels=False,
    allows_automation=False,
    allows_data_access=True,
)
# Deleted: nothing at all.
_DELETED = TenantCapabilityPolicy(
    allows_login=False,
    allows_api=False,
    allows_ai=False,
    allows_channels=False,
    allows_automation=False,
    allows_data_access=False,
)

STATE_POLICIES: dict[str, TenantCapabilityPolicy] = {
    "provisioning": _SETUP,
    "trial": _FULL,
    "active": _FULL,
    "past_due": _FULL,
    "grace": _FULL,
    "suspended": _SUSPENDED,
    "offboarding": _OFFBOARDING,
    "deleted": _DELETED,
}


class TenantLifecycleService:
    """Owns the §48 tenant lifecycle: transitions, timestamps and audit."""

    @staticmethod
    async def get(session, tenant_id: uuid.UUID) -> Tenant:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise NotFoundError("tenant not found")
        return tenant

    @staticmethod
    def policy_for(state: str) -> TenantCapabilityPolicy:
        """The capability policy for a state (unknown state is a bug, not a 404)."""
        try:
            return STATE_POLICIES[state]
        except KeyError:
            raise ValidationError(f"unknown tenant lifecycle state: {state}") from None

    @staticmethod
    def is_state(tenant: Tenant, state: str) -> bool:
        """Callers ask this instead of poking `is_active`."""
        return tenant.lifecycle_state == state

    @staticmethod
    def is_coarse_active(state: str) -> bool:
        """The `is_active` value a state maps to (single source of the rule)."""
        return state in TENANT_OPERATIONAL_STATES

    @staticmethod
    async def transition(
        session,
        tenant_id: uuid.UUID,
        target: str,
        *,
        reason: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> Tenant:
        """Move a tenant to `target`, or refuse with a clear conflict.

        Validation happens BEFORE any database read, so an invalid target or a
        missing reason fails fast and is unit-testable without a session.
        """
        if target not in STATE_POLICIES:
            raise ValidationError(f"unknown tenant lifecycle state: {target}")
        if target in _REASON_REQUIRED and not (reason or "").strip():
            raise ValidationError(f"a reason is required to move a tenant to {target}")

        tenant = await TenantLifecycleService.get(session, tenant_id)
        current = tenant.lifecycle_state
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            if allowed:
                hint = f" (allowed: {', '.join(sorted(allowed))})"
            else:
                hint = " — deleted is terminal"
            raise ConflictError(
                f"cannot move a {current} tenant to {target}{hint}"
            )

        was_active = tenant.is_active
        now = _now()
        tenant.lifecycle_state = target
        tenant.is_active = TenantLifecycleService.is_coarse_active(target)
        tenant.status_reason = reason
        # Each restrictive state owns one timestamp; leaving it clears that
        # timestamp so a reactivated tenant does not look still-suspended.
        tenant.suspended_at = now if target == "suspended" else None
        tenant.grace_ends_at = (
            now + timedelta(days=GRACE_PERIOD_DAYS) if target == "grace" else None
        )
        tenant.deletion_scheduled_at = (
            now + timedelta(days=OFFBOARDING_RETENTION_DAYS)
            if target == "offboarding"
            else None
        )

        # Every transition leaves an audit row naming actor, from, to and why —
        # a lifecycle change with no trail is the failure this feature exists
        # to prevent.
        await _record_audit(
            session,
            tenant.id,
            actor_user_id,
            "tenant.lifecycle_changed",
            "tenant",
            tenant.id,
            before={"lifecycle_state": current, "is_active": was_active},
            after={
                "lifecycle_state": target,
                "is_active": tenant.is_active,
                "reason": reason,
            },
        )
        # §67: the security trail answers "who restricted this workspace" even
        # for a platform operator who never touches the tenant's business audit.
        event_type = _LIFECYCLE_SECURITY_EVENTS.get(target)
        if event_type is None and target == "active" and current in _REASON_REQUIRED:
            event_type = "tenant_reactivated"
        await _record_security_event(
            event_type or "tenant_lifecycle_changed",
            details={"from": current, "to": target, "reason": reason},
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
        )
        await session.flush()
        return tenant


class HierarchyService:
    """§151 — workspaces, locations, and location access grants.

    Tenancy is passed in by the caller (the router takes it from the request
    context) and folded into EVERY query's WHERE clause — the second,
    application-layer half of isolation. RLS (workspaces/locations by
    app.tenant_id; user_location_access by app.user_id + the owner OR-clause in
    migration f151ee151ee1) is the first half. A foreign id is a 404, never a
    leak. Services never commit; the request transaction owns it.
    """

    # --- Workspaces ---

    @staticmethod
    async def list_workspaces(session, tenant_id: uuid.UUID) -> list[Workspace]:
        rows = (
            await session.execute(
                sa.select(Workspace)
                .where(Workspace.tenant_id == tenant_id)
                .order_by(Workspace.created_at)
            )
        ).scalars()
        return list(rows)

    @staticmethod
    async def _get_workspace(session, tenant_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
        ws = (
            await session.execute(
                sa.select(Workspace).where(
                    Workspace.id == workspace_id, Workspace.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if ws is None:
            raise NotFoundError("workspace not found")
        return ws

    @staticmethod
    async def create_workspace(
        session, tenant_id: uuid.UUID, *, name: str, slug: str
    ) -> Workspace:
        dup = (
            await session.execute(
                sa.select(Workspace.id).where(
                    Workspace.tenant_id == tenant_id, Workspace.slug == slug
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise ConflictError("a workspace with this slug already exists")
        ws = Workspace(tenant_id=tenant_id, name=name, slug=slug)
        session.add(ws)
        await session.flush()
        return ws

    @staticmethod
    async def get_workspace(session, tenant_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
        return await HierarchyService._get_workspace(session, tenant_id, workspace_id)

    @staticmethod
    async def update_workspace(
        session,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        name: str | None = None,
        is_active: bool | None = None,
    ) -> Workspace:
        ws = await HierarchyService._get_workspace(session, tenant_id, workspace_id)
        if name is not None:
            ws.name = name
        if is_active is not None:
            ws.is_active = is_active
        await session.flush()
        return ws

    # --- Locations ---

    @staticmethod
    async def _get_location(session, tenant_id: uuid.UUID, location_id: uuid.UUID) -> Location:
        loc = (
            await session.execute(
                sa.select(Location).where(
                    Location.id == location_id, Location.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if loc is None:
            raise NotFoundError("location not found")
        return loc

    @staticmethod
    async def list_locations(
        session, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[Location]:
        # Ensure the workspace is in this tenant first — a foreign workspace id
        # is a 404 on the workspace, not an empty location list.
        await HierarchyService._get_workspace(session, tenant_id, workspace_id)
        rows = (
            await session.execute(
                sa.select(Location)
                .where(Location.tenant_id == tenant_id, Location.workspace_id == workspace_id)
                .order_by(Location.created_at)
            )
        ).scalars()
        return list(rows)

    @staticmethod
    async def create_location(
        session,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        name: str,
        code: str | None,
    ) -> Location:
        await HierarchyService._get_workspace(session, tenant_id, workspace_id)
        if code is not None:
            dup = (
                await session.execute(
                    sa.select(Location.id).where(
                        Location.tenant_id == tenant_id,
                        Location.workspace_id == workspace_id,
                        Location.code == code,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise ConflictError("a location with this code already exists in the workspace")
        loc = Location(
            tenant_id=tenant_id, workspace_id=workspace_id, name=name, code=code
        )
        session.add(loc)
        await session.flush()
        return loc

    @staticmethod
    async def update_location(
        session,
        tenant_id: uuid.UUID,
        location_id: uuid.UUID,
        *,
        name: str | None = None,
        code: str | None = None,
        is_active: bool | None = None,
    ) -> Location:
        loc = await HierarchyService._get_location(session, tenant_id, location_id)
        if name is not None:
            loc.name = name
        if code is not None:
            dup = (
                await session.execute(
                    sa.select(Location.id).where(
                        Location.tenant_id == tenant_id,
                        Location.workspace_id == loc.workspace_id,
                        Location.code == code,
                        Location.id != loc.id,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise ConflictError("a location with this code already exists in the workspace")
            loc.code = code
        if is_active is not None:
            loc.is_active = is_active
        await session.flush()
        return loc

    # --- Location access ---

    @staticmethod
    async def list_access(
        session, tenant_id: uuid.UUID, location_id: uuid.UUID
    ) -> list[UserLocationAccess]:
        await HierarchyService._get_location(session, tenant_id, location_id)
        rows = (
            await session.execute(
                sa.select(UserLocationAccess)
                .where(UserLocationAccess.location_id == location_id)
                .order_by(UserLocationAccess.created_at)
            )
        ).scalars()
        return list(rows)

    @staticmethod
    async def grant_access(
        session,
        tenant_id: uuid.UUID,
        location_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        role_override: str | None,
        granted_by: uuid.UUID | None = None,
    ) -> UserLocationAccess:
        # Existence + tenancy check for the location (raises 404 otherwise).
        await HierarchyService._get_location(session, tenant_id, location_id)
        # Grants may only target tenant members — otherwise a user with no
        # relationship to the tenant would appear in an access row they could
        # never resolve against.
        is_member = (
            await session.execute(
                sa.select(TenantUser.user_id).where(
                    TenantUser.user_id == user_id, TenantUser.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if is_member is None:
            raise ValidationError("user is not a member of this tenant")
        existing = (
            await session.execute(
                sa.select(UserLocationAccess).where(
                    UserLocationAccess.user_id == user_id,
                    UserLocationAccess.location_id == location_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Idempotent PUT: refresh the override/granter, do not re-insert.
            existing.role_override = role_override
            existing.granted_by = granted_by
            await session.flush()
            return existing
        # AppendOnly table: its PK is (user_id, location_id), so build directly.
        grant = UserLocationAccess(
            user_id=user_id,
            location_id=location_id,
            role_override=role_override,
            granted_by=granted_by,
        )
        session.add(grant)
        await session.flush()
        return grant

    @staticmethod
    async def revoke_access(
        session,
        tenant_id: uuid.UUID,
        location_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> None:
        await HierarchyService._get_location(session, tenant_id, location_id)
        existing = (
            await session.execute(
                sa.select(UserLocationAccess).where(
                    UserLocationAccess.user_id == user_id,
                    UserLocationAccess.location_id == location_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise NotFoundError("no such access grant")
        await session.delete(existing)
        await session.flush()

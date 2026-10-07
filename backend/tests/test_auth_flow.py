"""Auth flow tests — register / login / rotation / logout / invitations.

Runs against the real database (as sales_app, RLS on) inside a per-test
rollback transaction.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core.errors import ConflictError, PermissionDeniedError, ValidationError
from app.core.secrets import get_envelope_store
from app.core.security import decode_token
from app.modules.identity.deps import _role_permissions
from app.modules.identity.models import (
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    Role,
    TenantUser,
    User,
)
from app.modules.identity.service import (
    _REFRESH_REUSE_GRACE_SECONDS,
    AuthService,
    EmailAlreadyRegistered,
    TenantService,
    UserService,
)


async def test_register_login_refresh_logout(db):
    email = f"user-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Flow Tenant",
        tenant_slug=f"flow-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Flow Owner",
    )
    assert tenant.slug.startswith("flow-")

    pair, logged_in, tenant_id = await AuthService.login(
        db, email=email, password="strong-password-1"
    )
    assert tenant_id == tenant.id
    claims = decode_token(pair.access_token)
    assert claims["sub"] == str(user.id)
    assert claims["tenant_id"] == str(tenant.id)

    pair2, _user, tenant_id2 = await AuthService.refresh(db, refresh_token=pair.refresh_token)
    assert tenant_id2 == tenant.id
    # rotation: old refresh token must be revoked
    revoked = (
        (await db.execute(select(RefreshToken).where(RefreshToken.token_hash != "")))
        .scalars()
        .all()
    )
    assert any(r.revoked_at is not None for r in revoked)

    await AuthService.logout(db, refresh_token=pair2.refresh_token)

    tenants = await TenantService.list_for_user(db, user.id)
    assert any(t.id == tenant.id and role == "owner" for t, role in tenants)


async def test_login_wrong_password_denied(db):
    with pytest.raises(PermissionDeniedError):
        await AuthService.login(db, email="ghost@test.local", password="nope")


async def test_refresh_token_reuse_revokes_family(db, app_sessions_on_test_connection):
    """Reuse past the grace window must revoke the whole family — durably.

    `_revoke_family_on_reuse` deliberately runs on its OWN session so the
    revocation survives the rollback that follows the 401. That means it cannot
    use the `db` fixture's connection unless the app's session factory is bound
    to it, which is what `app_sessions_on_test_connection` does — see the
    fixture's docstring for why the default fails. The replayed row is
    backdated past `_REFRESH_REUSE_GRACE_SECONDS` first, because a replay
    milliseconds after rotation is the tolerated concurrent-tab race, not
    reuse (that case is pinned in test_identity_gaps).
    """
    email = f"reuse-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Reuse Tenant",
        tenant_slug=f"reuse-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Reuse Owner",
    )
    pair, _u, _t = await AuthService.login(db, email=email, password="strong-password-1")
    user_id = user.id  # captured pre-expiry: the final select runs after expire_all
    await AuthService.refresh(db, refresh_token=pair.refresh_token)
    await db.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = "
            "now() - make_interval(secs => :age) WHERE token_hash = :h"
        ),
        {
            "age": _REFRESH_REUSE_GRACE_SECONDS + 30,
            "h": hashlib.sha256(pair.refresh_token.encode()).hexdigest(),
        },
    )
    # The raw UPDATE bypasses the session's identity map: the first refresh()
    # already loaded this row, so a stale revoked_at would land the replay in
    # the grace window instead of the reuse path. Expire before re-reading.
    db.expire_all()
    # reusing the now-rotated-and-stale token must deny AND revoke the family
    with pytest.raises(PermissionDeniedError):
        await AuthService.refresh(db, refresh_token=pair.refresh_token)
    remaining = (
        (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user_id)))
        .scalars()
        .all()
    )
    assert remaining
    assert all(r.revoked_at is not None for r in remaining)


async def test_invitation_flow(db, tenant_ctx):
    invitation = await TenantService.invite(
        db,
        tenant_id=tenant_ctx.tenant_id,
        email=f"staff-{uuid.uuid4().hex[:8]}@test.local",
        role_code="staff",
        invited_by=tenant_ctx.user.id,
        # the fixture user holds the owner role; the escalation guard needs it
        inviter_role_code="owner",
    )
    user, invitation = await TenantService.accept_invitation(
        db,
        token=invitation.token,
        password="strong-password-1",
        full_name="New Staff",
    )
    membership = (
        await db.execute(
            select(TenantUser).where(
                TenantUser.user_id == user.id,
                TenantUser.tenant_id == tenant_ctx.tenant_id,
            )
        )
    ).scalar_one()
    assert membership.role_id is not None
    # An invitation-born account is born VERIFIED: the token arrived in that
    # inbox, so redeeming it proves inbox control (pre-hijack guard).
    assert user.email_verified is True

    # accepting the same token again must fail
    from app.core.errors import ValidationError

    with pytest.raises((ValidationError, ConflictError)):
        await TenantService.accept_invitation(
            db, token=invitation.token, password="x-strong-pass-1", full_name="Again"
        )


async def test_unknown_role_rejected(db, tenant_ctx):
    from app.core.errors import ValidationError

    with pytest.raises(ValidationError):
        await TenantService.invite(
            db,
            tenant_id=tenant_ctx.tenant_id,
            email=f"x-{uuid.uuid4().hex[:6]}@test.local",
            role_code="superwizard",
            invited_by=tenant_ctx.user.id,
            inviter_role_code="owner",
        )


# ---------------------------------------------- invite privilege escalation --


async def test_owner_invitation_requires_platform_admin(db, tenant_ctx):
    """An owner cannot mint another owner (audit finding 7)."""
    with pytest.raises(PermissionDeniedError):
        await TenantService.invite(
            db,
            tenant_id=tenant_ctx.tenant_id,
            email=f"peer-{uuid.uuid4().hex[:6]}@test.local",
            role_code="owner",
            invited_by=tenant_ctx.user.id,
            inviter_role_code="owner",
        )


async def test_platform_admin_may_invite_an_owner(db, tenant_ctx):
    invitation = await TenantService.invite(
        db,
        tenant_id=tenant_ctx.tenant_id,
        email=f"coowner-{uuid.uuid4().hex[:6]}@test.local",
        role_code="owner",
        invited_by=tenant_ctx.user.id,
        inviter_role_code="owner",
        inviter_is_platform_admin=True,
    )
    assert invitation.status == "pending"


@pytest.mark.parametrize(
    ("inviter", "invited", "allowed"),
    [
        ("owner", "manager", True),
        ("owner", "staff", True),
        ("manager", "staff", True),
        ("manager", "manager", False),  # strictly outrank, never equal
        ("manager", "owner", False),
        ("staff", "staff", False),
        ("staff", "manager", False),
        ("ghost", "staff", False),  # unknown inviter rank fails CLOSED
    ],
)
async def test_invite_role_hierarchy_matrix(
    db, tenant_ctx, inviter: str, invited: str, allowed: bool
):
    """The inviter must STRICTLY outrank the invited role.

    The invitation IS the grant — accept_invitation binds the invited role
    verbatim — so inviting at or above the inviter's own level was a
    self-service escalation. Unknown inviter ranks must deny (fail closed).
    """
    if not allowed:
        with pytest.raises(PermissionDeniedError):
            await TenantService.invite(
                db,
                tenant_id=tenant_ctx.tenant_id,
                email=f"h-{uuid.uuid4().hex[:6]}@test.local",
                role_code=invited,
                invited_by=tenant_ctx.user.id,
                inviter_role_code=inviter,
            )
        return
    invitation = await TenantService.invite(
        db,
        tenant_id=tenant_ctx.tenant_id,
        email=f"h-{uuid.uuid4().hex[:6]}@test.local",
        role_code=invited,
        invited_by=tenant_ctx.user.id,
        inviter_role_code=inviter,
    )
    assert invitation.status == "pending"


# -------------------------------------------------- account pre-hijack guard --


async def test_register_duplicate_email_raises_the_distinguishable_subclass(db):
    """A taken address re-queues verification and raises EmailAlreadyRegistered.

    Subclassing ConflictError keeps the historical 409 lineage for direct
    callers; the register ROUTE is what turns this into the neutral 202 (the
    409 itself was a user-enumeration oracle).
    """
    email = f"dup-{uuid.uuid4().hex[:8]}@test.local"
    user, _tenant = await AuthService.register(
        db,
        tenant_name="First Tenant",
        tenant_slug=f"dup-first-{uuid.uuid4().hex[:6]}",
        email=email,
        password="strong-password-1",
        full_name="First Owner",
    )
    with pytest.raises(EmailAlreadyRegistered):
        await AuthService.register(
            db,
            tenant_name="Second Tenant",
            tenant_slug=f"dup-second-{uuid.uuid4().hex[:6]}",
            email=email.upper(),  # case-variant: same account
            password="strong-password-1",
            full_name="Second Owner",
        )
    # nothing about the existing account changed; no second tenant was created
    reloaded = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
    assert reloaded.email == email
    # a verification token was (re-)queued for the legitimate owner
    queued = (
        (
            await db.execute(
                select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert queued, "the duplicate path must still offer the owner a way in"


async def test_email_verification_marks_the_account_verified(db):
    email = f"verify-{uuid.uuid4().hex[:8]}@test.local"
    user, _tenant = await AuthService.register(
        db,
        tenant_name="Verify Tenant",
        tenant_slug=f"verify-{uuid.uuid4().hex[:6]}",
        email=email,
        password="strong-password-1",
        full_name="Verify Owner",
    )
    await db.refresh(user)
    assert user.email_verified is False, "a fresh signup starts unverified"

    row = (
        await db.execute(
            select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
        )
    ).scalar_one()
    from app.core.secrets import get_envelope_store

    token = get_envelope_store().decrypt(row.encrypted_token).value
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()

    verified = await AuthService.verify_email(db, token=token)
    await db.refresh(user)
    assert verified.id == user.id
    assert user.email_verified is True
    assert row.consumed_at is not None

    # the link is single-use
    with pytest.raises(ValidationError, match="invalid or expired"):
        await AuthService.verify_email(db, token=token)


async def test_password_reset_heals_an_unverified_account(db):
    """A completed reset proves inbox control — the pre-hijack cure.

    An attacker who pre-registered a victim's address never verified it; the
    reset link lands in the VICTIM's inbox, so completing the reset hands the
    account back to its rightful owner AND re-opens invitation binding.
    """
    email = f"heal-{uuid.uuid4().hex[:8]}@test.local"
    user, _tenant = await AuthService.register(
        db,
        tenant_name="Heal Tenant",
        tenant_slug=f"heal-{uuid.uuid4().hex[:6]}",
        email=email,
        password="original-password-1",
        full_name="Heal Owner",
    )
    await AuthService.request_password_reset(db, email=email)
    reset_row = (
        await db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    ).scalar_one()
    from app.core.secrets import get_envelope_store

    token = get_envelope_store().decrypt(reset_row.encrypted_token).value
    await AuthService.reset_password(db, token=token, password="replacement-pass-2")
    await db.refresh(user)
    assert user.email_verified is True


async def test_accept_invitation_refuses_an_unverified_existing_account(db, tenant_ctx):
    """The invitation must not bind to an unproven account (pre-hijack).

    An account whose email was never verified may be an attacker's
    pre-registration squatting on the invitee's address; binding the invited
    role to it is exactly the audit's attack. Refuse until the address is
    proven — here the account verifies its address and the SAME invitation
    then binds, proving the refusal was the verification gate and not the
    invitation itself.
    """
    from app.core.security import hash_password

    # A bare account with NO membership, born unverified — the state a
    # pre-registration squatter leaves behind on the invitee's address.
    squatter = User(
        email=f"squat-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("squat-password-1"),
        full_name="Squat Account",
    )
    db.add(squatter)
    await db.flush()

    invitation = await TenantService.invite(
        db,
        tenant_id=tenant_ctx.tenant_id,
        email=squatter.email,
        role_code="staff",
        invited_by=tenant_ctx.user.id,
        inviter_role_code="owner",
    )
    with pytest.raises(PermissionDeniedError, match="not verified"):
        await TenantService.accept_invitation(
            db,
            token=invitation.token,
            password="strong-password-1",
            full_name="Squat Accept",
        )
    # The legitimate owner proves the inbox through the REAL verification
    # flow: a verification link is queued for the address, then consumed.
    # Writing email_verified directly is refused by the users UPDATE policy
    # (fd2026100410/0412 — possession only), exactly as a stray write in
    # production would be.
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        EmailVerificationToken(
            user_id=squatter.id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            encrypted_token=get_envelope_store().encrypt(raw_token),
            requested_at=now,
            expires_at=now + timedelta(hours=24),
            next_attempt_at=now,
        )
    )
    await db.flush()
    verified = await AuthService.verify_email(db, token=raw_token)
    assert verified.email_verified is True
    # …and the SAME invitation now binds — refused earlier ONLY by the gate.
    user, _invitation = await TenantService.accept_invitation(
        db,
        token=invitation.token,
        password="strong-password-1",
        full_name="Squat Accept",
    )
    assert user.id == squatter.id


# ------------------------------------------------------------ switch-tenant --


async def test_switch_tenant_requires_a_live_refresh_token(db, tenant_ctx):
    """Half a credential pair must not mint a fresh token family.

    A stolen 30-minute ACCESS token used to be enough: switch_tenant issued a
    new pair even with a missing or invalid refresh token — a permanent
    session from half a steal. The presented refresh token must be live,
    unexpired and owned by the caller, and it is rotated on issue.
    """
    owner = (
        await db.execute(select(User).where(User.id == tenant_ctx.user.id))
    ).scalar_one()  # refreshed: is_active is loaded from the row
    pair, _u, _t = await AuthService.login(db, email=owner.email, password="secret-password")

    for bad in ("", "not-a-real-refresh-token", None):
        with pytest.raises(PermissionDeniedError):
            await AuthService.switch_tenant(
                db, user=owner, tenant_id=tenant_ctx.tenant_id, refresh_token=bad
            )

    # the valid switch rotates the presented family and mints a new one
    new_pair = await AuthService.switch_tenant(
        db, user=owner, tenant_id=tenant_ctx.tenant_id, refresh_token=pair.refresh_token
    )
    assert new_pair.refresh_token != pair.refresh_token
    rows = (
        (await db.execute(select(RefreshToken).where(RefreshToken.user_id == owner.id)))
        .scalars()
        .all()
    )
    old_rows = [
        r for r in rows if r.token_hash == hashlib.sha256(pair.refresh_token.encode()).hexdigest()
    ]
    assert old_rows and all(r.revoked_at is not None for r in old_rows)
    new_rows = [
        r
        for r in rows
        if r.token_hash == hashlib.sha256(new_pair.refresh_token.encode()).hexdigest()
    ]
    assert new_rows and all(r.revoked_at is None for r in new_rows)


async def test_duplicate_slug_conflict(db):
    slug = f"dup-{uuid.uuid4().hex[:8]}"
    await AuthService.register(
        db,
        tenant_name="One",
        tenant_slug=slug,
        email=f"a-{uuid.uuid4().hex[:6]}@test.local",
        password="strong-password-1",
        full_name="A",
    )
    with pytest.raises(ConflictError):
        await AuthService.register(
            db,
            tenant_name="Two",
            tenant_slug=slug,
            email=f"b-{uuid.uuid4().hex[:6]}@test.local",
            password="strong-password-1",
            full_name="B",
        )


async def test_profile_update(db, tenant_ctx):
    updated = await UserService.update_profile(db, tenant_ctx.user.id, full_name="Renamed Owner")
    assert updated.full_name == "Renamed Owner"


async def test_rbac_permission_matrix(db, tenant_ctx):
    """Owner (seeded) holds settings:write; staff does not."""
    owner_perms = await _role_permissions(db, tenant_ctx.role.id)
    assert "settings:write" in owner_perms
    assert "orders:write" in owner_perms

    staff_role = (await db.execute(select(Role).where(Role.code == "staff"))).scalar_one()
    staff_perms = await _role_permissions(db, staff_role.id)
    assert "conversations:write" in staff_perms
    assert "settings:write" not in staff_perms


async def test_register_minimal_email_password_only(db):
    """Minimal signup: only email+password — tenant name/slug and display
    name derive from the email local part, slug dedupes automatically."""
    email = f"hamed.adel-{uuid.uuid4().hex[:6]}@gmail.com"
    user, tenant = await AuthService.register(
        db,
        tenant_name=None,
        tenant_slug=None,
        email=email,
        password="Probe-1234",
        full_name=None,
    )
    assert user.email == email
    assert user.full_name == "Hamed Adel"
    assert tenant.name == "Hamed Adel"
    assert tenant.slug.startswith("hamed-adel-")


async def test_register_minimal_slug_collision_dedupes(db):
    """Two minimal signups with the same email local part get distinct slugs."""
    local = f"collision-{uuid.uuid4().hex[:4]}"
    _u1, t1 = await AuthService.register(
        db,
        tenant_name=None,
        tenant_slug=None,
        email=f"{local}@test.local",
        password="Probe-1234",
        full_name=None,
    )
    u2, t2 = await AuthService.register(
        db,
        tenant_name=None,
        tenant_slug=None,
        email=f"{local}@other.local",
        password="Probe-1234",
        full_name=None,
    )
    assert t1.slug != t2.slug
    assert t2.slug.startswith(t1.slug)  # نفس الأساس + لاحقة تفريد


async def test_email_is_case_folded_end_to_end(db):
    """Ali.Hassan@Example.COM and ali.hassan@example.com are ONE account.

    Registration, login and the duplicate check all fold to lower(email),
    and the schema's unique index on lower(email) backs the service layer:
    a case-variant of an existing address is refused, never a second user
    (mixed case used to mint two accounts — confirmed experimentally).
    """
    email = f"Case.Fold-{uuid.uuid4().hex[:8]}@Example.COM"
    folded = email.lower()
    user, _tenant = await AuthService.register(
        db,
        tenant_name="Case Tenant",
        tenant_slug=f"case-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Case Owner",
    )
    assert user.email == folded

    # A case-variant of the same address is a duplicate, not a second user.
    with pytest.raises(ConflictError):
        await AuthService.register(
            db,
            tenant_name="Case Tenant 2",
            tenant_slug=f"case-{uuid.uuid4().hex[:8]}",
            email=email.upper(),
            password="strong-password-1",
            full_name="Case Owner",
        )

    # Login matches case-insensitively.
    pair, logged_in, _tenant_id = await AuthService.login(
        db,
        email=folded.upper(),
        password="strong-password-1",
        ip="127.0.0.1",
        user_agent="test",
    )
    assert logged_in.email == folded
    assert pair.access_token


# ------------------------------------- mandated closing E2E (package 1.1) ----


async def test_e2e_login_mfa_refresh_grace_replay_then_reuse_revokes_family(
    db, app_sessions_on_test_connection, monkeypatch
):
    """Package 1.1's mandated closing test — one walk through the whole
    refresh contract on the real database:

    login → MFA challenge (the account is enrolled) → verify mints pair1
    → refresh(pair1) rotates: pair1's row is revoked, pair2 is the live heir
    → replaying pair1 INSIDE the 45s grace window is the tolerated
      concurrent-tab loser: it mints pair3 and never re-stamps revoked_at
      (the window is measured from the ORIGINAL rotation, not sliding)
    → backdating pair1's revoked_at past the window and replaying again is
      genuine REUSE: refused AND every family row revoked, durably —
      `_revoke_family_on_reuse` writes on its own session (bound here to the
      test connection by app_sessions_on_test_connection) so the revocation
      survives the 401's rollback, exactly as it must in production.

    Backdating stands in for sleeping the real 45 seconds: the window's
    arithmetic is already pinned by the DB-free tests in test_identity_gaps,
    and the DB-backed walk only needs the two regimes separated in time.
    """
    from fakeredis.aioredis import FakeRedis

    from app.core import mfa
    from app.modules.identity import service as identity_service

    # One fakeredis serves BOTH incidental redis deps of the walk: the MFA
    # challenge store (app.core.mfa.get_redis) and the per-(ip,email) lockout
    # (identity.service.get_redis_or_none). Their key namespaces are disjoint.
    # Pointing the lockout here keeps the E2E hermetic — the fail-open-on-
    # outage contract is pinned separately in test_auth_lockout.py.
    redis = FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis)
    monkeypatch.setattr(identity_service, "get_redis_or_none", lambda: redis)

    # -- register, then enroll + confirm MFA: the account now challenges at login
    email = f"e2e-{uuid.uuid4().hex[:8]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="E2E Tenant",
        tenant_slug=f"e2e-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="E2E Owner",
    )
    enrolled = await mfa.enroll_mfa(db, user_id=user.id)
    backup_codes = await mfa.confirm_mfa(db, user_id=user.id, code=mfa._totp(enrolled.secret))
    assert len(backup_codes) == mfa.BACKUP_CODE_COUNT
    # captured pre-expiry: the final select runs after expire_all (a raw
    # UPDATE bypasses the identity map, and reading user.id after expiry
    # would trigger a sync-context lazy load — MissingGreenlet)
    user_id = user.id

    # -- login → MFA challenge → verify → pair1
    with pytest.raises(mfa.MfaRequiredError) as excinfo:
        await AuthService.login(db, email=email, password="strong-password-1")
    pair1, _u, tenant_id = await AuthService.mfa_verify(
        db, challenge_id=excinfo.value.challenge_id, code=mfa._totp(enrolled.secret)
    )
    assert tenant_id == tenant.id
    assert pair1.access_token and pair1.refresh_token
    pair1_hash = hashlib.sha256(pair1.refresh_token.encode()).hexdigest()

    # -- refresh: rotation. pair1's row is revoked NOW; pair2 is the heir.
    pair2, _u2, _t2 = await AuthService.refresh(db, refresh_token=pair1.refresh_token)
    assert pair2.refresh_token != pair1.refresh_token
    row1 = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == pair1_hash))
    ).scalar_one()
    assert row1.revoked_at is not None
    rotated_at = row1.revoked_at

    # -- grace replay: the SAME token milliseconds after rotation — the
    # concurrent-tab loser, not theft. Tolerated: its own pair, and the
    # window must NOT slide (no re-stamp of revoked_at).
    pair3, _u3, _t3 = await AuthService.refresh(db, refresh_token=pair1.refresh_token)
    assert pair3.refresh_token not in {pair1.refresh_token, pair2.refresh_token}
    await db.refresh(row1)
    assert row1.revoked_at == rotated_at, "the tolerated replay must not extend the window"

    # -- reuse AFTER the window: backdate pair1's revocation past the grace
    # window, expire the identity map (the raw UPDATE bypasses it), replay.
    await db.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = "
            "now() - make_interval(secs => :age) WHERE token_hash = :h"
        ),
        {"age": _REFRESH_REUSE_GRACE_SECONDS + 30, "h": pair1_hash},
    )
    db.expire_all()
    with pytest.raises(PermissionDeniedError, match="refresh token revoked"):
        await AuthService.refresh(db, refresh_token=pair1.refresh_token)

    remaining = (
        (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user_id)))
        .scalars()
        .all()
    )
    assert remaining
    assert all(r.revoked_at is not None for r in remaining), (
        "reuse past the window must revoke EVERY live token the user owns — "
        "the rotation heir and the tolerated replay's pair included"
    )

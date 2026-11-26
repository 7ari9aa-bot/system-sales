"""The two halves of "login & security" that used to be a single apology.

The security page told merchants that listing signed-in devices was not
possible. It was: every login already writes a refresh-token row carrying the
browser and the IP, and rotation leaves exactly one live row per device, so the
account can show its own sessions without a new table and without touching the
login flow.

The other half is changing the password while signed in — the recovery email was
the only path, which meant waiting for a link to do something you already have
the credential for. The current password is required, the tenant's strength
policy decides what is acceptable, and every other chain is closed, because a
password change is also the moment you want the other devices out.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.security import hash_password, verify_password
from app.modules.identity.models import RefreshToken, User
from app.modules.identity.routers.auth import router as auth_router
from app.modules.identity.services import AuthService, SignedInDeviceService
from app.modules.identity.services._common import _hash_token, _now

CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) Version/17.5 Safari/604.1"
CURRENT_PASSWORD = "secret-password"


async def _chain(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    token: str,
    user_agent: str = CHROME,
    ip: str = "203.0.113.7",
    revoked: bool = False,
    expired: bool = False,
    tenant_id: uuid.UUID | None = None,
) -> RefreshToken:
    row = RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(token),
        tenant_id=tenant_id,
        expires_at=_now() + (timedelta(days=-1) if expired else timedelta(days=14)),
        user_agent=user_agent,
        ip=ip,
        revoked_at=_now() if revoked else None,
    )
    db.add(row)
    await db.flush()
    return row


# ------------------------------------------------------------------ listing --


async def test_a_live_chain_is_listed_with_the_caller_marked(db: AsyncSession, tenant_ctx) -> None:
    await _chain(db, tenant_ctx.user.id, token="this-device-token", tenant_id=tenant_ctx.tenant_id)
    await _chain(
        db,
        tenant_ctx.user.id,
        token="phone-token",
        user_agent=IPHONE,
        ip="198.51.100.9",
        tenant_id=tenant_ctx.tenant_id,
    )

    devices = await SignedInDeviceService.list_devices(
        db, tenant_ctx.user.id, current_token_hash=_hash_token("this-device-token")
    )

    assert len(devices) == 2
    current = [device for device in devices if device["current"]]
    assert len(current) == 1
    assert current[0]["device"] == "Chrome · Windows"
    assert current[0]["ip"] == "203.0.113.7"
    assert {device["device"] for device in devices} == {"Chrome · Windows", "Safari · iPhone"}


async def test_revoked_and_expired_chains_are_not_sessions(db: AsyncSession, tenant_ctx) -> None:
    await _chain(db, tenant_ctx.user.id, token="live-token", tenant_id=tenant_ctx.tenant_id)
    await _chain(db, tenant_ctx.user.id, token="revoked-token", revoked=True)
    await _chain(db, tenant_ctx.user.id, token="expired-token", expired=True)

    devices = await SignedInDeviceService.list_devices(db, tenant_ctx.user.id)

    assert len(devices) == 1
    assert devices[0]["current"] is False  # nothing was claimed, so nothing is marked


async def test_rotation_leaves_one_row_per_device(db: AsyncSession, tenant_ctx) -> None:
    """The same browser refreshing twice must not read as two devices."""
    await _chain(
        db, tenant_ctx.user.id, token="first", revoked=True, tenant_id=tenant_ctx.tenant_id
    )
    await _chain(db, tenant_ctx.user.id, token="second", tenant_id=tenant_ctx.tenant_id)

    devices = await SignedInDeviceService.list_devices(db, tenant_ctx.user.id)

    assert len(devices) == 1


async def test_another_account_never_appears(db: AsyncSession, tenant_ctx) -> None:
    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@test.local",
        password_hash="not-a-real-hash",
        full_name="Someone Else",
    )
    db.add(other)
    await db.flush()
    await _chain(db, other.id, token="their-token")

    assert await SignedInDeviceService.list_devices(db, tenant_ctx.user.id) == []


# ----------------------------------------------------------------- revoking --


async def test_revoking_others_keeps_the_asking_device(db: AsyncSession, tenant_ctx) -> None:
    mine = await _chain(db, tenant_ctx.user.id, token="keep-me", tenant_id=tenant_ctx.tenant_id)
    other = await _chain(
        db, tenant_ctx.user.id, token="close-me", user_agent=IPHONE, ip="198.51.100.9"
    )

    revoked = await SignedInDeviceService.revoke_others(
        db, tenant_ctx.user.id, current_token_hash=_hash_token("keep-me")
    )
    await db.flush()

    assert revoked == 1
    kept = (
        await db.execute(sa.select(RefreshToken).where(RefreshToken.id == mine.id))
    ).scalar_one()
    closed = (
        await db.execute(sa.select(RefreshToken).where(RefreshToken.id == other.id))
    ).scalar_one()
    assert kept.revoked_at is None
    assert closed.revoked_at is not None


async def test_revoking_one_session_cannot_reach_another_account(
    db: AsyncSession, tenant_ctx
) -> None:
    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@test.local",
        password_hash="not-a-real-hash",
        full_name="Someone Else",
    )
    db.add(other)
    await db.flush()
    theirs = await _chain(db, other.id, token="their-token")

    with pytest.raises(NotFoundError):
        await SignedInDeviceService.revoke_one(db, tenant_ctx.user.id, theirs.id)


async def test_revoking_everything_includes_the_caller(db: AsyncSession, tenant_ctx) -> None:
    await _chain(db, tenant_ctx.user.id, token="a", tenant_id=tenant_ctx.tenant_id)
    await _chain(db, tenant_ctx.user.id, token="b", user_agent=IPHONE, ip="198.51.100.9")

    assert await SignedInDeviceService.revoke_all(db, tenant_ctx.user.id) == 2
    await db.flush()
    assert await SignedInDeviceService.list_devices(db, tenant_ctx.user.id) == []


# ---------------------------------------------------------- password change --


async def _reload(db: AsyncSession, user_id: uuid.UUID) -> User:
    await db.flush()
    return (await db.execute(sa.select(User).where(User.id == user_id))).scalar_one()


async def test_a_password_change_requires_the_current_password(
    db: AsyncSession, tenant_ctx
) -> None:
    before = tenant_ctx.user.password_hash
    with pytest.raises(ValidationError):
        await AuthService.change_password(
            db,
            user_id=tenant_ctx.user.id,
            current_password="not-the-password",
            new_password="brand-new-pass1",
        )
    assert (await _reload(db, tenant_ctx.user.id)).password_hash == before


async def test_reusing_the_same_password_is_refused(db: AsyncSession, tenant_ctx) -> None:
    with pytest.raises(ValidationError):
        await AuthService.change_password(
            db,
            user_id=tenant_ctx.user.id,
            current_password=CURRENT_PASSWORD,
            new_password=CURRENT_PASSWORD,
        )


async def test_a_weak_password_is_refused_by_the_tenant_policy(
    db: AsyncSession, tenant_ctx
) -> None:
    with pytest.raises(ValidationError):
        await AuthService.change_password(
            db,
            user_id=tenant_ctx.user.id,
            current_password=CURRENT_PASSWORD,
            new_password="short",
        )


async def test_a_password_change_signs_out_every_other_device(db: AsyncSession, tenant_ctx) -> None:
    mine = await _chain(db, tenant_ctx.user.id, token="keep-me", tenant_id=tenant_ctx.tenant_id)
    other = await _chain(
        db, tenant_ctx.user.id, token="close-me", user_agent=IPHONE, ip="198.51.100.9"
    )
    version_before = int(tenant_ctx.user.auth_version or 0)

    revoked = await AuthService.change_password(
        db,
        user_id=tenant_ctx.user.id,
        current_password=CURRENT_PASSWORD,
        new_password="brand-new-pass1",
        keep_token_hash=_hash_token("keep-me"),
    )
    await db.flush()

    user = await _reload(db, tenant_ctx.user.id)
    assert revoked == 1
    assert verify_password("brand-new-pass1", user.password_hash)
    assert not verify_password(CURRENT_PASSWORD, user.password_hash)
    # access tokens minted before this moment stop being accepted
    assert int(user.auth_version or 0) == version_before + 1

    kept = (
        await db.execute(sa.select(RefreshToken).where(RefreshToken.id == mine.id))
    ).scalar_one()
    closed = (
        await db.execute(sa.select(RefreshToken).where(RefreshToken.id == other.id))
    ).scalar_one()
    assert kept.revoked_at is None
    assert closed.revoked_at is not None


# -------------------------------------------------------------- the routes ---


def test_the_session_routes_exist_under_the_refresh_cookie_path() -> None:
    """The refresh cookie is scoped to /api/v1/auth, so "this device" only exists there."""
    routes = {
        (method, route.path)
        for route in auth_router.routes
        for method in getattr(route, "methods", set())
    }
    assert ("GET", "/auth/sessions") in routes
    assert ("POST", "/auth/sessions/revoke-others") in routes
    assert ("POST", "/auth/sessions/revoke-all") in routes
    assert ("POST", "/auth/sessions/{session_id}/revoke") in routes
    assert ("POST", "/auth/password/change") in routes


def test_the_password_change_hash_matches_the_stored_format() -> None:
    """Guards the one assumption the form makes: the stored hash is bcrypt."""
    stored = hash_password("brand-new-pass1")
    assert stored != "brand-new-pass1"
    assert verify_password("brand-new-pass1", stored)
    assert not verify_password("brand-new-pass2", stored)

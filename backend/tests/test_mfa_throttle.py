"""§146 step-up throttling — confirm/disable get the same abuse bound as the
login challenge (5 wrong codes → lock), the counter resets on success and on
a fresh enrollment, and the Redis-backed state fails OPEN by design (the code
check itself still enforces correctness; a cache outage must not brick
disabling MFA).

DB-backed via the conftest fixtures (skips locally without
DATABASE_URL_APP_ADMIN). The §67 events the throttling emits are spied on —
their persistence is pinned in test_mfa_login_flow / test_security_events.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fakeredis.aioredis import FakeRedis

from app.core import mfa
from app.core.errors import PermissionDeniedError, RateLimitExceededError


@pytest.fixture
async def redis_client() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def spy_events(monkeypatch) -> list[dict]:
    """Capture the §67 events mfa emits instead of writing rows."""
    calls: list[dict] = []

    async def _spy(event_type, *, details=None, ip=None, tenant_id=None, actor_user_id=None):
        calls.append(
            {
                "event_type": event_type,
                "details": details,
                "ip": ip,
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
            }
        )

    monkeypatch.setattr(mfa, "_emit_security_event", _spy)
    return calls


async def _enroll(session, user_id) -> str:
    enrolled = await mfa.enroll_mfa(session, user_id=user_id)
    return enrolled.secret


class TestConfirmThrottle:
    async def test_five_wrong_codes_lock_confirmation(
        self, tenant_ctx, redis_client, monkeypatch, spy_events
    ):
        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        db = tenant_ctx.session
        secret = await _enroll(db, tenant_ctx.user.id)
        wrong = mfa._totp(secret, timestamp=1)

        for _ in range(mfa.STEPUP_MAX_FAILURES - 1):
            with pytest.raises(PermissionDeniedError):
                await mfa.confirm_mfa(
                    db, user_id=tenant_ctx.user.id, code=wrong
                )
        # The ceiling attempt itself locks...
        with pytest.raises(RateLimitExceededError):
            await mfa.confirm_mfa(db, user_id=tenant_ctx.user.id, code=wrong)
        assert spy_events[-1]["event_type"] == "mfa_confirm_locked"
        # ...and afterwards even the CORRECT code is refused until the
        # lock window passes (a fresh enrollment restarts, see below).
        with pytest.raises(RateLimitExceededError):
            await mfa.confirm_mfa(
                db, user_id=tenant_ctx.user.id, code=mfa._totp(secret)
            )

        # Each wrong code was audited, coarse only.
        assert [c["event_type"] for c in spy_events].count(
            "mfa_confirm_failure"
        ) == mfa.STEPUP_MAX_FAILURES - 1

    async def test_success_resets_the_counter(
        self, tenant_ctx, redis_client, monkeypatch, spy_events
    ):
        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        db = tenant_ctx.session
        secret = await _enroll(db, tenant_ctx.user.id)
        wrong = mfa._totp(secret, timestamp=1)

        with pytest.raises(PermissionDeniedError):
            await mfa.confirm_mfa(db, user_id=tenant_ctx.user.id, code=wrong)
        codes = await mfa.confirm_mfa(
            db, user_id=tenant_ctx.user.id, code=mfa._totp(secret)
        )
        assert len(codes) == mfa.BACKUP_CODE_COUNT
        assert await mfa._stepup_attempts(tenant_ctx.user.id, "confirm", redis=redis_client) == 0

    async def test_fresh_enrollment_restarts_a_locked_window(
        self, tenant_ctx, redis_client, monkeypatch, spy_events
    ):
        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        db = tenant_ctx.session
        secret = await _enroll(db, tenant_ctx.user.id)
        wrong = mfa._totp(secret, timestamp=1)
        for _ in range(mfa.STEPUP_MAX_FAILURES - 1):
            with pytest.raises(PermissionDeniedError):
                await mfa.confirm_mfa(db, user_id=tenant_ctx.user.id, code=wrong)
        with pytest.raises(RateLimitExceededError):
            await mfa.confirm_mfa(db, user_id=tenant_ctx.user.id, code=wrong)
        with pytest.raises(RateLimitExceededError):
            await mfa.confirm_mfa(
                db, user_id=tenant_ctx.user.id, code=mfa._totp(secret)
            )

        # Re-enroll (password-gated at the route) mints a NEW secret and
        # clears the counter — a locked user is not locked out forever.
        new_secret = await _enroll(db, tenant_ctx.user.id)
        assert new_secret != secret
        codes = await mfa.confirm_mfa(
            db, user_id=tenant_ctx.user.id, code=mfa._totp(new_secret)
        )
        assert len(codes) == mfa.BACKUP_CODE_COUNT


class TestDisableThrottle:
    async def test_five_wrong_codes_lock_disable(
        self, tenant_ctx, redis_client, monkeypatch, spy_events
    ):
        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        db = tenant_ctx.session
        secret = await _enroll(db, tenant_ctx.user.id)
        await mfa.confirm_mfa(
            db, user_id=tenant_ctx.user.id, code=mfa._totp(secret)
        )
        wrong = mfa._totp(secret, timestamp=1)

        for _ in range(mfa.STEPUP_MAX_FAILURES - 1):
            with pytest.raises(PermissionDeniedError):
                await mfa.disable_mfa(
                    db, user_id=tenant_ctx.user.id, code=wrong
                )
        with pytest.raises(RateLimitExceededError):
            await mfa.disable_mfa(
                db, user_id=tenant_ctx.user.id, code=wrong
            )
        with pytest.raises(RateLimitExceededError):
            await mfa.disable_mfa(
                db, user_id=tenant_ctx.user.id, code=mfa._totp(secret)
            )
        # MFA is still ON — locking the throttle must not disable it.
        assert await mfa.is_mfa_enabled(db, user_id=tenant_ctx.user.id)
        assert [c["event_type"] for c in spy_events].count(
            "mfa_disable_failure"
        ) == mfa.STEPUP_MAX_FAILURES - 1

    async def test_backup_code_path_is_not_blocked_by_totp_replay(
        self, tenant_ctx, redis_client, monkeypatch, spy_events
    ):
        """A replayed TOTP counter blocks the TOTP surface only — the backup
        code (a different factor, one-time by construction) still disables."""
        import time

        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        db = tenant_ctx.session
        secret = await _enroll(db, tenant_ctx.user.id)
        codes = await mfa.confirm_mfa(
            db, user_id=tenant_ctx.user.id, code=mfa._totp(secret)
        )

        # Burn the current window like a prior login would.
        counter = int(time.time()) // 30
        assert await mfa.claim_totp_counter(tenant_ctx.user.id, counter)

        await mfa.disable_mfa(
            db, user_id=tenant_ctx.user.id, backup_code=codes[0]
        )
        assert not await mfa.is_mfa_enabled(db, user_id=tenant_ctx.user.id)


class TestDocumentedFailOpen:
    async def test_throttle_fails_open_without_redis(
        self, tenant_ctx, monkeypatch, spy_events
    ):
        """Redis down: no counting, no lock — but the code check still
        enforces correctness (correct code confirms, wrong code rejects)."""

        def _boom():
            raise ConnectionError("redis down")

        monkeypatch.setattr("app.core.mfa.get_redis", _boom)
        db = tenant_ctx.session
        secret = await _enroll(db, tenant_ctx.user.id)

        with pytest.raises(PermissionDeniedError):
            await mfa.confirm_mfa(
                db, user_id=tenant_ctx.user.id, code=mfa._totp(secret, timestamp=1)
            )
        codes = await mfa.confirm_mfa(
            db, user_id=tenant_ctx.user.id, code=mfa._totp(secret)
        )
        assert len(codes) == mfa.BACKUP_CODE_COUNT

    async def test_replay_claim_fails_open_without_redis(
        self, tenant_ctx, monkeypatch, spy_events
    ):
        """Documented fail-open: with Redis unreachable the claim reports
        first-use so verification proceeds (the challenge itself already
        fails closed — it lives in Redis)."""

        def _boom():
            raise ConnectionError("redis down")

        monkeypatch.setattr("app.core.mfa.get_redis", _boom)
        uid = uuid.uuid4()
        assert await mfa.claim_totp_counter(uid, 12345) is True

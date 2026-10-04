"""§146 MFA login flow — TOTP vectors, Redis challenges (fakeredis), and the
DB-backed end-to-end login challenge (CI, real Postgres).

Non-DB classes run anywhere; DB classes skip without DATABASE_URL_APP_ADMIN.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fakeredis.aioredis import FakeRedis

from app.core import mfa
from app.core.errors import PermissionDeniedError


@pytest.fixture
async def redis_client() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


class TestTotp:
    """RFC 6238 correctness — the classic SHA1 test secret/timestamps."""

    # "12345678901234567890" in base32 (RFC 6238 appendix B).
    SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

    def test_rfc6238_vector_t59(self):
        # RFC 6238 T=59s → 94287082 (8 digits); we use 6 → 287082.
        assert mfa._totp(self.SECRET, timestamp=59) == "287082"

    def test_verify_accepts_current_and_drift_window(self):
        code = mfa._totp(self.SECRET, timestamp=1000)
        assert mfa.verify_totp(self.SECRET, code, timestamp=1000)
        # ±1 step (30s) clock drift is accepted.
        assert mfa.verify_totp(self.SECRET, code, timestamp=1000 + 30)
        assert mfa.verify_totp(self.SECRET, code, timestamp=1000 - 30)

    def test_verify_rejects_far_future_and_garbage(self):
        code = mfa._totp(self.SECRET, timestamp=1000)
        assert not mfa.verify_totp(self.SECRET, code, timestamp=1000 + 120)
        assert not mfa.verify_totp(self.SECRET, "not-digits", timestamp=1000)
        assert not mfa.verify_totp(self.SECRET, "", timestamp=1000)

    def test_backup_code_hashing_is_stable_and_normalized(self):
        assert mfa._hash_backup_code(" ab12 ") == mfa._hash_backup_code("ab12")


class TestChallengeStore:
    """Redis challenge mechanics — single-use, failure counting, lock."""

    async def test_challenge_round_trip_and_single_use(self, redis_client):
        import uuid

        uid, tid = uuid.uuid4(), uuid.uuid4()
        cid = await mfa.start_challenge(uid, tid, redis=redis_client)
        payload = await mfa.load_challenge(cid, redis=redis_client)
        # start_challenge snapshots auth_version (default 0) so a password
        # reset mid-challenge can invalidate it — same contract as the stream
        # gate's revocation check.
        assert payload == {
            "user_id": str(uid),
            "tenant_id": str(tid),
            "auth_version": 0,
        }
        consumed = await mfa.consume_challenge(cid, redis=redis_client)
        assert consumed is not None
        # GETDEL: the second consume gets nothing — no double token minting.
        assert await mfa.consume_challenge(cid, redis=redis_client) is None

    async def test_unknown_challenge_consumes_to_none(self, redis_client):
        assert await mfa.consume_challenge("nope", redis=redis_client) is None
        assert await mfa.load_challenge("nope", redis=redis_client) is None

    async def test_failure_counter_and_drop(self, redis_client):
        import uuid

        cid = await mfa.start_challenge(uuid.uuid4(), None, redis=redis_client)
        assert await mfa.record_challenge_failure(cid, redis=redis_client) == 1
        assert await mfa.record_challenge_failure(cid, redis=redis_client) == 2
        assert await mfa.challenge_failures(cid, redis=redis_client) == 2
        await mfa.drop_challenge(cid, redis=redis_client)
        assert await mfa.load_challenge(cid, redis=redis_client) is None
        assert await mfa.challenge_failures(cid, redis=redis_client) == 0

    async def test_challenge_has_ttl(self, redis_client):
        import uuid

        cid = await mfa.start_challenge(uuid.uuid4(), None, redis=redis_client)
        ttl = await redis_client.ttl(mfa._challenge_key(cid))
        assert 0 < ttl <= mfa.CHALLENGE_TTL_SECONDS


class TestMfaLoginFlow:
    """End-to-end: enroll → confirm → login challenge → verify → tokens.

    DB-backed via the conftest fixtures (skips locally without
    DATABASE_URL_APP_ADMIN; CI runs it on real Postgres). Redis is faked —
    CI has no Redis service, and the fakes still exercise the real
    single-use/TTL semantics.
    """

    async def _enroll_and_confirm(self, session, user_id):
        enrolled = await mfa.enroll_mfa(session, user_id=user_id)
        code = mfa._totp(enrolled.secret)
        backup_codes = await mfa.confirm_mfa(session, user_id=user_id, code=code)
        assert len(backup_codes) == mfa.BACKUP_CODE_COUNT
        return enrolled.secret, backup_codes

    async def test_login_challenges_then_verify_issues_tokens(
        self, tenant_ctx, redis_client, monkeypatch
    ):
        from app.modules.identity.service import AuthService

        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        db = tenant_ctx.session
        secret, _codes = await self._enroll_and_confirm(db, tenant_ctx.user.id)

        with pytest.raises(mfa.MfaRequiredError) as excinfo:
            await AuthService.login(
                db, email=tenant_ctx.user.email, password="secret-password"
            )
        challenge_id = excinfo.value.challenge_id

        pair, user, tenant_id = await AuthService.mfa_verify(
            db, challenge_id=challenge_id, code=mfa._totp(secret)
        )
        assert pair.access_token and pair.refresh_token
        assert user.id == tenant_ctx.user.id
        assert tenant_id == tenant_ctx.tenant.id

        # The challenge is consumed — a replay must not mint a second pair.
        with pytest.raises(PermissionDeniedError):
            await AuthService.mfa_verify(
                db, challenge_id=challenge_id, code=mfa._totp(secret)
            )

    async def test_login_without_mfa_still_issues_tokens_directly(
        self, tenant_ctx, redis_client, monkeypatch
    ):
        from app.modules.identity.service import AuthService

        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        pair, user, _ = await AuthService.login(
            tenant_ctx.session, email=tenant_ctx.user.email, password="secret-password"
        )
        assert pair.access_token and user.id == tenant_ctx.user.id

    async def test_five_wrong_codes_lock_the_challenge(
        self, tenant_ctx, redis_client, monkeypatch
    ):
        from app.modules.identity.service import AuthService

        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        db = tenant_ctx.session
        secret, _ = await self._enroll_and_confirm(db, tenant_ctx.user.id)
        # A code from a far-away window is guaranteed wrong.
        wrong = mfa._totp(secret, timestamp=1)

        with pytest.raises(mfa.MfaRequiredError) as excinfo:
            await AuthService.login(
                db, email=tenant_ctx.user.email, password="secret-password"
            )
        challenge_id = excinfo.value.challenge_id

        for _ in range(mfa.CHALLENGE_MAX_FAILURES):
            with pytest.raises(PermissionDeniedError):
                await AuthService.mfa_verify(db, challenge_id=challenge_id, code=wrong)
        # Locked: even the CORRECT code is refused now.
        with pytest.raises(PermissionDeniedError):
            await AuthService.mfa_verify(
                db, challenge_id=challenge_id, code=mfa._totp(secret)
            )

    async def test_disable_with_backup_code_is_one_time(
        self, tenant_ctx, redis_client, monkeypatch
    ):
        monkeypatch.setattr("app.core.mfa.get_redis", lambda: redis_client)
        db = tenant_ctx.session
        _secret, codes = await self._enroll_and_confirm(db, tenant_ctx.user.id)

        await mfa.disable_mfa(db, user_id=tenant_ctx.user.id, backup_code=codes[0])
        assert not await mfa.is_mfa_enabled(db, user_id=tenant_ctx.user.id)

    async def test_enroll_over_enabled_conflicts(self, tenant_ctx):
        db = tenant_ctx.session
        await self._enroll_and_confirm(db, tenant_ctx.user.id)
        from app.core.errors import ConflictError

        with pytest.raises(ConflictError):
            await mfa.enroll_mfa(db, user_id=tenant_ctx.user.id)

"""§147 break-glass on Redis — atomic single-use capabilities + §59 durability.

The store tests run against fakeredis anywhere (event recording is switched
off there — the emission contract is pinned in test_security_events.py); the
issue/use path is DB-backed (conftest fixtures — skips locally without
DATABASE_URL_APP_ADMIN, runs in CI on real Postgres) with the platform
writer bound to the test connection so its own-transaction rows are visible
and rolled back with the test.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select

from app.core import break_glass as bg
from app.modules.platform.models import SecurityEvent


@pytest.fixture
async def redis_client() -> AsyncIterator[FakeRedis]:
    client = FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def _seed_capability(
    redis_client, *, tenant_id, user_id, action="tenant_status_change"
) -> str:
    """Store a capability exactly the way break_glass() does (no DB needed)."""
    token = "test-cap-" + uuid.uuid4().hex[:16]
    payload = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "action": action,
            "resource_type": "tenant",
            "resource_id": str(tenant_id),
            "reason": "seeded for the capability-store tests",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
    )
    await redis_client.set(bg._capability_key(token), payload, ex=bg.CAPABILITY_TTL_MINUTES * 60)
    return token


class TestCapabilityStore:
    """Pure Redis semantics — no database involved (events off)."""

    async def test_valid_capability_validates_once(self, redis_client):
        tid, uid = uuid.uuid4(), uuid.uuid4()
        token = await _seed_capability(redis_client, tenant_id=tid, user_id=uid)
        assert await bg.validate_capability(
            token,
            tenant_id=tid,
            user_id=uid,
            action="tenant_status_change",
            redis=redis_client,
            record_events=False,
        )
        # GETDEL: the second presentation finds nothing — one-shot enforced
        # atomically, race-safe across API instances.
        assert not await bg.validate_capability(
            token,
            tenant_id=tid,
            user_id=uid,
            action="tenant_status_change",
            redis=redis_client,
            record_events=False,
        )

    async def test_mismatched_action_burns_the_token(self, redis_client):
        tid, uid = uuid.uuid4(), uuid.uuid4()
        token = await _seed_capability(redis_client, tenant_id=tid, user_id=uid)
        assert not await bg.validate_capability(
            token,
            tenant_id=tid,
            user_id=uid,
            action="different_action",
            redis=redis_client,
            record_events=False,
        )
        # Burned on presentation: it cannot be retried with the right action.
        assert not await bg.validate_capability(
            token,
            tenant_id=tid,
            user_id=uid,
            action="tenant_status_change",
            redis=redis_client,
            record_events=False,
        )

    async def test_wrong_tenant_or_user_fails(self, redis_client):
        tid, uid = uuid.uuid4(), uuid.uuid4()
        token = await _seed_capability(redis_client, tenant_id=tid, user_id=uid)
        assert not await bg.validate_capability(
            token,
            tenant_id=uuid.uuid4(),
            user_id=uid,
            action="tenant_status_change",
            redis=redis_client,
            record_events=False,
        )

    async def test_unknown_token_fails(self, redis_client):
        assert not await bg.validate_capability(
            "never-issued",
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action="tenant_status_change",
            redis=redis_client,
            record_events=False,
        )

    async def test_capability_carries_a_ttl(self, redis_client):
        token = await _seed_capability(redis_client, tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
        ttl = await redis_client.ttl(bg._capability_key(token))
        assert 0 < ttl <= bg.CAPABILITY_TTL_MINUTES * 60

    async def test_failed_peek_does_not_consume(self, redis_client):
        tid, uid = uuid.uuid4(), uuid.uuid4()
        token = await _seed_capability(redis_client, tenant_id=tid, user_id=uid)
        assert not await bg.peek_capability(
            token,
            tenant_id=uuid.uuid4(),
            user_id=uid,
            action="tenant_status_change",
            redis=redis_client,
            record_events=False,
        )
        # The pre-flight is read-only: the token still validates afterwards.
        assert await bg.peek_capability(
            token,
            tenant_id=tid,
            user_id=uid,
            action="tenant_status_change",
            redis=redis_client,
            record_events=False,
        )


class TestBreakGlassIssuePath:
    """Full break_glass() — DB-backed: audit row + security event + token."""

    async def test_issue_records_audit_and_security_event(
        self, tenant_ctx, redis_client, app_sessions_on_test_connection
    ):
        import sqlalchemy as sa

        from app.modules.platform.models import AuditLog

        db = tenant_ctx.session
        token = await bg.break_glass(
            db,
            tenant_id=tenant_ctx.tenant.id,
            user_id=tenant_ctx.user.id,
            action="tenant_status_change",
            resource_type="tenant",
            resource_id=str(tenant_ctx.tenant.id),
            reason="customer asked us to suspend billing fraud",
            redis=redis_client,
        )
        assert token

        audit = (
            await db.execute(
                sa.select(AuditLog).where(
                    AuditLog.tenant_id == tenant_ctx.tenant.id,
                    AuditLog.action == "break_glass",
                )
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.actor_user_id == tenant_ctx.user.id

        event = (
            await db.execute(
                sa.select(SecurityEvent).where(
                    SecurityEvent.event_type == "break_glass",
                    SecurityEvent.tenant_id == tenant_ctx.tenant.id,
                )
            )
        ).scalar_one_or_none()
        assert event is not None
        assert event.details["action"] == "tenant_status_change"

        # The issued token elevates exactly once, for the scoped action.
        assert await bg.validate_capability(
            token,
            tenant_id=tenant_ctx.tenant.id,
            user_id=tenant_ctx.user.id,
            action="tenant_status_change",
            redis=redis_client,
        )
        assert not await bg.validate_capability(
            token,
            tenant_id=tenant_ctx.tenant.id,
            user_id=tenant_ctx.user.id,
            action="tenant_status_change",
            redis=redis_client,
        )

    async def test_short_reason_rejected(self, tenant_ctx, redis_client):
        with pytest.raises(ValueError, match="reason"):
            await bg.break_glass(
                tenant_ctx.session,
                tenant_id=tenant_ctx.tenant.id,
                user_id=tenant_ctx.user.id,
                action="tenant_status_change",
                resource_type="tenant",
                resource_id="x",
                reason="too short",
                redis=redis_client,
            )

    async def test_atomic_consumption_leaves_the_three_events(
        self, tenant_ctx, redis_client, app_sessions_on_test_connection
    ):
        """§147 closing scenario: mint → first use succeeds → an immediate
        second presentation is rejected — and all THREE auditable events
        (mint / use / reject) exist, none carrying the token itself."""
        db = tenant_ctx.session
        token = await bg.break_glass(
            db,
            tenant_id=tenant_ctx.tenant.id,
            user_id=tenant_ctx.user.id,
            action="tenant_status_change",
            resource_type="tenant",
            resource_id=str(tenant_ctx.tenant.id),
            reason="incident 4711 — freeze fraudulent workspace",
            redis=redis_client,
        )

        # First presentation: the capability elevates exactly once.
        assert await bg.validate_capability(
            token,
            tenant_id=tenant_ctx.tenant.id,
            user_id=tenant_ctx.user.id,
            action="tenant_status_change",
            redis=redis_client,
        )
        # Immediate second presentation: atomically rejected (GETDEL).
        assert not await bg.validate_capability(
            token,
            tenant_id=tenant_ctx.tenant.id,
            user_id=tenant_ctx.user.id,
            action="tenant_status_change",
            redis=redis_client,
        )

        rows = (
            (
                await db.execute(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.event_type.in_(
                            ["break_glass", "break_glass_use", "break_glass_reject"]
                        )
                    )
                    .where(SecurityEvent.tenant_id == tenant_ctx.tenant.id)
                )
            )
            .scalars()
            .all()
        )
        # Same-transaction rows share created_at, so assert on the multiset.
        assert sorted(r.event_type for r in rows) == [
            "break_glass",
            "break_glass_reject",
            "break_glass_use",
        ]
        assert all(r.actor_user_id == tenant_ctx.user.id for r in rows)
        # Secrets hygiene: the capability token never lands in the trail.
        blob = json.dumps([r.details for r in rows])
        assert token not in blob
        use_row = next(r for r in rows if r.event_type == "break_glass_use")
        assert use_row.details["action"] == "tenant_status_change"

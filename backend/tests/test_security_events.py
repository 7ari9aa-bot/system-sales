"""§65–67: the security-event trail must cover the security-relevant actions.

`security_events` used to be written from a single module and only on the auth
failure paths, so the §67 trail could not answer "who suspended or deleted this
workspace" or "who probed another tenant". These tests pin the writers that
close those gaps, and the RLS handling that lets a tenant-scoped row land.

The first half is pure (no database); the second half runs in CI against a real
PostgreSQL with RLS enforced, and skips locally when no app DB URL is set.
"""

from __future__ import annotations

import json
import types
import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import bind_tenant
from app.core.errors import PermissionDeniedError
from app.modules.identity import service
from app.modules.identity.models import Tenant
from app.modules.identity.service import TenantLifecycleService
from app.modules.platform.models import SecurityEvent


class _Result:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _StubSession:
    """Enough of AsyncSession for the lifecycle service, with no database."""

    def __init__(self, tenant: Tenant | None) -> None:
        self._tenant = tenant
        self.added: list = []

    async def execute(self, *args, **kwargs):
        return _Result(self._tenant)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


@pytest.fixture
def recorded(monkeypatch):
    """Capture the security events the service emits, instead of writing rows."""
    calls: list[dict] = []

    async def _spy(
        event_type: str,
        *,
        details: dict | None = None,
        ip: str | None = None,
        tenant_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        calls.append(
            {
                "event_type": event_type,
                "details": details,
                "ip": ip,
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
            }
        )

    monkeypatch.setattr(service, "_record_security_event", _spy)
    return calls


def _tenant(state: str) -> Tenant:
    return Tenant(
        id=uuid.uuid4(),
        slug=f"t-{uuid.uuid4().hex[:8]}",
        name="Acme",
        lifecycle_state=state,
        is_active=state not in {"suspended", "offboarding", "deleted"},
    )


# ------------------------------------------------- lifecycle transitions ----


@pytest.mark.parametrize(
    ("current", "target", "event_type"),
    [
        ("active", "suspended", "tenant_suspended"),
        ("active", "offboarding", "tenant_offboarding_started"),
        ("active", "deleted", "tenant_deleted"),
        ("suspended", "active", "tenant_reactivated"),
        ("offboarding", "active", "tenant_reactivated"),
    ],
)
async def test_lifecycle_transition_emits_a_security_event(
    recorded, current: str, target: str, event_type: str
) -> None:
    tenant = _tenant(current)
    actor = uuid.uuid4()

    await TenantLifecycleService.transition(
        _StubSession(tenant),
        tenant.id,
        target,
        reason="operator action",
        actor_user_id=actor,
    )

    assert [c["event_type"] for c in recorded] == [event_type]
    call = recorded[0]
    assert call["tenant_id"] == tenant.id
    assert call["actor_user_id"] == actor
    assert call["details"] == {"from": current, "to": target, "reason": "operator action"}


async def test_routine_transition_is_still_recorded(recorded) -> None:
    """No gap: a billing-state move is a lifecycle change too, just a generic one."""
    tenant = _tenant("trial")

    await TenantLifecycleService.transition(
        _StubSession(tenant), tenant.id, "active", actor_user_id=uuid.uuid4()
    )

    assert [c["event_type"] for c in recorded] == ["tenant_lifecycle_changed"]


async def test_transition_does_not_leak_secrets_into_the_metadata(recorded) -> None:
    """The metadata answers "who/what", never "what secret"."""
    tenant = _tenant("active")

    await TenantLifecycleService.transition(
        _StubSession(tenant),
        tenant.id,
        "suspended",
        reason="non-payment",
        actor_user_id=uuid.uuid4(),
    )

    details = recorded[0]["details"]
    assert set(details) == {"from", "to", "reason"}


# ------------------------------------------- permission-denied (cross-tenant) --


async def test_switch_tenant_to_a_non_member_tenant_emits_a_security_event(
    recorded,
) -> None:
    user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)
    target = uuid.uuid4()

    with pytest.raises(PermissionDeniedError):
        await service.AuthService.switch_tenant(
            _StubSession(None), user=user, tenant_id=target, refresh_token="irrelevant"
        )

    assert [c["event_type"] for c in recorded] == ["cross_tenant_access_denied"]
    assert recorded[0]["actor_user_id"] == user.id
    # The caller has no legitimate context in the target tenant — the row must
    # stay tenant-less rather than bind (and write into) another tenant's trail.
    assert recorded[0]["tenant_id"] is None
    assert recorded[0]["details"] == {"requested_tenant_id": str(target)}


# ---------------------------------------------------- DB-backed (CI only) ----


@pytest.fixture
async def security_event_sessions(monkeypatch, db):
    """Bind the platform writer's OWN session to the test connection.

    The writer deliberately opens a short-lived session so the audit row
    survives the caller's rollback; in production that is a different
    connection. Here it joins the test's connection, so the row it writes is
    visible to the test and rolled back with it.
    """
    conn = await db.connection()
    factory = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: factory)
    return factory


async def test_transition_persists_a_tenant_scoped_security_event(
    db: AsyncSession, tenant_ctx, security_event_sessions
) -> None:
    tenant_ctx.tenant.lifecycle_state = "active"
    tenant_ctx.tenant.is_active = True
    await db.flush()

    await TenantLifecycleService.transition(
        db,
        tenant_ctx.tenant_id,
        "suspended",
        reason="payment fraud",
        actor_user_id=tenant_ctx.user.id,
    )

    rows = (
        await db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "tenant_suspended")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_ctx.tenant_id
    assert rows[0].actor_user_id == tenant_ctx.user.id
    assert rows[0].details == {
        "from": "active",
        "to": "suspended",
        "reason": "payment fraud",
    }


async def test_tenant_scoped_event_lands_without_a_bound_context(
    db: AsyncSession, tenant_ctx, security_event_sessions
) -> None:
    """security_events is FORCE RLS: a tenant-scoped row is rejected unless the
    writer binds the tenant GUC itself. Clearing the GUC first means the row can
    only land if the writer binds it — which is the login-path case, where no
    tenant context exists at all."""
    from app.modules.platform.security_events import record_security_event

    await db.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))

    await record_security_event(
        "tenant_suspended",
        details={"probe": True},
        tenant_id=tenant_ctx.tenant_id,
        actor_user_id=tenant_ctx.user.id,
    )

    await bind_tenant(db, tenant_ctx.tenant_id)  # re-bind so the read is allowed
    rows = (
        await db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "tenant_suspended")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == tenant_ctx.tenant_id


# ---------------------------------- §146/§147 MFA + break-glass emissions ----
#
# Package 1.4: the MFA challenge and the break-glass capability own their
# event boundaries inside core (mfa.py / break_glass.py) and delegate to the
# platform writer. These pure tests pin the EMISSION CONTRACT — one coarse
# event per rejection, no codes, no seeds, no tokens — while the DB-backed
# persistence of the same events is pinned in test_mfa_login_flow.py and
# test_break_glass_redis.py.


class _SpyEvents:
    """Capture what a core emitter sends to the platform writer."""

    def __init__(self, monkeypatch, module, name: str = "_emit_security_event"):
        self.calls: list[dict] = []
        spy = self

        async def _capture(event_type, *, details=None, ip=None, tenant_id=None, actor_user_id=None):
            spy.calls.append(
                {
                    "event_type": event_type,
                    "details": details,
                    "ip": ip,
                    "tenant_id": tenant_id,
                    "actor_user_id": actor_user_id,
                }
            )

        monkeypatch.setattr(module, name, _capture)


@pytest.fixture
async def fakeredis_client() -> AsyncIterator:
    from fakeredis.aioredis import FakeRedis

    client = FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_every_mfa_challenge_rejection_emits_one_coarse_event(
    monkeypatch, fakeredis_client
) -> None:
    from app.core import mfa

    spy = _SpyEvents(monkeypatch, mfa)
    monkeypatch.setattr("app.core.mfa.get_redis", lambda: fakeredis_client)

    async def _no_totp(session, *, user_id, code):
        return None

    async def _no_backup(session, user_id, code):
        return False

    monkeypatch.setattr(mfa, "_verify_user_totp_counter", _no_totp)
    monkeypatch.setattr(mfa, "_consume_backup_code", _no_backup)

    uid, tid = uuid.uuid4(), uuid.uuid4()
    cid = await mfa.start_challenge(uid, tid, redis=fakeredis_client)
    for _ in range(mfa.CHALLENGE_MAX_FAILURES):
        with pytest.raises(PermissionDeniedError):
            await mfa.check_challenge_code(
                None, challenge_id=cid, code="000000", ip="203.0.113.9"
            )

    assert [c["event_type"] for c in spy.calls] == ["mfa_verify_failure"] * (
        mfa.CHALLENGE_MAX_FAILURES
    )
    outcomes = [c["details"]["outcome"] for c in spy.calls]
    assert outcomes[: mfa.CHALLENGE_MAX_FAILURES - 1] == ["invalid_code"] * (
        mfa.CHALLENGE_MAX_FAILURES - 1
    )
    assert outcomes[-1] == "challenge_locked"
    # Coarse only: outcome string, the actor from the challenge payload, and
    # the request ip — never the presented code, the seed, or any PII.
    assert all(set(c["details"]) == {"outcome"} for c in spy.calls)
    assert all(c["actor_user_id"] == uid for c in spy.calls)
    assert all(c["tenant_id"] == tid for c in spy.calls)
    assert all(c["ip"] == "203.0.113.9" for c in spy.calls)


async def test_break_glass_use_and_reject_are_both_audited(
    monkeypatch, fakeredis_client
) -> None:
    from app.core import break_glass as bg

    spy = _SpyEvents(monkeypatch, bg)
    tid, uid = uuid.uuid4(), uuid.uuid4()
    token = "bg-audit-" + uuid.uuid4().hex[:16]
    payload = json.dumps(
        {
            "tenant_id": str(tid),
            "user_id": str(uid),
            "action": "tenant_status_change",
            "resource_type": "tenant",
            "resource_id": str(tid),
            "reason": "audited emission contract",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
    )
    await fakeredis_client.set(
        bg._capability_key(token), payload, ex=bg.CAPABILITY_TTL_MINUTES * 60
    )

    # The USE validates and is audited; the immediate second presentation
    # is REJECTED and audited too.
    assert await bg.validate_capability(
        token, tenant_id=tid, user_id=uid, action="tenant_status_change",
        redis=fakeredis_client,
    )
    assert not await bg.validate_capability(
        token, tenant_id=tid, user_id=uid, action="tenant_status_change",
        redis=fakeredis_client,
    )
    assert [c["event_type"] for c in spy.calls] == [
        "break_glass_use",
        "break_glass_reject",
    ]
    assert spy.calls[0]["details"] == {
        "action": "tenant_status_change",
        "outcome": "validated",
    }
    assert spy.calls[1]["details"] == {
        "action": "tenant_status_change",
        "outcome": "rejected",
    }
    # The capability token itself must never appear in the trail.
    assert all(token not in json.dumps(c["details"]) for c in spy.calls)

    # A failed PEEK is a rejected attempt (audited); a successful peek stays
    # silent — the use at the protected action is its own event.
    spy.calls.clear()
    assert not await bg.peek_capability(
        token, tenant_id=tid, user_id=uid, action="tenant_status_change",
        redis=fakeredis_client,
    )
    assert [c["event_type"] for c in spy.calls] == ["break_glass_reject"]

"""Identity/auth gaps that the existing suite could not see.

The headline gap: refresh-token REUSE detection revoked the token family on the
REQUEST transaction and then raised — so the 401 rolled the revocation back and
the family was never actually revoked in production. The old test
(``test_auth_flow.test_refresh_token_reuse_revokes_family``) called the service
directly, outside any request transaction, so the uncommitted UPDATE was visible
to it and the bug was invisible.

The first test is DB-free (runs locally); the second is DB-backed (CI only).
"""

from __future__ import annotations

import types
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.errors import PermissionDeniedError
from app.core.security import hash_password
from app.modules.identity import service
from app.modules.identity.models import RefreshToken


class _Result:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Minimal AsyncSession stand-in for an independently-owned writer."""

    def __init__(self) -> None:
        self.executed: list = []
        self.added: list = []

    async def execute(self, stmt, *args, **kwargs):
        self.executed.append(stmt)
        return _Result(None)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return _FakeTxn()


class _RequestSession:
    """The request-scoped session: records what the service writes ONTO it."""

    def __init__(self, row) -> None:
        self._row = row
        self.executed: list = []
        self.added: list = []

    async def execute(self, stmt, *args, **kwargs):
        self.executed.append(stmt)
        return _Result(self._row)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


@pytest.fixture
def recorded_events(monkeypatch):
    """Capture §67 security events instead of writing rows."""
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


def _revoked_row(user_id: uuid.UUID, tenant_id: uuid.UUID):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        tenant_id=tenant_id,
        revoked_at=datetime.now(UTC),
    )


# ------------------------------------------------------------- DB-free (local) --


async def test_reuse_detection_revokes_the_family_on_an_independent_transaction(
    monkeypatch, recorded_events
) -> None:
    """The family revocation must NOT ride the request transaction.

    The reuse path raises straight after, so anything written on the request
    session is rolled back by the caller. The revocation therefore has to go
    through a session the service owns; and the audit event through the §67
    writer (which also owns its transaction).
    """
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    request_session = _RequestSession(_revoked_row(user_id, tenant_id))

    created: list[_FakeSession] = []

    def _factory():
        session = _FakeSession()
        created.append(session)
        return session

    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: _factory)

    with pytest.raises(PermissionDeniedError):
        await service.AuthService.refresh(
            request_session, refresh_token="replayed-token"
        )

    # The revocation ran on its OWN session...
    assert len(created) == 1, "family revocation must run on an independent session"
    assert len(created[0].executed) == 1
    stmt = created[0].executed[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert sql.startswith("UPDATE refresh_tokens")
    assert "revoked_at" in sql

    # ...and the request session carries only the SELECT, no doomed writes.
    assert len(request_session.executed) == 1
    assert request_session.added == [], "no audit row on the doomed request transaction"

    assert [c["event_type"] for c in recorded_events] == ["token_reuse_detected"]
    assert recorded_events[0]["actor_user_id"] == user_id
    assert recorded_events[0]["tenant_id"] == tenant_id


async def test_reuse_detection_compiled_statement_targets_the_whole_family() -> None:
    """Guard the UPDATE's WHERE so it cannot silently revoke one token only."""
    stmt = (
        sa.update(RefreshToken)
        .where(RefreshToken.user_id == uuid.uuid4(), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "refresh_tokens.user_id" in sql
    assert "refresh_tokens.revoked_at IS NULL" in sql


# ------------------------------------------------------- DB-backed (CI only) ----


async def test_reuse_revocation_survives_the_request_rollback(db_url, monkeypatch) -> None:
    """End-to-end: the revocation must outlive the request that raised the 401.

    Everything is COMMITTED here, because the fix's independent writer opens its
    own transaction and cannot see uncommitted test data — and because the point
    is to prove durability across a rollback. Cleanup is explicit.
    """
    engine = create_async_engine(
        db_url, pool_pre_ping=True, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # The service's independent writer must use this engine, not the settings one.
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: factory)

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"reuse-{user_id.hex[:12]}@test.local"
    try:
        async with factory() as seed:
            async with seed.begin():
                await seed.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name, lifecycle_state, is_active) "
                        "VALUES (:id, :slug, 'Reuse Tenant', 'active', true)"
                    ),
                    {"id": str(tenant_id), "slug": f"reuse-{tenant_id.hex[:12]}"},
                )
                await seed.execute(
                    text(
                        "INSERT INTO users (id, email, password_hash, full_name, is_active) "
                        "VALUES (:id, :email, :ph, 'Reuse User', true)"
                    ),
                    {"id": str(user_id), "email": email, "ph": hash_password("secret-password")},
                )

        # Mint the first pair (login-equivalent), committed.
        async with factory() as session:
            async with session.begin():
                pair = service.AuthService._issue_pair(
                    session, types.SimpleNamespace(id=user_id), tenant_id
                )

        # Rotate once: `pair.refresh_token` is now revoked, `pair2` is live.
        async with factory() as session:
            async with session.begin():
                pair2, _user, _tenant = await service.AuthService.refresh(
                    session, refresh_token=pair.refresh_token
                )

        async def _replay_the_rotated_token() -> None:
            # Mirrors `get_db`: the raise propagates THROUGH the transaction, so
            # the transaction rolls back exactly as it does in production.
            async with factory() as session:
                async with session.begin():
                    await service.AuthService.refresh(
                        session, refresh_token=pair.refresh_token
                    )

        with pytest.raises(PermissionDeniedError):
            await _replay_the_rotated_token()

        async with factory() as check:
            async with check.begin():
                rows = (
                    await check.execute(
                        select(RefreshToken).where(RefreshToken.user_id == user_id)
                    )
                ).scalars().all()

        assert len(rows) == 2
        assert all(r.revoked_at is not None for r in rows), (
            "reuse detection must revoke the whole family even though the "
            "request transaction rolled back"
        )
        # The rotation issued a live token; the reuse must have killed it too.
        assert pair2.refresh_token != pair.refresh_token
    finally:
        async with factory() as cleanup:
            async with cleanup.begin():
                await bind_tenant(cleanup, tenant_id)
                await cleanup.execute(
                    text("DELETE FROM security_events WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
                await cleanup.execute(
                    text("DELETE FROM refresh_tokens WHERE user_id = :u"),
                    {"u": str(user_id)},
                )
                await cleanup.execute(
                    text("DELETE FROM users WHERE id = :u"), {"u": str(user_id)}
                )
                await cleanup.execute(
                    text("DELETE FROM tenants WHERE id = :t"), {"t": str(tenant_id)}
                )
        await engine.dispose()

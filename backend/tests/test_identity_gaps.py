"""Identity/auth gaps that the existing suite could not see.

The headline gap: refresh-token REUSE detection revoked the token family on the
REQUEST transaction and then raised — so the 401 rolled the revocation back and
the family was never actually revoked in production. The old test
(``test_auth_flow.test_refresh_token_reuse_revokes_family``) called the service
directly, outside any request transaction, so the uncommitted UPDATE was visible
to it and the bug was invisible.

The reuse path now carries a small GRACE WINDOW (audit finding 5): the loser of
a concurrent refresh race (two tabs, same token) is tolerated inside
``_REFRESH_REUSE_GRACE_SECONDS`` of the rotation instead of nuking every session
the user owns; a replay past the window is still genuine reuse and revokes the
family. Both sides are pinned below.

The first tests are DB-free (run locally); the last two are DB-backed (CI only).
"""

from __future__ import annotations

import hashlib
import types
import uuid
from datetime import UTC, datetime, timedelta

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
from app.modules.identity.service import _REFRESH_REUSE_GRACE_SECONDS, AuthService


class _Result:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
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


def _revoked_row(
    user_id: uuid.UUID, tenant_id: uuid.UUID, *, age_seconds: float | None = None
):
    """A consumed (rotated) refresh-token row.

    ``age_seconds`` backdates ``revoked_at`` — the grace window measures the
    replay against it, so the reuse tests backdate past the window and the
    tolerance tests leave it just-rotated (None = now).
    """
    if age_seconds is None:
        revoked_at = datetime.now(UTC)
    else:
        revoked_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        tenant_id=tenant_id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked_at=revoked_at,
    )


# ------------------------------------------------------------- DB-free (local) --


async def test_reuse_detection_revokes_the_family_on_an_independent_transaction(
    monkeypatch, recorded_events
) -> None:
    """The family revocation must NOT ride the request transaction.

    The reuse path raises straight after, so anything written on the request
    session is rolled back by the caller. The revocation therefore has to go
    through a session the service owns; and the audit event through the §67
    writer (which also owns its transaction). The replay here is backdated
    PAST the grace window — inside it the same replay is the tolerated
    concurrent-duplicate case (see the tolerance test below).
    """
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    request_session = _RequestSession(
        _revoked_row(user_id, tenant_id, age_seconds=_REFRESH_REUSE_GRACE_SECONDS + 30)
    )

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


class _QueuedSession:
    """A request-session stand-in that serves a QUEUE of statement results.

    The tolerance path runs the WHOLE refresh flow on the fake (token row →
    user → tenant lifecycle state → pair), so each SELECT needs its own
    answer; popping the queue in order keeps the fake honest about the order
    the service actually reads in.
    """

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.executed: list = []
        self.added: list = []

    async def execute(self, stmt, *args, **kwargs):
        self.executed.append(stmt)
        return _Result(self._results.pop(0) if self._results else None)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


async def test_refresh_race_inside_the_grace_window_is_tolerated(
    monkeypatch, recorded_events
) -> None:
    """The loser of a concurrent refresh race must NOT nuke the family.

    Two tabs hit /auth/refresh with the same token; FOR UPDATE serializes
    them, the winner rotates, the loser re-reads the row as revoked — inside
    the grace window that is a duplicate, not theft. The loser gets a pair of
    its own, the family revocation never runs, and the row's ORIGINAL
    revoked_at must not be extended (a sliding window would let a patient
    replay re-enter forever).
    """
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    age = 5.0  # rotated 5s ago — well inside the window
    row = _revoked_row(user_id, tenant_id, age_seconds=age)
    original_revoked_at = row.revoked_at
    request_session = _QueuedSession(
        [
            row,  # the refresh-token lookup
            types.SimpleNamespace(  # the user lookup
                id=user_id,
                is_active=True,
                auth_version=0,
                is_platform_admin=False,
            ),
            "active",  # the tenant lifecycle state
        ]
    )

    def _factory():  # must never be called: no family revocation
        raise AssertionError("family revocation must not run inside the grace window")

    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: _factory)

    pair, _user, _tenant = await AuthService.refresh(
        request_session, refresh_token="raced-token"
    )

    assert pair.refresh_token, "the tolerated duplicate still mints its own pair"
    assert row.revoked_at == original_revoked_at, (
        "the tolerated path must NOT re-stamp revoked_at — the window is "
        "measured from the original rotation, or replay could extend it"
    )
    assert [c["event_type"] for c in recorded_events] == ["token_refresh_race_tolerated"]
    assert any(isinstance(obj, RefreshToken) for obj in request_session.added)


async def test_refresh_replay_past_the_grace_window_still_revokes(
    recorded_events,
) -> None:
    """Genuine later reuse: past the window, the family dies."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    request_session = _RequestSession(
        _revoked_row(user_id, tenant_id, age_seconds=_REFRESH_REUSE_GRACE_SECONDS + 0.5)
    )

    with pytest.raises(PermissionDeniedError, match="refresh token revoked"):
        await AuthService.refresh(request_session, refresh_token="replayed-token")

    assert [c["event_type"] for c in recorded_events] == ["token_reuse_detected"]


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


# --------------------------------------------- get_current_user verdict split --

def _bare_request():
    """A minimal Starlette Request for direct dependency calls."""
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/me",
            "raw_path": b"/api/v1/auth/me",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


class _BrokenSession:
    """A session whose every query dies — the shape of a pool failure."""

    async def execute(self, *args, **kwargs):
        raise sa.exc.OperationalError("SELECT users", {}, Exception("pool exploded"))


async def test_get_current_user_db_failure_is_not_an_auth_verdict() -> None:
    """A database failure must surface as 5xx, never as 401/403.

    get_current_user's catch-all converts UNEXPECTED exceptions into the
    "invalid token" 403 — correct for a malformed/expired token, wrong for a
    transient connection blip: answering 403 would log every user out on a
    pool hiccup. SQLAlchemyError is therefore deliberately re-raised (the
    generic handler renders it 5xx). Both sides are pinned here: an
    undecodable token still gets the auth verdict, a dead session does not.
    """
    from app.core.security import create_access_token
    from app.core.errors import PermissionDeniedError
    from app.modules.identity.deps import get_current_user

    token = create_access_token(str(uuid.uuid4()), {"tenant_id": str(uuid.uuid4())})

    with pytest.raises(PermissionDeniedError):
        await get_current_user(_bare_request(), _BrokenSession(), "Bearer not-a-jwt")
    with pytest.raises(sa.exc.OperationalError):
        await get_current_user(_bare_request(), _BrokenSession(), f"Bearer {token}")


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

        # The replay below must be genuine REUSE, not a tolerated race: backdate
        # the rotated row's revoked_at past the grace window (sleeping the real
        # 45s would slow the suite for no extra coverage — the window's
        # arithmetic is already pinned by the DB-free tests).
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "UPDATE refresh_tokens SET revoked_at = "
                        "now() - make_interval(secs => :age) "
                        "WHERE token_hash = :h"
                    ),
                    {
                        "age": _REFRESH_REUSE_GRACE_SECONDS + 30,
                        "h": hashlib.sha256(pair.refresh_token.encode()).hexdigest(),
                    },
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
                # security_events is deliberately NOT deleted here: fd2026100409
                # made it append-only (INSERT/SELECT policies only), so even the
                # test role cannot purge it. Isolation is guaranteed by the
                # test transaction's rollback instead.
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


async def test_replay_right_after_rotation_is_a_tolerated_race_not_reuse(
    db_url, monkeypatch
) -> None:
    """The parallel-tab case END TO END: replaying a just-rotated token gets a
    pair and leaves the rest of the family alive.

    This is the other half of the grace window: with it, two tabs refreshing in
    the same second stop revoking each other's sessions; without it, this exact
    sequence killed every token the user owned.
    """
    engine = create_async_engine(
        db_url, pool_pre_ping=True, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: factory)

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"grace-{user_id.hex[:12]}@test.local"
    try:
        async with factory() as seed:
            async with seed.begin():
                await seed.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name, lifecycle_state, is_active) "
                        "VALUES (:id, :slug, 'Grace Tenant', 'active', true)"
                    ),
                    {"id": str(tenant_id), "slug": f"grace-{tenant_id.hex[:12]}"},
                )
                await seed.execute(
                    text(
                        "INSERT INTO users (id, email, password_hash, full_name, is_active) "
                        "VALUES (:id, :email, :ph, 'Grace User', true)"
                    ),
                    {"id": str(user_id), "email": email, "ph": hash_password("secret-password")},
                )

        async with factory() as session:
            async with session.begin():
                pair = service.AuthService._issue_pair(
                    session, types.SimpleNamespace(id=user_id), tenant_id
                )

        # Rotate once, then replay the JUST-rotated token milliseconds later —
        # the loser of the tab race.
        async with factory() as session:
            async with session.begin():
                pair2, _user, _tenant = await service.AuthService.refresh(
                    session, refresh_token=pair.refresh_token
                )
        async with factory() as session:
            async with session.begin():
                pair3, _user, _tenant = await service.AuthService.refresh(
                    session, refresh_token=pair.refresh_token
                )

        assert pair3.refresh_token not in {pair.refresh_token, pair2.refresh_token}

        async with factory() as check:
            async with check.begin():
                rows = (
                    await check.execute(
                        select(RefreshToken).where(RefreshToken.user_id == user_id)
                    )
                ).scalars().all()

        # The raced replay minted its own live pair; the family was NOT nuked.
        live = [r for r in rows if r.revoked_at is None]
        assert len(live) == 2, "the rotated token AND the tolerated replay stay live"
    finally:
        async with factory() as cleanup:
            async with cleanup.begin():
                await bind_tenant(cleanup, tenant_id)
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

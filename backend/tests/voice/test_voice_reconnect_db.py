"""Reconnect idempotency, on a real Postgres instead of an index definition.

The rule under test is the one that costs money when it breaks: a phone that drops and
re-dials with the same client key must continue the session it already had, not buy a
second call. Until now the only proof was a static one — that the ORM declares a unique
index on (tenant_id, client_key). That says the index exists in the model; it does not say
the database refuses the duplicate, nor that the manager returns the open session.

These run against the real database the CI shards provide (tests/conftest.py `db` fixture,
transactional rollback) and skip cleanly when no database URL is configured.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
import sqlalchemy as sa

from app.core.db import bind_tenant
from app.modules.voice.application.session_manager import VoiceSessionManager
from app.modules.voice.domain.personas import PrincipalType
from app.modules.voice.infrastructure.sql_store import SqlSessionStore

SCOPES = frozenset({"assistant:use"})


async def _start(session, tenant_id: uuid.UUID, principal_id: uuid.UUID, key: str):
    manager = VoiceSessionManager(SqlSessionStore(session))
    return await manager.start(
        principal_type=PrincipalType.MERCHANT_USER,
        principal_id=principal_id,
        tenant_id=tenant_id,
        held_scopes=SCOPES,
        client_key=key,
    )


async def test_a_redial_with_the_same_key_continues_the_open_call(db, tenant_ctx) -> None:
    key = f"phone-{uuid.uuid4().hex[:8]}"

    first = await _start(db, tenant_ctx.tenant_id, tenant_ctx.user.id, key)
    second = await _start(db, tenant_ctx.tenant_id, tenant_ctx.user.id, key)

    assert second.session_id == first.session_id
    # One row, not two: the second call reused the session it found.
    rows = (
        await db.execute(
            sa.text("SELECT count(*) FROM voice_sessions WHERE tenant_id = :t AND client_key = :k"),
            {"t": str(tenant_ctx.tenant_id), "k": key},
        )
    ).scalar_one()
    assert rows == 1


async def test_the_database_itself_refuses_a_second_row_for_the_same_key(db, tenant_ctx) -> None:
    """The manager's lookup is an optimisation; the unique index is the guarantee."""
    key = f"phone-{uuid.uuid4().hex[:8]}"
    await _start(db, tenant_ctx.tenant_id, tenant_ctx.user.id, key)
    donor = await _start(
        db, tenant_ctx.tenant_id, tenant_ctx.user.id, f"other-{uuid.uuid4().hex[:8]}"
    )

    # A second row for the same shop and the same key, built by the store itself so the
    # test cannot pass because of a column name it guessed wrong.
    clash = uuid.uuid4()
    squatter = replace(
        donor,
        session_id=clash,
        capability=replace(donor.capability, session_id=clash),
        client_key=key,
    )

    with pytest.raises(sa.exc.IntegrityError):
        await SqlSessionStore(db).put(squatter)


async def test_another_shop_may_use_the_same_key(db, tenant_ctx, owner_password_hash) -> None:
    """The key is the caller's own, so uniqueness is per shop, never global."""
    from app.modules.identity.models import Tenant

    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Shop")
    db.add(other)
    await db.flush()

    key = f"phone-{uuid.uuid4().hex[:8]}"
    mine = await _start(db, tenant_ctx.tenant_id, tenant_ctx.user.id, key)

    await bind_tenant(db, other.id)
    theirs = await _start(db, other.id, tenant_ctx.user.id, key)

    assert theirs.session_id != mine.session_id


async def test_a_session_from_another_shop_is_invisible(db, tenant_ctx) -> None:
    """RLS, measured: the store cannot read a session that belongs to another tenant."""
    from app.modules.identity.models import Tenant

    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Shop")
    db.add(other)
    await db.flush()

    mine = await _start(db, tenant_ctx.tenant_id, tenant_ctx.user.id, f"k-{uuid.uuid4().hex[:8]}")

    await bind_tenant(db, other.id)
    assert await SqlSessionStore(db).get(mine.session_id) is None

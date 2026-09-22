"""G-06 / §68-69: DatabaseSecretStore — the secure-environment secret store.

EnvSecretStore kept values in ``os.environ`` of the current process: invisible
to the second uvicorn worker, lost on every restart/redeploy. These tests pin
the replacement: envelope-encrypted (AES-256-GCM, ``v1:``) versioned rows in
Postgres, tenant-scoped under FORCE RLS, selected automatically when
``is_secure_environment`` is true.

The store opens its own sessions by design (the port signature carries no
session), so the DB tests bind the app's session factory to the test
connection via ``app_sessions_on_test_connection``.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from app.core.secrets import DatabaseSecretStore, EnvelopeSecretStore
from app.core.tenancy import reset_current_tenant, set_current_tenant
from app.modules.platform.models import SecretValue

_KEY_B64 = base64.b64encode(b"g06-db-store-test-key-32-bytes!!!"[:32]).decode("ascii")


@pytest.fixture
def envelope() -> EnvelopeSecretStore:
    return EnvelopeSecretStore(_KEY_B64)


@pytest.fixture
def store(envelope: EnvelopeSecretStore) -> DatabaseSecretStore:
    return DatabaseSecretStore(envelope=envelope)


@pytest.fixture
def ambient_tenant(tenant_ctx):
    """Publish the request-path tenant contextvar the store resolves from."""
    set_current_tenant(tenant_ctx.tenant_id)
    try:
        yield tenant_ctx
    finally:
        reset_current_tenant()


async def _rows(db, tenant_id: uuid.UUID, key: str) -> list[SecretValue]:
    return list(
        (
            await db.execute(
                sa.select(SecretValue)
                .where(
                    SecretValue.tenant_id == tenant_id,
                    SecretValue.vault_key == key,
                )
                .order_by(SecretValue.version)
            )
        )
        .scalars()
        .all()
    )


async def test_put_get_roundtrip_and_ciphertext_at_rest(
    db, tenant_ctx, app_sessions_on_test_connection, ambient_tenant, store
) -> None:
    version = await store.put("wa_token", "super-secret-value")
    assert version == 1
    assert await store.get_or_none("wa_token") == "super-secret-value"

    rows = await _rows(db, tenant_ctx.tenant_id, "wa_token")
    assert len(rows) == 1
    assert rows[0].ciphertext.startswith(EnvelopeSecretStore.PREFIX)
    assert "super-secret-value" not in rows[0].ciphertext
    assert rows[0].expires_at is None


async def test_values_survive_a_new_store_instance(
    db, tenant_ctx, app_sessions_on_test_connection, ambient_tenant, store, envelope
) -> None:
    """The G-06 regression: EnvSecretStore lost every value on process restart.

    A second store instance (a "restarted process") must read what the first
    wrote, because the value lives in Postgres, not process memory.
    """
    await store.put("meta_app_secret", "v1-value")
    restarted = DatabaseSecretStore(envelope=envelope)
    assert await restarted.get_or_none("meta_app_secret") == "v1-value"


async def test_rotate_serves_newest_and_expires_the_old_version(
    db, tenant_ctx, app_sessions_on_test_connection, ambient_tenant, store
) -> None:
    await store.put("wa_token", "old-value")
    new_version = await store.rotate("wa_token", "new-value", grace_seconds=300)

    assert new_version == 2
    assert await store.get_or_none("wa_token") == "new-value"

    rows = await _rows(db, tenant_ctx.tenant_id, "wa_token")
    assert [row.version for row in rows] == [1, 2]
    # §69: the old version stays readable for the grace window, then expires.
    assert rows[0].expires_at is not None
    assert rows[0].expires_at > datetime.now(UTC)
    assert rows[1].expires_at is None


async def test_expired_versions_are_not_served(
    db, tenant_ctx, app_sessions_on_test_connection, ambient_tenant, store
) -> None:
    await store.put("short_lived", "value", ttl_seconds=-1)  # already expired
    assert await store.get_or_none("short_lived") is None


async def test_delete_removes_every_version(
    db, tenant_ctx, app_sessions_on_test_connection, ambient_tenant, store
) -> None:
    await store.put("doomed", "one")
    await store.rotate("doomed", "two")
    await store.delete("doomed")
    assert await store.get_or_none("doomed") is None
    assert await _rows(db, tenant_ctx.tenant_id, "doomed") == []


async def test_tenant_isolation(
    db, tenant_ctx, app_sessions_on_test_connection, ambient_tenant, store
) -> None:
    await store.put("wa_token", "tenant-a-secret")
    # Another tenant's context sees nothing — app-level filter AND RLS.
    set_current_tenant(uuid.uuid4())
    try:
        assert await store.get_or_none("wa_token") is None
    finally:
        set_current_tenant(tenant_ctx.tenant_id)


async def test_fail_closed_without_tenant_context(
    db, tenant_ctx, app_sessions_on_test_connection, store
) -> None:
    """No ambient tenant -> LookupError, never a guess at the scope."""
    reset_current_tenant()
    with pytest.raises(LookupError):
        await store.get_or_none("wa_token")
    with pytest.raises(LookupError):
        await store.put("wa_token", "value")


def test_secure_environment_resolves_database_store(monkeypatch) -> None:
    from app.core import secrets
    from app.core.config import get_settings

    secrets.reset_secret_store()
    monkeypatch.setattr(
        type(get_settings()),
        "is_secure_environment",
        property(lambda _self: True),
    )
    try:
        assert isinstance(secrets.get_secret_store(), secrets.DatabaseSecretStore)
    finally:
        secrets.reset_secret_store()


def test_local_environment_resolves_env_store() -> None:
    from app.core import secrets

    secrets.reset_secret_store()
    try:
        assert isinstance(secrets.get_secret_store(), secrets.EnvSecretStore)
    finally:
        secrets.reset_secret_store()

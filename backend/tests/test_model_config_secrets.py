"""§68: model-config provider keys live in the secret store, not the row."""

from __future__ import annotations

from sqlalchemy import select

from app.core.secrets import InMemorySecretStore, get_envelope_store
from app.modules.ai.gateway import resolve_model_config
from app.modules.ai.models import ModelConfig
from app.modules.ai.secret_backfill import (
    backfill_model_config_secrets,
    model_config_vault_key,
    set_model_config_secret,
)
from app.modules.platform.models import SecretValue


async def test_backfill_moves_inline_key_into_secret_values(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    row = ModelConfig(
        tenant_id=tenant_id,
        alias="fast",
        provider="openai",
        model="m",
        config={"base_url": "https://cfg.test/v1", "api_key": "sk-live-123"},
    )
    db.add(row)
    await db.flush()

    moved = await db.run_sync(lambda s: backfill_model_config_secrets(s.connection()))
    await db.refresh(row)

    assert moved == 1
    assert row.secret_ref == model_config_vault_key(tenant_id, "fast")
    assert "api_key" not in (row.config or {})
    assert row.config["base_url"] == "https://cfg.test/v1"

    ciphertext = (
        await db.execute(
            select(SecretValue.ciphertext).where(
                SecretValue.tenant_id == tenant_id,
                SecretValue.vault_key == row.secret_ref,
            )
        )
    ).scalar_one()
    assert get_envelope_store().decrypt(ciphertext).value == "sk-live-123"

    # Idempotent: nothing left to move.
    assert await db.run_sync(lambda s: backfill_model_config_secrets(s.connection())) == 0


async def test_backfill_ignores_blank_api_keys(db, tenant_ctx):
    db.add(
        ModelConfig(
            tenant_id=tenant_ctx.tenant_id,
            alias="fast",
            provider="openai",
            model="m",
            config={"api_key": ""},
        )
    )
    await db.flush()
    assert await db.run_sync(lambda s: backfill_model_config_secrets(s.connection())) == 0


async def test_set_model_config_secret_rotates_and_gateway_prefers_it(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    vault_key = await set_model_config_secret(db, tenant_id, "fast", "sk-new-1")
    vault_key2 = await set_model_config_secret(db, tenant_id, "fast", "sk-new-2")
    assert vault_key == vault_key2 == model_config_vault_key(tenant_id, "fast")

    versions = (
        (
            await db.execute(
                select(SecretValue.version)
                .where(
                    SecretValue.tenant_id == tenant_id,
                    SecretValue.vault_key == vault_key,
                )
                .order_by(SecretValue.version.asc())
            )
        )
        .scalars()
        .all()
    )
    assert versions == [1, 2]

    db.add(
        ModelConfig(
            tenant_id=tenant_id,
            alias="fast",
            provider="openai",
            model="m",
            config={"base_url": "https://cfg.test/v1", "api_key": "stale-inline"},
            secret_ref=vault_key2,
        )
    )
    await db.flush()

    store = InMemorySecretStore()
    await store.put(vault_key2, "sk-new-2")
    monkeypatch.setattr("app.core.secrets.get_secret_store", lambda: store)

    resolved = await resolve_model_config(db, tenant_id, "fast")
    assert resolved["api_key"] == "sk-new-2"

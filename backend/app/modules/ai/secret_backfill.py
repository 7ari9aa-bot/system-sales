"""§68 model-config credentials: keys live in the secret store, not the row.

model_configs historically carried the provider API key inline in the config
JSONB — anyone with table read access (dumps, support tooling, BI) saw a live
provider key. The fix: the row stores only a secret_ref pointer and the key
lives in secret_values, envelope-encrypted (AES-256-GCM). The gateway already
prefers secret_ref at resolution time (gateway.resolve_model_config).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.core.secrets import EnvelopeSecretStore, get_envelope_store

VAULT_KEY_PREFIX = "model_config"


def model_config_vault_key(tenant_id, alias: str) -> str:
    return f"{VAULT_KEY_PREFIX}:{tenant_id}:{alias}"


def backfill_model_config_secrets(
    conn, *, store: EnvelopeSecretStore | None = None
) -> int:
    """Move every inline api_key into secret_values; returns rows migrated.

    Sync (over a Connection) because its production caller is the alembic
    migration, which runs on a plain connection.
    """
    s = store or get_envelope_store()
    rows = conn.execute(
        text(
            "SELECT id, tenant_id, alias, config->>'api_key' AS api_key "
            "FROM model_configs "
            "WHERE secret_ref IS NULL AND config->'api_key' IS NOT NULL "
            "AND config->>'api_key' <> ''"
        )
    ).fetchall()
    moved = 0
    for row in rows:
        vault_key = model_config_vault_key(row.tenant_id, row.alias)
        version = conn.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM secret_values "
                "WHERE tenant_id = :t AND vault_key = :k"
            ),
            {"t": row.tenant_id, "k": vault_key},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO secret_values (id, tenant_id, vault_key, version, ciphertext) "
                "VALUES (:i, :t, :k, :v, :c) "
                "ON CONFLICT (tenant_id, vault_key, version) DO NOTHING"
            ),
            {
                "i": uuid.uuid4(),
                "t": row.tenant_id,
                "k": vault_key,
                "v": version,
                "c": s.encrypt(row.api_key),
            },
        )
        conn.execute(
            text(
                "UPDATE model_configs SET secret_ref = :k, config = config - 'api_key' "
                "WHERE id = :i"
            ),
            {"k": vault_key, "i": row.id},
        )
        moved += 1
    return moved


async def set_model_config_secret(
    session, tenant_id, alias: str, api_key: str
) -> str:
    """Write-path for operator tooling: store the key, return the vault_key.

    The caller sets ModelConfig.secret_ref to the returned key and leaves
    api_key out of the config JSONB.
    """
    from sqlalchemy import func, select

    from app.modules.platform.models import SecretValue

    vault_key = model_config_vault_key(tenant_id, alias)
    current = (
        await session.execute(
            select(func.coalesce(func.max(SecretValue.version), 0)).where(
                SecretValue.tenant_id == tenant_id,
                SecretValue.vault_key == vault_key,
            )
        )
    ).scalar_one()
    session.add(
        SecretValue(
            tenant_id=tenant_id,
            vault_key=vault_key,
            version=current + 1,
            ciphertext=get_envelope_store().encrypt(api_key),
        )
    )
    return vault_key

"""Move model_configs api_key into the encrypted secret store (§68 backfill).

Revision ID: fe2026100812
Revises: fe2026100811
Create Date: 2026-10-10 01:10:00.000000

Every model_configs row that still carries config.api_key gets the key
migrated into secret_values (envelope-encrypted, AES-256-GCM) and the
plaintext dropped from the JSONB. The gateway already prefers secret_ref
(gateway.resolve_model_config), so resolution is unchanged.

Refuses to run when rows need migrating but SECRETS_MASTER_KEY is absent —
encrypting with the published dev-key fallback would be worse than plaintext.
A skipped migration never reruns (alembic stamps it applied), so a silent
skip would leave plaintext keys in place forever; failing the deploy makes
the missing key visible immediately.
"""

import logging
import os

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026100812"
down_revision: str | None = "fe2026100811"
branch_labels: str | None = None
depends_on: str | None = None

logger = logging.getLogger("alembic.runtime")


def upgrade() -> None:
    conn = op.get_bind()
    if conn is None:
        # tests/test_migrations.py swaps `op` for a recording stub with no
        # bind, so it can parse every migration's SQL statically. There is
        # nothing to encrypt while it is doing that (the d5a1c7e94b02
        # precedent).
        return
    pending = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM model_configs "
            "WHERE secret_ref IS NULL AND config->'api_key' IS NOT NULL "
            "AND config->>'api_key' <> ''"
        )
    ).scalar_one()
    if pending == 0:
        return
    master = os.environ.get("SECRETS_MASTER_KEY", "").strip()
    if not master:
        raise RuntimeError(
            f"{pending} model_configs row(s) still carry an inline api_key and "
            "SECRETS_MASTER_KEY is not set — refusing to leave provider keys in "
            "plaintext. Set SECRETS_MASTER_KEY (base64, 32+ bytes) and redeploy."
        )
    previous = [
        k.strip()
        for k in os.environ.get("SECRETS_PREVIOUS_MASTER_KEYS", "").split(",")
        if k.strip()
    ]
    from app.core.secrets import EnvelopeSecretStore
    from app.modules.ai.secret_backfill import backfill_model_config_secrets

    moved = backfill_model_config_secrets(
        conn, store=EnvelopeSecretStore(master, previous_master_keys=previous)
    )
    logger.info("model_configs secret backfill: moved %d row(s) into secret_values", moved)


def downgrade() -> None:
    # One-way: plaintext keys cannot be restored from ciphertext by design.
    pass

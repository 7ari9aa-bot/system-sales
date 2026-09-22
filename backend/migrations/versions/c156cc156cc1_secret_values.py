"""secret_values: durable envelope-encrypted secret store (§68-69, G-06)

Revision ID: c156cc156cc1
Revises: c146bb146bb1
Create Date: 2026-09-22

EnvSecretStore — the only SecretStorePort implementation that existed — kept
values in ``os.environ`` of the current process: invisible to the second
uvicorn worker, lost on every restart/redeploy, and never rotated with grace.
That is strictly worse than the JSONB column §68 replaced. This table backs
the new DatabaseSecretStore: values live in Postgres, encrypted by
EnvelopeSecretStore (AES-256-GCM, ``v1:`` wire format), versioned per key so
rotation keeps the old version readable for a grace period (§69), and scoped
per tenant under FORCE RLS.

Idempotent — uses IF NOT EXISTS for the table, indexes and policy.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c156cc156cc1"
down_revision: str | None = "c146bb146bb1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical tenant guard (same shape as c136aa136aa1 / provision.py): the
# NULLIF keeps an UNSET app.tenant_id from casting '' to uuid, so an unbound
# session matches ZERO rows instead of raising.
_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # NOTE: one statement per op.execute(). Migrations run through asyncpg,
    # whose extended-query protocol rejects multiple commands in a single
    # execute ("cannot insert multiple commands into a prepared statement").
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.secret_values (
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_key VARCHAR(255) NOT NULL,
            version INTEGER NOT NULL,
            ciphertext TEXT NOT NULL,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Version numbers are per (tenant, key) and never reused — the store reads
    # max(version) across ALL rows, including expired ones.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_secret_values_key_version
        ON public.secret_values (tenant_id, vault_key, version)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_secret_values_tenant_key
        ON public.secret_values (tenant_id, vault_key)
        """
    )
    op.execute("ALTER TABLE public.secret_values ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.secret_values FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'secret_values' AND policyname = 'tenant_isolation'
            ) THEN
                CREATE POLICY tenant_isolation ON public.secret_values
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD});
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.secret_values")
    op.execute("DROP TABLE IF EXISTS public.secret_values")

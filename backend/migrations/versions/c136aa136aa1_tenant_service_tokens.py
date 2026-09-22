"""tenant_service_tokens: per-tenant n8n service tokens (§136)

Revision ID: c136aa136aa1
Revises: c066cc066cc1
Create Date: 2026-09-22

The single global SERVICE_TOKEN_INTERNAL Bearer let ANY tenant's automation
authenticate to the n8n adapter as any OTHER tenant. §136 requires the n8n
callback to carry a tenant-scoped credential — never a global unrestricted
token.

This table stores per-tenant, scoped, revocable service tokens. Only the
sha256 hex digest of the presented token is kept (token_hash); the
plaintext is returned to the caller exactly once at issuance.

Idempotent — uses IF NOT EXISTS for the table, indexes and policy.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c136aa136aa1"
down_revision: str | None = "c066cc066cc1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Canonical tenant guard (same shape as b2c3d4e5f6a7 / provision.py): the
# NULLIF keeps an UNSET app.tenant_id from casting '' to uuid, so an unbound
# session matches ZERO rows instead of raising.
_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # NOTE: one statement per op.execute(). Migrations run through asyncpg,
    # whose extended-query protocol rejects multiple commands in a single
    # execute ("cannot insert multiple commands into a prepared statement").
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.tenant_service_tokens (
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(127) NOT NULL,
            token_hash VARCHAR(64) NOT NULL,
            scopes JSONB NOT NULL DEFAULT '[]',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at TIMESTAMPTZ,
            rotated_from_id UUID REFERENCES tenant_service_tokens(id) ON DELETE SET NULL,
            revoked_at TIMESTAMPTZ
        )
        """
    )
    # Digest lookups must be fast AND unique across tenants: one presented
    # token resolves to at most one row.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_service_tokens_hash
        ON public.tenant_service_tokens (token_hash)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenant_service_tokens_tenant_id
        ON public.tenant_service_tokens (tenant_id)
        """
    )
    op.execute("ALTER TABLE public.tenant_service_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.tenant_service_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'tenant_service_tokens' AND policyname = 'tenant_isolation'
            ) THEN
                CREATE POLICY tenant_isolation ON public.tenant_service_tokens
                USING (tenant_id = {_TENANT_GUARD})
                WITH CHECK (tenant_id = {_TENANT_GUARD});
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.tenant_service_tokens")
    op.execute("DROP TABLE IF EXISTS public.tenant_service_tokens")

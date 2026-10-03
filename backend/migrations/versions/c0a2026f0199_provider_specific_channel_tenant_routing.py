"""resolve webhook tenants only through an unambiguous provider identity

Revision ID: c0a2026f0199
Revises: a8f41c9d07e2
Create Date: 2026-10-02 20:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c0a2026f0199"
down_revision: str | None = "a8f41c9d07e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL_TENANT_FN = """
CREATE OR REPLACE FUNCTION public.resolve_channel_tenant(p_provider text, p_key text)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
    SELECT i.tenant_id
      FROM public.integrations i
     WHERE i.provider = p_provider
       AND i.kind = 'channel'
       AND i.status IN ('active', 'connected')
       AND p_key = CASE p_provider
             WHEN 'whatsapp' THEN i.config->>'phone_number_id'
             WHEN 'telegram' THEN i.config->>'public_key'
             WHEN 'messenger' THEN i.config->>'account_id'
             WHEN 'instagram' THEN i.config->>'account_id'
             WHEN 'webchat' THEN i.config->>'public_key'
             ELSE NULL
           END
       AND NOT EXISTS (
             SELECT 1
               FROM public.integrations duplicate
              WHERE duplicate.id <> i.id
                AND duplicate.provider = i.provider
                AND duplicate.kind = 'channel'
                AND duplicate.status IN ('active', 'connected')
                AND p_key = CASE p_provider
                      WHEN 'whatsapp' THEN duplicate.config->>'phone_number_id'
                      WHEN 'telegram' THEN duplicate.config->>'public_key'
                      WHEN 'messenger' THEN duplicate.config->>'account_id'
                      WHEN 'instagram' THEN duplicate.config->>'account_id'
                      WHEN 'webchat' THEN duplicate.config->>'public_key'
                      ELSE NULL
                    END
           )
     LIMIT 1
$fn$;
"""


def upgrade() -> None:
    # One statement per execute: asyncpg's extended-query protocol rejects
    # multiple top-level statements in a single call.
    op.execute(_CHANNEL_TENANT_FN)
    op.execute(
        "REVOKE ALL ON FUNCTION public.resolve_channel_tenant(text, text) FROM PUBLIC;"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                GRANT EXECUTE ON FUNCTION public.resolve_channel_tenant(text, text)
                    TO sales_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Keep the stricter resolver when rolling the revision marker back. Restoring
    # ambiguous cross-provider matching could route a webhook to the wrong tenant.
    pass

"""secure_channel_identity_routing

Revision ID: db6022a13691
Revises: b4c5d6e7f8a9
Create Date: 2026-10-02 16:01:55.259671

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "db6022a13691"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_IDENTITY = """CASE
    WHEN provider = 'whatsapp' THEN config->>'phone_number_id'
    WHEN provider IN ('messenger', 'instagram') THEN config->>'account_id'
    WHEN provider IN ('telegram', 'webchat') THEN config->>'public_key'
END"""

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

_UNIQUE_INDEX = f"""
CREATE UNIQUE INDEX uq_integrations_active_channel_identity
    ON public.integrations (provider, ({_IDENTITY}))
 WHERE kind = 'channel'
   AND status IN ('active', 'connected')
   AND (
       (provider = 'whatsapp' AND config->>'phone_number_id' IS NOT NULL) OR
       (provider IN ('messenger', 'instagram') AND config->>'account_id' IS NOT NULL) OR
       (provider IN ('telegram', 'webchat') AND config->>'public_key' IS NOT NULL)
   )
"""

_DUPLICATE_PREFLIGHT = f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.integrations
         WHERE kind = 'channel'
           AND status IN ('active', 'connected')
           AND ({_IDENTITY}) IS NOT NULL
         GROUP BY provider, ({_IDENTITY})
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'duplicate active channel identities; reconcile integrations before deploying';
    END IF;
END
$$;
"""


def upgrade() -> None:
    # One SQL statement per execute() for asyncpg. The preflight gives the
    # operator a non-PII remediation message before the unique index is built.
    op.execute(_DUPLICATE_PREFLIGHT)
    op.execute(_UNIQUE_INDEX)
    op.execute(_CHANNEL_TENANT_FN)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_integrations_active_channel_identity")
    # Keep the fail-closed tenant resolver on downgrade. Restoring its former
    # oldest-row-wins behavior could route a webhook into another tenant.

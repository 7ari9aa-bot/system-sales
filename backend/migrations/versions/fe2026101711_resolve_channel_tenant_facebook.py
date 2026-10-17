"""Add facebook to resolve_channel_tenant routing function.

Revision ID: fe2026101711
Revises: fe2026101710
Create Date: 2026-10-17 02:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026101711"
down_revision: str | None = "fe2026101710"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION public.resolve_channel_tenant(p_provider text, p_key text)
        RETURNS uuid
        LANGUAGE sql
        STABLE SECURITY DEFINER
        SET search_path TO 'public', 'pg_temp'
        AS $function$
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
                     WHEN 'facebook' THEN COALESCE(i.config->>'account_id', i.config->>'page_id')
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
                              WHEN 'facebook' THEN COALESCE(duplicate.config->>'account_id', duplicate.config->>'page_id')
                              WHEN 'webchat' THEN duplicate.config->>'public_key'
                              ELSE NULL
                            END
                   )
             LIMIT 1
        $function$;
    """)


def downgrade() -> None:
    pass

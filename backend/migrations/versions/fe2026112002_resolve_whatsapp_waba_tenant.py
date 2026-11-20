"""Find the store behind a WhatsApp Business Account id.

Meta's template-status webhook names the business account (`entry[].id`) and carries no phone
number, so `resolve_channel_tenant` (which matches the phone number) cannot place it and the event
would be dropped as an unknown store.

The new function is separate on purpose: it leaves the routing every message depends on untouched.
Like its sibling it is SECURITY DEFINER (webhooks arrive before any store is bound and
`integrations` is FORCE-RLS) and returns only the store id, never the credentials in `config`. When
two stores claim the same account it answers nothing rather than guess, so an event can never be
filed under the wrong store.

Revision ID: fe2026112002
Revises: fe2026112001
Create Date: 2026-11-20 03:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112002"
down_revision: str | None = "fe2026112001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WABA_TENANT_FN = """
CREATE OR REPLACE FUNCTION public.resolve_whatsapp_waba_tenant(p_waba_id text)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
    SELECT i.tenant_id
      FROM public.integrations i
     WHERE p_waba_id IS NOT NULL
       AND p_waba_id <> ''
       AND i.provider = 'whatsapp'
       AND i.kind = 'channel'
       AND i.status IN ('active', 'connected')
       AND i.config->>'waba_id' = p_waba_id
       AND NOT EXISTS (
             SELECT 1
               FROM public.integrations other
              WHERE other.id <> i.id
                AND other.provider = 'whatsapp'
                AND other.kind = 'channel'
                AND other.status IN ('active', 'connected')
                AND other.config->>'waba_id' = p_waba_id
                AND other.tenant_id <> i.tenant_id
           )
     LIMIT 1
$fn$;
"""


def upgrade() -> None:
    # One statement per execute: asyncpg's extended-query protocol rejects several in one call.
    op.execute(_WABA_TENANT_FN)
    op.execute("REVOKE ALL ON FUNCTION public.resolve_whatsapp_waba_tenant(text) FROM PUBLIC;")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                GRANT EXECUTE ON FUNCTION public.resolve_whatsapp_waba_tenant(text)
                    TO sales_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.resolve_whatsapp_waba_tenant(text);")

"""Find the one customer behind a Meta-scoped user id, for the data-deletion callback.

Meta's data-deletion request names only the person's app-scoped id (`user_id` in the signed
request), never a store. The callback therefore runs before any store is bound, and
`customer_identities` is FORCE-RLS, so the lookup goes through a SECURITY DEFINER function like
`resolve_channel_tenant`. It returns only the ids (never contact details). When the id matches
more than one customer it answers nothing rather than guess: a deletion filed against the wrong
person is worse than one that needs a human.

The status function lets the public status URL answer for a code it handed out, and only for
requests the callback itself opened.

Revision ID: fe2026112008
Revises: fe2026112007
Create Date: 2026-11-20 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112008"
down_revision: str | None = "fe2026112007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FN = """
CREATE OR REPLACE FUNCTION public.resolve_meta_user_customer(p_external_id text)
RETURNS TABLE (tenant_id uuid, customer_id uuid)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
    SELECT ci.tenant_id, ci.customer_id
      FROM public.customer_identities ci
     WHERE p_external_id IS NOT NULL
       AND p_external_id <> ''
       AND ci.channel IN ('messenger', 'instagram', 'facebook')
       AND ci.external_id = p_external_id
       AND (
             SELECT count(DISTINCT (x.tenant_id, x.customer_id))
               FROM public.customer_identities x
              WHERE x.channel IN ('messenger', 'instagram', 'facebook')
                AND x.external_id = p_external_id
           ) = 1
     LIMIT 1
$fn$;
"""

_STATUS_FN = """
CREATE OR REPLACE FUNCTION public.meta_deletion_status(p_request_id uuid)
RETURNS TABLE (status text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
    SELECT d.status::text
      FROM public.data_subject_requests d
     WHERE d.id = p_request_id
       AND d.request_type = 'delete'
       AND d.payload_scope->>'source' = 'meta_data_deletion_callback'
     LIMIT 1
$fn$;
"""


def upgrade() -> None:
    op.execute(_FN)
    op.execute(_STATUS_FN)
    op.execute("REVOKE ALL ON FUNCTION public.resolve_meta_user_customer(text) FROM PUBLIC;")
    op.execute("REVOKE ALL ON FUNCTION public.meta_deletion_status(uuid) FROM PUBLIC;")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                GRANT EXECUTE ON FUNCTION public.resolve_meta_user_customer(text) TO sales_app;
                GRANT EXECUTE ON FUNCTION public.meta_deletion_status(uuid) TO sales_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.meta_deletion_status(uuid);")
    op.execute("DROP FUNCTION IF EXISTS public.resolve_meta_user_customer(text);")

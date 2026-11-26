"""Resolve an invitation from its token without a permissive policy on the table.

``fe2026112607`` let the public accept endpoint read its own invitation by
adding ``invitations_accept_read`` beside the canonical ``tenant_isolation``
policy. Both are PERMISSIVE, so Postgres ORs them: any session that could set
``app.invitation_token`` could read a row outside its tenant, and the schema
gate (``tests/security/test_schema_wide_rls_policies.py``) is right to refuse a
tenant table carrying a second policy — it is the same shape the phase-9 sweep
(d8a1b2c3d4e5) had to repair everywhere else.

The possession read belongs in a function, not in a policy: presenting the
32-char secret grants the caller the *identity* of one row, and nothing else.
``invitation_by_token`` runs as the table owner (RLS bypassed inside the
function), returns ONLY ``id`` and ``tenant_id`` — never the email, role or
status — and the endpoint then binds that tenant and reads the row through the
normal ``tenant_isolation`` path. Same capability as before, no second policy.

Revision ID: fe2026112609
Revises: fe2026112608
Create Date: 2026-11-26 15:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112609"
down_revision: str | None = "fe2026112608"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INVITATION_TOKEN_FN = """
CREATE OR REPLACE FUNCTION public.invitation_by_token(p_token text)
RETURNS TABLE (id uuid, tenant_id uuid)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
    SELECT i.id, i.tenant_id
      FROM public.invitations i
     WHERE i.token = p_token
     LIMIT 1
$fn$;
"""

_INVITATION_TOKEN_FN_REVOKE = (
    "REVOKE ALL ON FUNCTION public.invitation_by_token(text) FROM PUBLIC;"
)

_INVITATION_TOKEN_FN_GRANT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        GRANT EXECUTE ON FUNCTION public.invitation_by_token(text) TO sales_app;
    END IF;
END
$$;
"""


def upgrade() -> None:
    # One statement per op.execute(): asyncpg's extended-query protocol rejects
    # several commands in one prepared statement.
    op.execute(_INVITATION_TOKEN_FN)
    op.execute(_INVITATION_TOKEN_FN_REVOKE)
    op.execute(_INVITATION_TOKEN_FN_GRANT)
    # The permissive read policy goes away with the lookup it existed for; the
    # canonical tenant_isolation policy and FORCE RLS stay exactly as they were.
    op.execute("DROP POLICY IF EXISTS invitations_accept_read ON invitations")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.invitation_by_token(text)")

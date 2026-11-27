"""The invitation lookup is a function, not a second permissive policy.

``fe2026112609`` replaced the permissive ``invitations_accept_read`` policy with
``public.invitation_tenant_by_token`` and dropped the policy in the same revision. Then
``fe2026112618`` (written after a production accept returned 404) re-created the policy to
converge an environment where it was missing — and that re-creation is the wrong repair: a
second permissive policy on a tenant table is OR-ed with ``tenant_isolation`` by Postgres, so
any session able to set ``app.invitation_token`` could read that invitation row. The
schema-wide guard reports exactly that, and it is right to.

The accept flow does not need the policy. ``app/modules/identity/services/tenant.py`` resolves
the tenant with ``SELECT public.invitation_tenant_by_token(:token)`` (SECURITY DEFINER, one
row, token equality only) and then binds the tenant and reads under ``tenant_isolation`` like
every other query. So this revision converges on the object that actually carries the flow:
it drops the permissive policy if any environment still has it, and re-asserts the function
with its revoke/grant so a database missing the function has a path back.

``app/core/boot.py`` now watches the function (``REQUIRED_PUBLIC_FUNCTIONS``) instead of the
policy, so the next drift is reported by the process, not by a teammate who cannot join.

Revision ID: fe2026112619
Revises: fe2026112618
Create Date: 2026-11-27 08:45:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112619"
down_revision: str | None = "fe2026112618"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INVITATION_TOKEN_FN = """
CREATE OR REPLACE FUNCTION public.invitation_tenant_by_token(p_token text)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
    SELECT i.tenant_id
      FROM public.invitations i
     WHERE i.token = p_token
     LIMIT 1
$fn$;
"""


def upgrade() -> None:
    # One statement per op.execute(): asyncpg's extended-query protocol rejects several
    # commands in one prepared statement.
    op.execute("DROP POLICY IF EXISTS invitations_accept_read ON invitations")
    op.execute(_INVITATION_TOKEN_FN)
    op.execute("REVOKE ALL ON FUNCTION public.invitation_tenant_by_token(text) FROM PUBLIC;")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
                GRANT EXECUTE ON FUNCTION public.invitation_tenant_by_token(text) TO sales_app;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Nothing to undo. The policy is deliberately not restored (it was the hole), and the
    # function belongs to fe2026112609: dropping it here would break that revision's
    # downgrade order and leave the accept flow without its lookup.
    pass

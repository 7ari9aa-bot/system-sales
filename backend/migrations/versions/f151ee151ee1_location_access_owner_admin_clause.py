"""location_access owner-admin grant clause (§151 Q3)

Revision ID: f151ee151ee1
Revises: e171ee171ee0
Create Date: 2026-09-22

The b2c3d4e5f6a7 sweep gave ``user_location_access`` a self-keyed policy
(members see/claim only their OWN grant rows). That makes the Q3 admin API
impossible: an owner managing a staff member's location access writes rows
whose ``user_id`` is NOT the actor, and FORCE RLS rejects them. This widens
BOTH clauses with a tenant-owner OR-branch — the actor may manage grants for
any location whose tenant they own — while keeping the self-branch for
ordinary members (unchanged behavior for login/claim paths).

Why ``r.code = 'owner'`` mirrors the app layer exactly: ``settings:write`` —
which gates every route in the Q3 router — is held only by the owner role in
the ROLE_MATRIX (provision.py). The RLS branch is the second belt, not a new
policy. Subqueries inside a policy run as the invoking user under RLS: the
tenant GUC is already bound on every request path that reaches these routes,
so ``locations``/``tenant_users`` stay tenant-visible inside the EXISTS.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f151ee151ee1"
down_revision: str | None = "e171ee171ee0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USER_GUARD = "NULLIF(current_setting('app.user_id', true), '')::uuid"

_SELF_CLAUSE = f"user_id = {_USER_GUARD}"
_ADMIN_CLAUSE = f"""EXISTS (
            SELECT 1
              FROM public.locations l
              JOIN public.tenant_users tu ON tu.tenant_id = l.tenant_id
              JOIN public.roles r ON r.id = tu.role_id
             WHERE l.id = user_location_access.location_id
               AND tu.user_id = {_USER_GUARD}
               AND r.code = 'owner'
        )"""


def upgrade() -> None:
    # One statement per op.execute(): asyncpg's extended protocol rejects
    # multiple commands per execute.
    op.execute("DROP POLICY IF EXISTS location_access ON public.user_location_access")
    op.execute(
        f"""CREATE POLICY location_access ON public.user_location_access
            USING ({_SELF_CLAUSE} OR {_ADMIN_CLAUSE})
            WITH CHECK ({_SELF_CLAUSE} OR {_ADMIN_CLAUSE})"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS location_access ON public.user_location_access")
    op.execute(
        f"""CREATE POLICY location_access ON public.user_location_access
            USING ({_SELF_CLAUSE})
            WITH CHECK ({_SELF_CLAUSE})"""
    )

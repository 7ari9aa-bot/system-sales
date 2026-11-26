"""Grant the DELETE that fe2026112503 promised but never issued.

fe2026112503 added the ``audit_logs_tenant_delete`` policy (own rows only,
older than one day) so ``security.audit_retention_days`` could purge old
audit rows — but it left the matching ``GRANT DELETE`` to "the provision
script", which production does not run. The policy alone is not enough:
``fd2026100409`` had already ``REVOKE``d DELETE from ``sales_app``, so every
``audit_retention_sweep`` died with

    asyncpg.exceptions.InsufficientPrivilegeError: permission denied for
    table audit_logs

and, before the per-job savepoint, that single failure aborted the whole
per-tenant batch — the reason no recurring sweep ran at all.

The grant is narrow on purpose: DELETE only, and only where the policy lets
it through. UPDATE stays revoked, so a row is still never modified in place;
the sweep can only remove a tenant's own rows past its retention window.

Revision ID: fe2026112608
Revises: fe2026112607
Create Date: 2026-11-26 12:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112608"
down_revision: str | None = "fe2026112607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT DELETE ON public.audit_logs TO sales_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON public.audit_logs FROM sales_app")

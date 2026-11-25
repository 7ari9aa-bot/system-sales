"""Add DELETE policy to audit_logs for the retention sweep.

The isolation-hardening migration (fd2026100409) deliberately made
``audit_logs`` append-only: INSERT and SELECT policies but no DELETE
policy, plus ``REVOKE UPDATE, DELETE`` from ``sales_app``. That was
correct when nothing ever purged audit rows.

``security.audit_retention_days`` introduces a tenant-scoped sweep that
deletes rows older than the retention window (0 = no deletion). This
migration:

* Adds a DELETE policy (``audit_logs_tenant_delete``) that allows a
  tenant to delete only its own rows **older than 1 day**, mirroring the
  existing ``audit_logs_tenant_read`` SELECT policy but with an age
  guard: ``created_at < now() - interval '1 day'``. This is a safety net
  on top of the sweep's own retention-window check — even a buggy sweep
  can never delete rows younger than 24 hours.
* The provision script is updated to ``GRANT DELETE`` to ``sales_app``
  (UPDATE stays revoked — rows are never modified, only old ones purged).

The sweep is the ONLY code path that deletes audit rows, and it is gated
by the tenant setting, so the append-only invariant holds for every
tenant that leaves the setting at its default (365 days) or sets it to 0.

Revision ID: fe2026112503
Revises: fe2026112502
Create Date: 2026-11-25 11:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112503"
down_revision: str | None = "fe2026112502"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DROP first for idempotency — safe on a fresh CI DB (no-op) and on
    # databases where a prior version of this migration already ran.
    op.execute("DROP POLICY IF EXISTS audit_logs_tenant_delete ON public.audit_logs")
    op.execute(
        """
        CREATE POLICY audit_logs_tenant_delete ON public.audit_logs
            FOR DELETE
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                AND created_at < now() - interval '1 day'
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS audit_logs_tenant_delete ON public.audit_logs")

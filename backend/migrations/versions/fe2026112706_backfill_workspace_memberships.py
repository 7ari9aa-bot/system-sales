"""Backfill the workspace grants that tenant membership used to imply.

``resolve_scope`` now refuses a workspace the caller has no row for. Without
this backfill that refusal would lock every existing customer out of their own
shop the moment the release lands: nobody has a row yet, because the table
arrived in the previous migration.

The grant being backfilled is exactly today's behaviour — every member of the
account, on every business of that account — so nothing changes for anyone
already working. What changes is that a business created *after* this release
gets rows only when someone is granted access to it, which is the point.

Revision ID: fe2026112706
Revises: fe2026112705
Create Date: 2026-11-28 00:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112706"
down_revision: str | None = "fe2026112705"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO workspace_memberships
            (workspace_id, user_id, tenant_id, is_default, created_at, updated_at)
        SELECT w.id, tu.user_id, w.tenant_id, false, now(), now()
        FROM workspaces w
        JOIN tenant_users tu ON tu.tenant_id = w.tenant_id
        ON CONFLICT (workspace_id, user_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # No inverse on purpose: the rows are indistinguishable from grants made by
    # hand after this release, and deleting them would revoke real access.
    pass

"""Grant ``settings:branch_write`` as a real permission row.

The policy module already lets a holder of ``settings:branch_write`` write a
``branch_delegable`` setting below tenant level, and ``provision.py`` lists it in the role
matrix — but no permission row was ever created, so no role could hold it. A manager could
not edit a branch's own settings even though the code was written for exactly that, and the
only way it would appear was running provisioning, which is not part of the deploy path.

Owner and manager get it: a manager tunes a branch or warehouse without gaining
``settings:write`` over tenant-wide settings. A cashier gets neither.

Revision ID: fe2026112606
Revises: fe2026112605
Create Date: 2026-11-26 12:58:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112606"
down_revision: str | None = "fe2026112605"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (id, code, resource, action)
        VALUES (gen_random_uuid(), 'settings:branch_write', 'settings', 'branch_write')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
          FROM roles r, permissions p
         WHERE r.code IN ('owner', 'manager')
           AND p.code = 'settings:branch_write'
         ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
         WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'settings:branch_write')
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'settings:branch_write'")

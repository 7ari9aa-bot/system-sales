"""Separate "may approve a settings change" from "may write a setting".

Approving a change request needed ``settings:write``: the reviewer had to hold the same
power as the person proposing the change, so a shop could not have a manager who reviews
without also being able to write every key directly. ``settings:approve`` splits them.

Granted to owner and manager: a manager reviews a proposal without gaining
``settings:write``, and a cashier still holds neither.

Revision ID: fe2026112604
Revises: fe2026112603
Create Date: 2026-11-26 09:35:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112604"
down_revision: str | None = "fe2026112603"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (id, code, resource, action)
        VALUES (gen_random_uuid(), 'settings:approve', 'settings', 'approve')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
          FROM roles r, permissions p
         WHERE r.code IN ('owner', 'manager')
           AND p.code = 'settings:approve'
         ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
         WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'settings:approve')
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'settings:approve'")

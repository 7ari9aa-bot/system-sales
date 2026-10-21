"""pos:override: the permission to sell past a till's discount ceiling.

Revision ID: fe2026102102
Revises: fe2026102101
Create Date: 2026-10-21 04:30:00.000000

The discount ceiling on a POS profile is now enforced by the sale itself. Going over it needs this
permission, which owners and managers get and staff do not (the ai:approve pattern). provision.py
seeds NEW tenants; this migration brings EXISTING databases to the same matrix, so a manager already
in production is not locked out of the override. Idempotent: safe to re-run.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026102102"
down_revision: str | None = "fe2026102101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (id, code, resource, action)
        VALUES (gen_random_uuid(), 'pos:override', 'pos', 'override')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.code IN ('owner', 'manager') AND p.code = 'pos:override'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'pos:override')
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'pos:override'")

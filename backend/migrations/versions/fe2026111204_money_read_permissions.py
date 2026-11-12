"""finance:read and purchasing:read: who may see the shop's money through the assistant.

Revision ID: fe2026111204
Revises: fe2026111203
Create Date: 2026-11-12 20:00:00.000000

The owner assistant is gaining tools that read profit, expenses and supplier balances. Each tool
declares the permission its asker must hold, and a tool they lack is never shown to the model.
provision.py seeds NEW tenants; this brings EXISTING databases to the same matrix. OWNER ONLY: a
manager does not receive money visibility by being a manager (the owner grants it), and staff,
who already hold analytics:read, never do. Idempotent: safe to re-run.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111204"
down_revision: str | None = "fe2026111203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (id, code, resource, action)
        VALUES (gen_random_uuid(), 'finance:read', 'finance', 'read'),
               (gen_random_uuid(), 'purchasing:read', 'purchasing', 'read')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.code IN ('owner') AND p.code IN ('finance:read', 'purchasing:read')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions WHERE code IN ('finance:read', 'purchasing:read')
        )
        """
    )
    op.execute("DELETE FROM permissions WHERE code IN ('finance:read', 'purchasing:read')")

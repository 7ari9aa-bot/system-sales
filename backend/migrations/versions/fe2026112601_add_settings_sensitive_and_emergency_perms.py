"""Add settings:read_sensitive and settings:emergency_bypass permissions.

Two new permissions:
* ``settings:read_sensitive`` — gated to Owner by default. Without it, the
  router masks the *value* of any setting whose ``sensitivity`` is SENSITIVE
  (team.require_2fa, security.*, billing.*) in the read, history and override
  endpoints. The key and metadata still appear; only the value is hidden.
* ``settings:emergency_bypass`` — gated to Owner by default. Without it,
  rollback / restore / apply_preset may not skip the change-request approval
  flow for APPROVAL_REQUIRED settings. With it, those operations may bypass
  approval in a documented emergency, and an independent audit row records
  the bypass.

Revision ID: fe2026112601
Revises: fe2026112506
Create Date: 2026-11-26 00:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026112601"
down_revision: str | None = "fe2026112506"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (id, code, resource, action)
        VALUES (gen_random_uuid(), 'settings:read_sensitive', 'settings', 'read_sensitive')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO permissions (id, code, resource, action)
        VALUES (gen_random_uuid(), 'settings:emergency_bypass', 'settings', 'emergency_bypass')
        ON CONFLICT (code) DO NOTHING
        """
    )
    # Grant both to the owner role only.
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
          FROM roles r, permissions p
         WHERE r.code = 'owner'
           AND p.code IN ('settings:read_sensitive', 'settings:emergency_bypass')
         ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
         WHERE permission_id IN (
             SELECT id FROM permissions
              WHERE code IN ('settings:read_sensitive', 'settings:emergency_bypass')
         )
        """
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ('settings:read_sensitive', 'settings:emergency_bypass')"
    )

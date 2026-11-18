"""Settings: one override per (tenant, key, scope, scope_id), NULL scope_id included.

Revision ID: fe2026111802
Revises: fe2026111801
Create Date: 2026-11-18 15:30:00.000000

``tenant_settings.scope_id`` is NULL for tenant-level settings. A plain UNIQUE
constraint treats every NULL as different, so two concurrent writes could both
insert a tenant-level row for the same key and every later read would raise
``MultipleResultsFound``. ``NULLS NOT DISTINCT`` (PostgreSQL 15+) makes NULL equal
to NULL for this constraint only. Any duplicate that slipped in is removed first,
keeping the most recently updated row.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fe2026111802"
down_revision: str | None = "fe2026111801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the newest row of each duplicate group; history rows pointing at the
    # removed ones become setting_id NULL through the existing ON DELETE SET NULL.
    op.execute(
        """
        DELETE FROM tenant_settings t
        USING (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY tenant_id, key, scope, scope_id
                       ORDER BY updated_at DESC, id DESC
                   ) AS rn
            FROM tenant_settings
        ) d
        WHERE t.id = d.id AND d.rn > 1
        """
    )
    op.execute("ALTER TABLE tenant_settings DROP CONSTRAINT uq_tenant_settings_key_scope")
    op.execute(
        """
        ALTER TABLE tenant_settings
        ADD CONSTRAINT uq_tenant_settings_key_scope
        UNIQUE NULLS NOT DISTINCT (tenant_id, key, scope, scope_id)
        """
    )
    # A tenant-level row must not carry a scope id, and every other scope must.
    op.execute(
        """
        ALTER TABLE tenant_settings
        ADD CONSTRAINT ck_tenant_settings_scope_id
        CHECK ((scope = 'tenant') = (scope_id IS NULL))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_settings DROP CONSTRAINT ck_tenant_settings_scope_id")
    op.execute("ALTER TABLE tenant_settings DROP CONSTRAINT uq_tenant_settings_key_scope")
    op.execute(
        """
        ALTER TABLE tenant_settings
        ADD CONSTRAINT uq_tenant_settings_key_scope
        UNIQUE (tenant_id, key, scope, scope_id)
        """
    )

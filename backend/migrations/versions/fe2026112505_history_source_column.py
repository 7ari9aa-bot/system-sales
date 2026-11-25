"""Add source column to tenant_settings_history (§174 extended auditing).

Revision ID: fe2026112505
Revises: fe2026112504
Create Date: 2026-11-25

The new ``source`` column records where each change came from (api, preset,
restore, migration, rollback, change_request), enabling filtered audit search.
"""

from alembic import op

revision = "fe2026112505"
down_revision = "fe2026112504"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_settings_history "
        "ADD COLUMN IF NOT EXISTS source VARCHAR(31) NOT NULL DEFAULT 'api'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tenant_settings_history_source "
        "ON tenant_settings_history (tenant_id, source)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenant_settings_history_source")
    op.execute("ALTER TABLE tenant_settings_history DROP COLUMN IF EXISTS source")

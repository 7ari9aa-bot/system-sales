"""w8_notifications_realtime

- Add notifications table / in-app user notifications (§B3)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "a7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure notifications has all in-app fields needed by §B3
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'notifications') THEN
                CREATE TABLE notifications (
                    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    kind VARCHAR(31) NOT NULL DEFAULT 'system',
                    title VARCHAR(127),
                    body TEXT NOT NULL,
                    action_url VARCHAR(512),
                    payload JSONB NOT NULL DEFAULT '{}',
                    read_at TIMESTAMPTZ,
                    dedup_key VARCHAR(127),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            ELSE
                ALTER TABLE notifications ADD COLUMN IF NOT EXISTS kind VARCHAR(31) NOT NULL DEFAULT 'system';
                ALTER TABLE notifications ADD COLUMN IF NOT EXISTS title VARCHAR(127);
                ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_url VARCHAR(512);
                ALTER TABLE notifications ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}';
                ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ;
                ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(127);
            END IF;
        END $$;
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_notifications_tenant_user_read
        ON notifications (tenant_id, user_id, read_at);

        CREATE INDEX IF NOT EXISTS ix_notifications_dedup
        ON notifications (tenant_id, dedup_key)
        WHERE dedup_key IS NOT NULL;

        ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
        ALTER TABLE notifications FORCE ROW LEVEL SECURITY;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'notifications' AND policyname = 'notifications_tenant_isolation'
            ) THEN
                CREATE POLICY notifications_tenant_isolation ON notifications
                USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notifications_dedup")
    op.execute("DROP INDEX IF EXISTS ix_notifications_tenant_user_read")

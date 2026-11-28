"""Commercial application rows: what a plan includes, what was bought, what is installed.

Three tables, one release, because the access decision needs all three to answer
anything: an inclusion without an installation cannot open a screen, and an
installation without a purchase has no right behind it.

RLS ships with each table, not after: a tenant table without tenant_isolation
makes the boot reconciler refuse to start the service, and grants are explicit
because the provision script that used to patch them does not run in production.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "fe2026112707"
down_revision = "fe2026112706"
branch_labels = None
depends_on = None

POLICY = (
    "CREATE POLICY tenant_isolation ON {table} "
    "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
    "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _secure(table: str, indexes: list[tuple[str, str]]) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(POLICY.format(table=table))
    # sales_app is created by scripts/provision.py, which does not always run before Alembic: a
    # CI database has no such role, and a bare GRANT aborted the whole upgrade with
    # role "sales_app" does not exist (CI run 46087712727, backend shards, «alembic upgrade head»).
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO sales_app;
          END IF;
        END $$;
        """
    )
    for name, column in indexes:
        op.execute(f"CREATE INDEX {name} ON {table} ({column})")


def upgrade() -> None:
    op.create_table(
        "plan_application_inclusions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("application_key", sa.String(64), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("plan_id", "application_key", name="uq_plan_app_inclusion"),
    )
    _secure(
        "plan_application_inclusions",
        [("ix_plan_app_inclusions_tenant_id", "tenant_id")],
    )

    op.create_table(
        "subscription_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("application_key", sa.String(64), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "subscription_id", "application_key", "workspace_id", name="uq_subscription_item_scope"
        ),
    )
    _secure(
        "subscription_items",
        [
            ("ix_subscription_items_tenant_id", "tenant_id"),
            ("ix_subscription_items_workspace_id", "workspace_id"),
        ],
    )

    op.create_table(
        "workspace_app_installations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("application_key", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="not_installed"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "workspace_id", "application_key", name="uq_workspace_app_installation"
        ),
    )
    _secure(
        "workspace_app_installations",
        [
            ("ix_workspace_app_installations_tenant_id", "tenant_id"),
            ("ix_workspace_app_installations_workspace_id", "workspace_id"),
        ],
    )


def downgrade() -> None:
    op.drop_table("workspace_app_installations")
    op.drop_table("subscription_items")
    op.drop_table("plan_application_inclusions")

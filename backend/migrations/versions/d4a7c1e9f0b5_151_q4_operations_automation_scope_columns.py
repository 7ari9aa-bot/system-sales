"""§151 Q4 — scope columns for operations & automation domain tables.

The hierarchy tables (workspaces/locations/user_location_access), the scope
GUCs, and the 71-table scope retrofit landed in Q1-Q3 (48528b41d6db). These
seven tables were still tenant-only: tasks, SLA policies/events, business
calendars, and the workflow trio. ADR-048 assigns them an ownership scope
(operations = Location-level, automation = Workspace-level), and the Q4
stamp mechanism (WorkspaceScopeMixin INSERT defaults from the request scope)
needs the columns to exist before it can fill them.

Same shape as the W2A retrofit: nullable workspace_id/location_id, FKs with
ondelete SET NULL (a removed hierarchy node never deletes business rows),
and one index per column so scoped reads stay cheap. NULL keeps every
existing row tenant-wide — no backfill, no behavior change until a scoped
request writes.

Calls are written out per table (no loop): the static model/migration drift
guard (tests/test_migrations.py) reads this file's AST and must see every
column as a literal add_column argument.

Revision ID: d4a7c1e9f0b5
Revises: f151ee151ee1
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7c1e9f0b5"
down_revision: str | None = "f151ee151ee1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPE_TABLES = (
    "tasks",
    "sla_policies",
    "business_calendars",
    "sla_events",
    "workflows",
    "workflow_executions",
    "workflow_failures",
)


def upgrade() -> None:
    op.add_column("tasks", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("tasks", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_tasks_workspace_id"), "tasks", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_tasks_location_id"), "tasks", ["location_id"], unique=False)
    op.create_foreign_key(None, "tasks", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(None, "tasks", "locations", ["location_id"], ["id"], ondelete="SET NULL")
    op.add_column("sla_policies", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("sla_policies", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_sla_policies_workspace_id"), "sla_policies", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_sla_policies_location_id"), "sla_policies", ["location_id"], unique=False)
    op.create_foreign_key(None, "sla_policies", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(None, "sla_policies", "locations", ["location_id"], ["id"], ondelete="SET NULL")
    op.add_column("business_calendars", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("business_calendars", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_business_calendars_workspace_id"), "business_calendars", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_business_calendars_location_id"), "business_calendars", ["location_id"], unique=False)
    op.create_foreign_key(None, "business_calendars", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(None, "business_calendars", "locations", ["location_id"], ["id"], ondelete="SET NULL")
    op.add_column("sla_events", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("sla_events", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_sla_events_workspace_id"), "sla_events", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_sla_events_location_id"), "sla_events", ["location_id"], unique=False)
    op.create_foreign_key(None, "sla_events", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(None, "sla_events", "locations", ["location_id"], ["id"], ondelete="SET NULL")
    op.add_column("workflows", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("workflows", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_workflows_workspace_id"), "workflows", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_workflows_location_id"), "workflows", ["location_id"], unique=False)
    op.create_foreign_key(None, "workflows", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(None, "workflows", "locations", ["location_id"], ["id"], ondelete="SET NULL")
    op.add_column("workflow_executions", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("workflow_executions", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_workflow_executions_workspace_id"), "workflow_executions", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_workflow_executions_location_id"), "workflow_executions", ["location_id"], unique=False)
    op.create_foreign_key(None, "workflow_executions", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(None, "workflow_executions", "locations", ["location_id"], ["id"], ondelete="SET NULL")
    op.add_column("workflow_failures", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column("workflow_failures", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_workflow_failures_workspace_id"), "workflow_failures", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_workflow_failures_location_id"), "workflow_failures", ["location_id"], unique=False)
    op.create_foreign_key(None, "workflow_failures", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(None, "workflow_failures", "locations", ["location_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    # Dropping the columns drops their FKs too on Postgres — no need to
    # name constraints the upgrade left auto-named.
    op.drop_index(op.f("ix_tasks_location_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_workspace_id"), table_name="tasks")
    op.drop_column("tasks", "location_id")
    op.drop_column("tasks", "workspace_id")
    op.drop_index(op.f("ix_sla_policies_location_id"), table_name="sla_policies")
    op.drop_index(op.f("ix_sla_policies_workspace_id"), table_name="sla_policies")
    op.drop_column("sla_policies", "location_id")
    op.drop_column("sla_policies", "workspace_id")
    op.drop_index(op.f("ix_business_calendars_location_id"), table_name="business_calendars")
    op.drop_index(op.f("ix_business_calendars_workspace_id"), table_name="business_calendars")
    op.drop_column("business_calendars", "location_id")
    op.drop_column("business_calendars", "workspace_id")
    op.drop_index(op.f("ix_sla_events_location_id"), table_name="sla_events")
    op.drop_index(op.f("ix_sla_events_workspace_id"), table_name="sla_events")
    op.drop_column("sla_events", "location_id")
    op.drop_column("sla_events", "workspace_id")
    op.drop_index(op.f("ix_workflows_location_id"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_workspace_id"), table_name="workflows")
    op.drop_column("workflows", "location_id")
    op.drop_column("workflows", "workspace_id")
    op.drop_index(op.f("ix_workflow_executions_location_id"), table_name="workflow_executions")
    op.drop_index(op.f("ix_workflow_executions_workspace_id"), table_name="workflow_executions")
    op.drop_column("workflow_executions", "location_id")
    op.drop_column("workflow_executions", "workspace_id")
    op.drop_index(op.f("ix_workflow_failures_location_id"), table_name="workflow_failures")
    op.drop_index(op.f("ix_workflow_failures_workspace_id"), table_name="workflow_failures")
    op.drop_column("workflow_failures", "location_id")
    op.drop_column("workflow_failures", "workspace_id")
